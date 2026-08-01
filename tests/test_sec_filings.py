from __future__ import annotations

import unittest

from crawler_sec_filings import (
    FORM_CATEGORIES,
    category_rows,
    company_maps,
    efts_hits,
    filing_url,
    subject_ciks,
)
from sec_edgar_client import SecAccessError, SecEdgarClient, sec_headers


class FakeResponse:
    def __init__(self, status_code: int, payload=None, url="https://sec.test") -> None:
        self.status_code = status_code
        self.payload = payload
        self.url = url
        self.headers = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


class SecEdgarClientTests(unittest.TestCase):
    def test_contact_email_is_in_user_agent(self) -> None:
        headers = sec_headers("owner@example.com")
        self.assertIn("owner@example.com", headers["User-Agent"])
        self.assertEqual(headers["Sec-Fetch-Mode"], "cors")

    def test_403_opens_circuit_and_avoids_more_requests(self) -> None:
        session = FakeSession([FakeResponse(403)])
        client = SecEdgarClient(
            session=session,
            sleeper=lambda _: None,
            min_interval=0.1,
        )

        with self.assertRaises(SecAccessError):
            client.get_json("https://www.sec.gov/blocked")
        with self.assertRaises(SecAccessError):
            client.get_json("https://www.sec.gov/not-requested")

        self.assertEqual(len(session.calls), 1)

    def test_efts_queries_each_form_instead_of_joining_them(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "hits": {
                            "total": {"value": 1},
                            "hits": [{"_source": {"adsh": "a", "form": "4"}}],
                        }
                    },
                ),
                FakeResponse(
                    200,
                    {
                        "hits": {
                            "total": {"value": 1},
                            "hits": [{"_source": {"adsh": "b", "form": "8-K"}}],
                        }
                    },
                ),
            ]
        )
        client = SecEdgarClient(
            session=session,
            sleeper=lambda _: None,
            min_interval=0.1,
        )

        hits = efts_hits(client, ("4", "8-K"), "2026-07-31", "2026-08-01", 10)

        self.assertEqual(len(hits), 2)
        self.assertEqual(
            [call[1]["params"]["forms"] for call in session.calls],
            ["4", "8-K"],
        )


class SecFilingParsingTests(unittest.TestCase):
    def test_schedule_13_forms_use_efts_names(self) -> None:
        self.assertEqual(
            FORM_CATEGORIES["activist_stakes"],
            (
                "SCHEDULE 13D",
                "SCHEDULE 13D/A",
                "SCHEDULE 13G",
                "SCHEDULE 13G/A",
            ),
        )

    def test_company_maps_normalize_class_share_symbols(self) -> None:
        by_symbol, by_cik = company_maps(
            {"0": {"ticker": "BRK.B", "cik_str": 1067983, "title": "Berkshire"}}
        )
        self.assertEqual(by_symbol["BRK-B"]["cik"], 1067983)
        self.assertEqual(by_cik[1067983], "BRK-B")

    def test_efts_hit_is_filtered_to_tracked_issuer(self) -> None:
        hit = {
            "_source": {
                "ciks": ["0002141713", "0001413447"],
                "display_names": [
                    "Reporting Owner (CIK 0002141713)",
                    "NXP Semiconductors N.V. (CIK 0001413447)",
                ],
                "form": "4",
                "adsh": "0002141713-26-000004",
                "file_date": "2026-07-31",
                "period_ending": "2026-07-29",
                "file_description": "FORM 4",
                "file_num": ["001-34841"],
                "film_num": ["261225489"],
                "items": [],
            }
        }

        rows = category_rows(
            [hit],
            "insider",
            {1413447},
            {1413447: "NXPI"},
            {"NXPI": {"name": "NXP Semiconductors N.V."}},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "NXPI")
        self.assertEqual(rows[0]["company"], "NXP Semiconductors N.V.")
        self.assertEqual(rows[0]["categories"], ["insider"])
        self.assertIn("000214171326000004", rows[0]["filing_url"])

    def test_insider_subject_excludes_reporting_owner(self) -> None:
        source = {"ciks": ["0001621104", "0001403161"]}
        self.assertEqual(subject_ciks(source, "insider"), [1403161])

    def test_schedule_subject_excludes_institutional_filer(self) -> None:
        source = {"ciks": ["0000103730", "0002012383"]}
        self.assertEqual(subject_ciks(source, "activist_stakes"), [103730])
        rows = category_rows(
            [{"_source": {**source, "adsh": "0002012383-26-003198"}}],
            "activist_stakes",
            {2012383},
            {2012383: "BLK"},
            {"BLK": {"name": "BlackRock, Inc."}},
        )
        self.assertEqual(rows, [])

    def test_filing_url_uses_filing_entity_cik(self) -> None:
        url = filing_url(
            {
                "ciks": ["0002141713", "0001413447"],
                "adsh": "0002141713-26-000004",
            }
        )
        self.assertEqual(
            url,
            "https://www.sec.gov/Archives/edgar/data/2141713/"
            "000214171326000004/0002141713-26-000004-index.html",
        )

    def test_filing_url_prefers_accession_submitter_cik(self) -> None:
        url = filing_url(
            {
                "ciks": ["0001621104", "0001403161"],
                "adsh": "0001403161-26-000107",
            }
        )
        self.assertEqual(
            url,
            "https://www.sec.gov/Archives/edgar/data/1403161/"
            "000140316126000107/0001403161-26-000107-index.html",
        )


if __name__ == "__main__":
    unittest.main()
