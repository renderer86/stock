import unittest

from crawler_naver_year_end_prices import (
    cached_for_period,
    parse_monthly_chart,
)


class NaverYearEndPricesTest(unittest.TestCase):
    def test_parses_last_monthly_close_for_each_year(self) -> None:
        content = b"""<?xml version="1.0" encoding="EUC-KR"?>
        <protocol><chartdata>
          <item data="20161130|10|12|9|11|100" />
          <item data="20161229|11|13|10|12|200" />
          <item data="20171228|20|24|19|23|300" />
        </chartdata></protocol>"""
        self.assertEqual(
            parse_monthly_chart(content),
            [
                {"year": 2016, "date": "20161229", "close": 12},
                {"year": 2017, "date": "20171228", "close": 23},
            ],
        )

    def test_cache_tracks_requested_period_even_for_delisted_stock(self) -> None:
        entry = {
            "status": "ok",
            "requested_end_year": 2025,
            "prices": [{"year": 2020, "date": "20201230", "close": 100}],
        }
        self.assertTrue(cached_for_period(entry, end_year=2025))
        self.assertFalse(cached_for_period(entry, end_year=2026))


if __name__ == "__main__":
    unittest.main()
