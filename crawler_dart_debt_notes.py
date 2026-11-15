"""Cache verified annual debt balances from OpenDART XBRL notes."""
from __future__ import annotations

import argparse
from collections import defaultdict
from io import BytesIO
import json
import os
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

import requests

from collector_common import USER_AGENT, atomic_write_json
from dart_financial_storage import load_financial_panel
from env_loader import load_env_file


XBRL_URL = "https://opendart.fss.or.kr/api/fnlttXbrl.xml"
CACHE_NAME = "dart_debt_notes.json"
DEFAULT_PANEL = Path("data/dart_financial_panel.json")
PILOT_CODES = "093050,192820"
COMPONENTS = (
    "short_term_borrowings", "current_portion_long_term_debt", "long_term_borrowings",
    "current_bonds", "bonds", "lease_liabilities_current", "lease_liabilities_noncurrent",
)
XBRL = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
BASIS = ("ConsolidatedAndSeparateFinancialStatementsAxis", "ConsolidatedMember")
REPORTED = ("CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis", "ReportedAmountMember")
FINANCING_AXIS = "LiabilitiesArisingFromFinancingActivitiesAxis"
FINANCING_BALANCE = "LiabilitiesArisingFromFinancingActivities"
MATURITY_AXIS = "ClassesOfCurrentAndNoncurrentValuesUsedForChangesInAssetAndLiabilityAxis"
CONVERTIBLE_BOND_MEMBER = "ConvertibleBondsOfLiabilitiesArisingFromFinancingActivitiesMemberOfDisclosureOfReconciliationOfLiabilitiesArisingFromFinancingActivitiesTableOfMember"
PREFERRED_MEMBERS = (
    "RedeemableConvertiblePreferredStockLiabilityMemberOfLiabilitiesArisingFromFinancingActivitiesMemberOfDisclosureOfReconciliationOfLiabilitiesArisingFromFinancingActivitiesTableOfMember",
    "ConvertibleRedeemablePreferredStockLiabilitiesOfLiabilitiesArisingFromFinancingActivitiesMemberOfDisclosureOfReconciliationOfLiabilitiesArisingFromFinancingActivitiesTableOfMember",
)
LONG_LOANS = "NoncurrentPortionOfNoncurrentLoansReceived"
CURRENT_BONDS = "CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued"
LONG_BONDS = "NoncurrentPortionOfNoncurrentBondsIssued"
ANCHORS = {"assets": "Assets", "equity": "Equity", "liabilities": "Liabilities"}


def local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def maturity_dimension(maturity: str) -> tuple[str, str]:
    return MATURITY_AXIS, f"AssetAndLiabilityClassifiedAs{maturity}Member"


class AnnualFacts:
    def __init__(self, root: ET.Element, period_end: str):
        unit_ids = {
            unit.get("id") for unit in root.findall(f"{{{XBRL}}}unit")
            if local_name(unit.findtext(f"{{{XBRL}}}measure") or "") == "KRW"
        }
        contexts = {}
        for context in root.findall(f"{{{XBRL}}}context"):
            if context.findtext(f"{{{XBRL}}}period/{{{XBRL}}}instant") != period_end:
                continue
            if context.find(f".//{{{XBRLDI}}}typedMember") is not None:
                continue
            dimensions = frozenset(
                (local_name(member.get("dimension", "")), local_name(member.text or ""))
                for member in context.iter(f"{{{XBRLDI}}}explicitMember")
            )
            if BASIS in dimensions:
                contexts[context.get("id")] = dimensions - {BASIS}

        self.values = defaultdict(set)
        for fact in root:
            context = contexts.get(fact.get("contextRef"))
            amount = (fact.text or "").strip()
            if context is not None and fact.get("unitRef") in unit_ids and re.fullmatch(r"\d+", amount):
                self.values[(local_name(fact.tag), context)].add(int(amount))

    def amount(self, name: str, *dimensions: tuple[str, str]) -> int | None:
        amounts = self.values.get((name, frozenset(dimensions)), set())
        if len(amounts) > 1:
            raise ValueError(f"Conflicting XBRL amounts for {name}")
        return next(iter(amounts), None)

    def require(self, name: str, *dimensions: tuple[str, str]) -> int:
        amount = self.amount(name, *dimensions)
        if amount is None:
            raise ValueError(f"Missing XBRL amount for {name}")
        return amount

