from __future__ import annotations

from typing import Any


SECTOR_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "financials",
        ("금융", "은행", "증권", "보험", "카드", "캐피탈", "financial"),
    ),
    (
        "information_technology",
        (
            "반도체",
            "소프트웨어",
            "하드웨어",
            "전자",
            "디스플레이",
            "정보기술",
            "it",
            "technology",
        ),
    ),
    (
        "healthcare",
        ("제약", "바이오", "건강", "의료", "헬스", "health"),
    ),
    (
        "consumer_staples",
        (
            "필수소비",
            "식품",
            "음료",
            "담배",
            "생활용품",
            "consumer staples",
        ),
    ),
    (
        "consumer_discretionary",
        (
            "경기소비",
            "자동차",
            "의류",
            "유통",
            "호텔",
            "레저",
            "미디어",
            "consumer discretionary",
        ),
    ),
    (
        "industrials",
        (
            "산업재",
            "기계",
            "조선",
            "운송",
            "항공",
            "건설",
            "방산",
            "상사",
            "industrial",
        ),
    ),
    (
        "materials",
        ("소재", "화학", "철강", "금속", "종이", "비금속", "material"),
    ),
    (
        "energy",
        ("에너지", "정유", "석유", "가스", "석탄", "energy"),
    ),
    (
        "communication_services",
        ("통신", "커뮤니케이션", "인터넷", "communication"),
    ),
    (
        "utilities",
        ("유틸리티", "전력", "수도", "가스공급", "utility"),
    ),
    (
        "real_estate",
        ("부동산", "리츠", "real estate"),
    ),
)


def classify_sector(row: dict[str, Any]) -> str:
    if row.get("is_financial"):
        return "financials"
    text = " ".join(
        str(row.get(key) or "").strip().lower()
        for key in ("sector", "industry", "company")
    )
    for group, keywords in SECTOR_KEYWORDS:
        if any(keyword.lower() in text for keyword in keywords):
            return group
    return "other"
