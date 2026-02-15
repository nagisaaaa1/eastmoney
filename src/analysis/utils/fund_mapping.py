"""
Fund-to-index mapping helpers.
"""

from __future__ import annotations

import re
from typing import Optional


class FundIndexMapper:
    """
    Map fund names to likely benchmark index codes.
    """

    # (regex pattern, index code, readable name)
    MAPPING_RULES = [
        (r"(沪深|HS)300", "000300", "沪深300"),
        (r"中证500", "000905", "中证500"),
        (r"中证1000", "000852", "中证1000"),
        (r"科创50", "000688", "科创50"),
        (r"科创100", "000698", "科创100"),
        (r"创业板(指|ETF|50)", "399006", "创业板指"),
        (r"上证50", "000016", "上证50"),
        (r"中证A500", "000510", "中证A500"),
        (r"恒生科技", "HK_TECH", "恒生科技"),
        (r"纳斯达克|纳指", "US_NDX", "纳斯达克100"),
        (r"标普500", "US_SPX", "标普500"),
        (r"全指证券公司|证券ETF", "399975", "证券公司"),
        (r"中证医疗|医疗ETF", "399989", "中证医疗"),
        (r"中证白酒|白酒", "399997", "中证白酒"),
        (r"新能源车|新能车", "399976", "新能源车"),
        (r"光伏产业|光伏ETF", "931151", "光伏产业"),
    ]

    FOREIGN_INDEX_CODES = {"HK_TECH", "US_NDX", "US_SPX"}

    @staticmethod
    def guess_index_code(fund_name: str) -> Optional[str]:
        """
        Guess target index code from fund name.
        """
        if not fund_name:
            return None

        for pattern, code, _ in FundIndexMapper.MAPPING_RULES:
            if re.search(pattern, str(fund_name), re.IGNORECASE):
                return code
        return None

    @staticmethod
    def is_tracking_foreign(index_code: str) -> bool:
        """
        Whether index is foreign-market and requires a dedicated data source.
        """
        return str(index_code or "").upper() in FundIndexMapper.FOREIGN_INDEX_CODES