def financing_loans(facts: AnnualFacts, current_bonds: int, long_bonds: int) -> tuple[int, int, int, int]:
    """Disaggregate the financing roll-forward, which includes ordinary bonds in loans."""
    current_dim = maturity_dimension("Current")
    long_dim = maturity_dimension("Noncurrent")
    short = facts.require(FINANCING_BALANCE, current_dim, (FINANCING_AXIS, "ShorttermBorrowingsMember"))
    long_member = (FINANCING_AXIS, "LongtermBorrowingsMember")
    current_long_and_bonds = facts.require(FINANCING_BALANCE, current_dim, long_member)
    long_and_bonds = facts.require(FINANCING_BALANCE, long_dim, long_member)
    current_long = current_long_and_bonds - current_bonds
    long = long_and_bonds - long_bonds
    convertible = facts.amount("ConvertibleBondsNet", REPORTED) or 0
    represented_convertible = facts.amount(FINANCING_BALANCE, current_dim, (FINANCING_AXIS, CONVERTIBLE_BOND_MEMBER)) or 0
    if convertible != represented_convertible:
        raise ValueError("Convertible bond balance does not reconcile")
    total = facts.amount("LoansReceived", REPORTED)
    if total is None:
        total = facts.require("CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived", REPORTED) + facts.require(LONG_LOANS, REPORTED)
    if short + current_long + long != total:
        raise ValueError("Loans do not reconcile with the disclosed balance")

    excluded = sum(
        facts.amount(FINANCING_BALANCE, current_dim, (FINANCING_AXIS, member)) or 0
        for member in (*PREFERRED_MEMBERS, "DerivativeLiabilitiesMember")
    )
    current_financing = short + current_long_and_bonds + convertible + facts.require("CurrentLeaseLiabilities", REPORTED) + excluded
    long_financing = long_and_bonds + facts.require("NoncurrentLeaseLiabilities", REPORTED)
    fiscal_current = facts.amount(FINANCING_BALANCE, current_dim)
    fiscal_long = facts.amount(FINANCING_BALANCE, long_dim)
    if fiscal_current is None and fiscal_long is None:
        reconciles = facts.require(FINANCING_BALANCE) == current_financing + long_financing
    else:
        reconciles = fiscal_current == current_financing and fiscal_long == long_financing
    if not reconciles:
        raise ValueError("Debt does not reconcile with the financing roll-forward")
    return short, current_long, long, convertible


def other_financial_liability_loans(facts: AnnualFacts, current_bonds: int, long_bonds: int) -> tuple[int, int, int, int]:
    """Reconcile the capital-management borrowing total with the maturity disclosure."""
    if facts.amount("ConvertibleBondsNet", REPORTED):
        raise ValueError("Convertible bonds require a maturity reconciliation")
    long = facts.require(LONG_LOANS, REPORTED)
    maturity_name = "CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived"
    lenders = [
        tuple(dimensions) for name, dimensions in facts.values
        if name == maturity_name and len(dimensions) == 1 and next(iter(dimensions))[0] == "CounterpartiesAxis"
        and facts.amount(LONG_LOANS, *dimensions) == long
    ]
    if len(lenders) != 1:
        raise ValueError("Long-term loan maturity is ambiguous")
    current_long = facts.require(maturity_name, *lenders[0]) - long
    current_loans = facts.require("Borrowings", REPORTED) - long - current_bonds - long_bonds
    current = facts.require("OtherCurrentFinancialLiabilities", REPORTED)
    noncurrent = facts.require("OtherNoncurrentFinancialLiabilities", REPORTED)
    current_lease = facts.require("CurrentLeaseLiabilities", REPORTED)
    long_lease = facts.require("NoncurrentLeaseLiabilities", REPORTED)
    derivatives = facts.amount("CurrentDerivativeLiabilities", REPORTED) or 0
    # These notes report whole millions of won, while the panel stores won.
    if max(
        abs(current - current_loans - current_bonds - current_lease - derivatives),
        abs(noncurrent - long - long_bonds - long_lease),
    ) > 1_000_000:
        raise ValueError("Debt does not reconcile with the financial liability disclosure")
    return current_loans - current_long, current_long, long, 0


def row_identity(row: dict) -> dict:
    return {key: row.get(key) for key in ("ticker", "corp_code", "fiscal_year", "receipt_number", "detail_basis", "currency")}


def extract_debt_note(archive: bytes, row: dict) -> dict:
    period_end = f"{row['fiscal_year']}-12-31"
    instance = f"entity{row['corp_code']}_{period_end}.xbrl"
    with ZipFile(BytesIO(archive)) as zipped:
        root = ET.fromstring(zipped.read(instance))
    facts = AnnualFacts(root, period_end)
    current_bonds = facts.require(CURRENT_BONDS, REPORTED)
    long_bonds = facts.require(LONG_BONDS, REPORTED)
    current_lease = facts.require("CurrentLeaseLiabilities", REPORTED)
    long_lease = facts.require("NoncurrentLeaseLiabilities", REPORTED)
    if current_lease + long_lease != facts.require("LeaseLiabilities", REPORTED):
        raise ValueError("Lease balances do not reconcile")
    financing_short = facts.amount(FINANCING_BALANCE, maturity_dimension("Current"), (FINANCING_AXIS, "ShorttermBorrowingsMember"))
    if financing_short is not None:
        if current_bonds + long_bonds != facts.require("BondsIssued", REPORTED):
            raise ValueError("Bond balances do not reconcile")
        short, current_long, long, convertible = financing_loans(facts, current_bonds, long_bonds)
    else:
        short, current_long, long, convertible = other_financial_liability_loans(facts, current_bonds, long_bonds)
    return {
        **row_identity(row),
        "period_end": period_end,
        "source": "OpenDART fnlttXbrl.xml",
        "anchors": {key: facts.require(concept) for key, concept in ANCHORS.items()},
        "accounts": dict(zip(COMPONENTS, (short, current_long, long, current_bonds + convertible, long_bonds, current_lease, long_lease))),
        "current_convertible_bonds": convertible,
    }


