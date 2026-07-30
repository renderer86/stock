from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Iterable


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def median(values: Iterable[float]) -> float | None:
    cleaned = [value for value in values if math.isfinite(value)]
    return statistics.median(cleaned) if cleaned else None


def population_std(values: Iterable[float]) -> float | None:
    cleaned = [value for value in values if math.isfinite(value)]
    return statistics.pstdev(cleaned) if len(cleaned) >= 2 else None


def percentile_rank(value: float, population: list[float]) -> float | None:
    cleaned = sorted(item for item in population if math.isfinite(item))
    if not cleaned:
        return None
    below_or_equal = sum(item <= value for item in cleaned)
    return below_or_equal / len(cleaned)


def slope_through_origin(pairs: Iterable[tuple[float, float]]) -> float | None:
    cleaned = [
        (x_value, y_value)
        for x_value, y_value in pairs
        if math.isfinite(x_value) and math.isfinite(y_value)
    ]
    denominator = sum(x_value * x_value for x_value, _ in cleaned)
    if denominator <= 0:
        return None
    return sum(x_value * y_value for x_value, y_value in cleaned) / denominator


def equivalent_n_from_r(
    r_value: float,
    lag_years: int,
    minimum: float,
    maximum: float,
) -> float:
    # r >= 1 implies no observable fade in the sample. It is economically
    # capped rather than allowed to produce an infinite horizon.
    bounded_r = clamp(r_value, 0.01, 0.999)
    n_years = -float(lag_years) / math.log(bounded_r)
    return round(clamp(n_years, minimum, maximum), 3)


def extract_high_roe_spells(
    series: list[tuple[int, float]],
    threshold: float,
) -> list[dict[str, Any]]:
    """Extract spells using two-year entry/exit confirmation.

    A spell starts at the first of two consecutive high-ROE years. It ends
    after the first of two consecutive below-threshold years. An unfinished
    spell is right-censored.
    """

    if not series:
        return []
    ordered = sorted(series)
    spells: list[dict[str, Any]] = []
    active_start: int | None = None
    high_run = 0
    low_run = 0
    previous_year: int | None = None

    for year, roe in ordered:
        if previous_year is not None and year != previous_year + 1:
            if active_start is not None:
                spells.append(
                    {
                        "start_year": active_start,
                        "end_year": previous_year,
                        "duration": previous_year - active_start + 1,
                        "event_observed": False,
                        "ended_by": "data_gap",
                    }
                )
            active_start = None
            high_run = 0
            low_run = 0

        is_high = roe >= threshold
        if active_start is None:
            high_run = high_run + 1 if is_high else 0
            if high_run >= 2:
                active_start = year - 1
                low_run = 0
        else:
            low_run = 0 if is_high else low_run + 1
            if low_run >= 2:
                end_year = year - 2
                spells.append(
                    {
                        "start_year": active_start,
                        "end_year": end_year,
                        "duration": max(1, end_year - active_start + 1),
                        "event_observed": True,
                        "ended_by": "two_year_exit",
                    }
                )
                active_start = None
                high_run = 0
                low_run = 0
        previous_year = year

    if active_start is not None and previous_year is not None:
        spells.append(
            {
                "start_year": active_start,
                "end_year": previous_year,
                "duration": previous_year - active_start + 1,
                "event_observed": False,
                "ended_by": "right_censored",
            }
        )
    return spells


def trailing_streak(
    series: list[tuple[int, float]],
    threshold: float,
) -> dict[str, Any]:
    if not series:
        return {"years": 0, "confirmed": False, "through_year": None}
    ordered = sorted(series)
    count = 0
    previous_year: int | None = None
    through_year = ordered[-1][0]
    for year, roe in reversed(ordered):
        if previous_year is not None and year != previous_year - 1:
            break
        if roe < threshold:
            break
        count += 1
        previous_year = year
    return {
        "years": count,
        "confirmed": count >= 2,
        "through_year": through_year,
    }


def kaplan_meier_survival(
    spells: list[dict[str, Any]],
    horizon: int,
) -> dict[int, float]:
    """Return discrete S(t)=P(T>t) for t=0..horizon."""

    if not spells:
        return {year: 1.0 for year in range(horizon + 1)}
    events: dict[int, int] = defaultdict(int)
    censored: dict[int, int] = defaultdict(int)
    for spell in spells:
        duration = max(1, int(spell.get("duration") or 1))
        if spell.get("event_observed"):
            events[duration] += 1
        else:
            censored[duration] += 1

    at_risk = len(spells)
    survival = 1.0
    result = {0: 1.0}
    for year in range(1, horizon + 1):
        event_count = events.get(year, 0)
        if at_risk > 0 and event_count:
            survival *= 1.0 - event_count / at_risk
        result[year] = max(0.0, survival)
        at_risk -= event_count + censored.get(year, 0)
    return result


def restricted_mean_residual_life(
    survival: dict[int, float],
    survived_years: int,
    horizon: int,
) -> float | None:
    base = survival.get(min(survived_years, horizon))
    if base is None or base <= 0:
        return None
    remaining = sum(
        survival.get(year, 0.0) / base
        for year in range(survived_years + 1, horizon + 1)
    )
    return round(max(0.0, remaining), 3)