def eligible_row(row: dict) -> bool:
    return (
        row.get("detail_basis") == row.get("statement_basis") == "CFS"
        and row.get("currency") == "KRW" and row.get("report_code") == "11011"
        and row.get("detail_status") == "complete" and not row.get("is_financial")
        and not (row.get("detail_validation") or {}).get("calculation_blocked")
        and bool(re.fullmatch(r"\d{14}", row.get("receipt_number") or ""))
    )


def debt_note_accounts(row: dict, note: dict | None) -> dict:
    if not note or not eligible_row(row) or any(note.get(key) != value for key, value in row_identity(row).items()):
        return {}
    accounts = row.get("detail_accounts") or {}
    anchors = note.get("anchors") or {}
    if any(type(anchors.get(key)) is not int or anchors[key] <= 0 or accounts.get(key) != anchors[key] for key in ANCHORS):
        return {}
    details = note.get("accounts") or {}
    if set(details) != set(COMPONENTS) or any(type(value) is not int or value < 0 for value in details.values()):
        return {}
    if sum(details.values()) > anchors["liabilities"]:
        return {}
    if any(accounts.get(key) is not None and accounts[key] != value for key, value in details.items()):
        return {}
    lease_total = accounts.get("lease_liabilities_total")
    if lease_total is not None and lease_total != details["lease_liabilities_current"] + details["lease_liabilities_noncurrent"]:
        return {}
    return {key: value for key, value in details.items() if accounts.get(key) is None}


def load_debt_notes(path: Path) -> dict:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported DART debt notes schema: {path}")
    return payload["filings"]


def sync_debt_notes(panel: dict, notes: dict) -> bool:
    changed = False
    for row in panel.get("observations") or []:
        note = notes.get(row.get("receipt_number"))
        if debt_note_accounts(row, note):
            if row.get("debt_note") != note:
                row["debt_note"] = note
                changed = True
        elif "debt_note" in row:
            del row["debt_note"]
            changed = True
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--codes", default=PILOT_CODES)
    parser.add_argument("--years", type=int, default=2, help="Recent annual filings per ticker")
    args = parser.parse_args()
    if args.years < 1:
        parser.error("--years must be positive")

    path = args.panel.with_name(CACHE_NAME)
    notes = load_debt_notes(path)
    selected = {code.strip() for code in args.codes.split(",")}
    by_ticker = defaultdict(list)
    for row in load_financial_panel(args.panel).get("observations") or []:
        if row["ticker"] in selected and eligible_row(row):
            by_ticker[row["ticker"]].append(row)
    load_env_file(Path(__file__).resolve().parent / ".env")
    key = os.environ.get("DART_API_KEY", "").strip()
    added = 0
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for ticker, rows in sorted(by_ticker.items()):
            for row in sorted(rows, key=lambda item: item["fiscal_year"], reverse=True)[:args.years]:
                receipt = row["receipt_number"]
                if receipt in notes or not key:
                    continue
                if all((row.get("detail_accounts") or {}).get(part) is not None for part in COMPONENTS):
                    continue
                try:
                    response = session.get(XBRL_URL, params={"crtfc_key": key, "rcept_no": receipt, "reprt_code": "11011"}, timeout=20)
                    response.raise_for_status()
                    note = extract_debt_note(response.content, row)
                    if not debt_note_accounts(row, note):
                        raise ValueError("Notes did not match the panel or offered no missing values")
                except requests.RequestException as exc:
                    print(f"[DEBT NOTES] {ticker} {receipt} unavailable: {type(exc).__name__}")
                    continue
                except (BadZipFile, ET.ParseError, KeyError, ValueError) as exc:
                    print(f"[DEBT NOTES] {ticker} {receipt} unverified: {exc}")
                    continue
                notes[receipt] = note
                added += 1
    if added:
        atomic_write_json(path, {
            "schema_version": 1,
            "source": "OpenDART XBRL annual debt notes",
            "count": len(notes),
            "filings": dict(sorted(notes.items())),
        })
    print(f"[DEBT NOTES] verified filings added={added}, cached={len(notes)}")


if __name__ == "__main__":
    main()
