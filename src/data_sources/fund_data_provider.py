"""
Fund data provider for recommendation factors.

This module keeps fund factor computation usable when TuShare permissions are
limited by falling back to AkShare data.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, Optional

import akshare as ak
import pandas as pd

from src.data_sources.tushare_client import get_fund_nav


_EMPTY_NAV = pd.DataFrame(columns=["nav_date", "unit_nav", "accum_nav"])
_AK_INDICATOR_UNIT_NAV = "\u5355\u4f4d\u51c0\u503c\u8d70\u52bf"
_AK_INDICATOR_ACCUM_NAV = "\u7d2f\u8ba1\u51c0\u503c\u8d70\u52bf"
_XQ_KEY_MANAGER = "\u57fa\u91d1\u7ecf\u7406"
_XQ_KEY_SIZE = "\u6700\u65b0\u89c4\u6a21"
_XQ_KEY_TYPE = "\u57fa\u91d1\u7c7b\u578b"
_XQ_KEY_INCEPTION = "\u6210\u7acb\u65f6\u95f4"
_UNIT_TRILLION = "\u4e07\u4ebf"
_UNIT_BILLION = "\u4ebf"
_UNIT_TEN_THOUSAND = "\u4e07"


def normalize_fund_code(code: str) -> str:
    """Return 6-digit fund code."""
    if not code:
        return ""
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if len(digits) >= 6:
        return digits[:6]
    return str(code).strip()


def _filter_nav_date_range(
    nav_df: pd.DataFrame,
    start_date: Optional[str],
    end_date: Optional[str],
) -> pd.DataFrame:
    if nav_df.empty:
        return _EMPTY_NAV.copy()

    result = nav_df.copy()
    if start_date:
        result = result[result["nav_date"] >= str(start_date)]
    if end_date:
        result = result[result["nav_date"] <= str(end_date)]

    return result.sort_values("nav_date").reset_index(drop=True)


def _to_nav_frame(
    df: pd.DataFrame,
    date_col: str,
    unit_col: Optional[str] = None,
    accum_col: Optional[str] = None,
) -> pd.DataFrame:
    if df is None or df.empty or date_col not in df.columns:
        return _EMPTY_NAV.copy()

    frame = pd.DataFrame()
    frame["nav_date"] = pd.to_datetime(df[date_col], errors="coerce")
    frame["unit_nav"] = (
        pd.to_numeric(df[unit_col], errors="coerce")
        if unit_col and unit_col in df.columns
        else pd.NA
    )
    frame["accum_nav"] = (
        pd.to_numeric(df[accum_col], errors="coerce")
        if accum_col and accum_col in df.columns
        else pd.NA
    )

    if "unit_nav" in frame.columns and "accum_nav" in frame.columns:
        frame["accum_nav"] = frame["accum_nav"].fillna(frame["unit_nav"])
        frame["unit_nav"] = frame["unit_nav"].fillna(frame["accum_nav"])

    frame = frame.dropna(subset=["nav_date", "unit_nav"], how="any")
    if frame.empty:
        return _EMPTY_NAV.copy()

    frame["nav_date"] = frame["nav_date"].dt.strftime("%Y%m%d")
    frame = frame.drop_duplicates(subset=["nav_date"], keep="last")
    return frame.sort_values("nav_date").reset_index(drop=True)


def _get_tushare_nav(fund_code: str, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
    code = normalize_fund_code(fund_code)
    if "." in str(fund_code):
        candidates = [str(fund_code).upper()]
    elif code.startswith("5"):
        candidates = [f"{code}.SH"]
    elif code.startswith(("15", "16")):
        candidates = [f"{code}.SZ"]
    else:
        candidates = [f"{code}.OF"] if code else []

    seen = set()
    for ts_code in candidates:
        if ts_code in seen:
            continue
        seen.add(ts_code)
        try:
            df = get_fund_nav(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception:
            df = None
        nav_df = _to_nav_frame(df, date_col="nav_date", unit_col="unit_nav", accum_col="accum_nav")
        if not nav_df.empty:
            return nav_df

    return _EMPTY_NAV.copy()


def _get_akshare_open_nav(fund_code: str) -> pd.DataFrame:
    code = normalize_fund_code(fund_code)
    if not code:
        return _EMPTY_NAV.copy()

    try:
        unit_df = ak.fund_open_fund_info_em(symbol=code, indicator=_AK_INDICATOR_UNIT_NAV)
        accum_df = ak.fund_open_fund_info_em(symbol=code, indicator=_AK_INDICATOR_ACCUM_NAV)
    except Exception:
        return _EMPTY_NAV.copy()

    if unit_df is None or unit_df.empty:
        return _EMPTY_NAV.copy()

    unit_date_col, unit_nav_col = unit_df.columns[0], unit_df.columns[1]
    nav_df = _to_nav_frame(unit_df, date_col=unit_date_col, unit_col=unit_nav_col)

    if accum_df is not None and not accum_df.empty and len(accum_df.columns) >= 2:
        accum_date_col, accum_nav_col = accum_df.columns[0], accum_df.columns[1]
        accum_nav = _to_nav_frame(accum_df, date_col=accum_date_col, accum_col=accum_nav_col)
        if not accum_nav.empty:
            merged = nav_df.merge(
                accum_nav[["nav_date", "accum_nav"]],
                on="nav_date",
                how="left",
                suffixes=("", "_y"),
            )
            merged["accum_nav"] = merged["accum_nav_y"].fillna(merged["accum_nav"])
            nav_df = merged.drop(columns=["accum_nav_y"], errors="ignore")

    return nav_df


def _get_akshare_etf_nav(fund_code: str) -> pd.DataFrame:
    code = normalize_fund_code(fund_code)
    if not code:
        return _EMPTY_NAV.copy()

    try:
        df = ak.fund_etf_fund_info_em(fund=code)
    except Exception:
        return _EMPTY_NAV.copy()

    if df is None or df.empty or len(df.columns) < 3:
        return _EMPTY_NAV.copy()

    date_col = df.columns[0]
    unit_nav_col = df.columns[1]
    accum_nav_col = df.columns[2]
    return _to_nav_frame(df, date_col=date_col, unit_col=unit_nav_col, accum_col=accum_nav_col)


def get_fund_nav_with_fallback(
    fund_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Get fund NAV data with fallback order:
    1) TuShare
    2) AkShare open-fund API
    3) AkShare ETF API
    """
    nav_df = _get_tushare_nav(fund_code, start_date, end_date)
    if nav_df.empty:
        nav_df = _get_akshare_open_nav(fund_code)
    if nav_df.empty:
        nav_df = _get_akshare_etf_nav(fund_code)

    return _filter_nav_date_range(nav_df, start_date, end_date)


def get_fallback_trade_date(now: Optional[datetime] = None) -> str:
    """
    Return a reasonable China-market reference date when trade calendar is missing.

    - Weekend: roll back to Friday
    - Weekday before 15:00: use previous business day
    - Weekday after 15:00: use current date
    """
    ref = now or datetime.now()

    if ref.weekday() >= 5:
        ref = ref - timedelta(days=ref.weekday() - 4)
    elif ref.hour < 15:
        ref = ref - timedelta(days=1)
        while ref.weekday() >= 5:
            ref = ref - timedelta(days=1)

    return ref.strftime("%Y%m%d")


def _parse_scale_to_billion(scale_text: str) -> Optional[float]:
    if not scale_text:
        return None

    text = str(scale_text).strip()
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if not m:
        return None

    value = float(m.group(1))
    if _UNIT_TRILLION in text:
        return value * 10000.0
    if _UNIT_BILLION in text:
        return value
    if _UNIT_TEN_THOUSAND in text:
        return value / 10000.0
    return value


@lru_cache(maxsize=2048)
def get_fund_basic_snapshot(fund_code: str) -> Dict[str, Optional[object]]:
    """
    Return lightweight fund metadata from AkShare.

    Cached to avoid repeated network calls during batch computations.
    """
    code = normalize_fund_code(fund_code)
    if not code:
        return {
            "manager_name": None,
            "fund_size_billion": None,
            "fund_type": None,
            "inception_date": None,
        }

    try:
        df = ak.fund_individual_basic_info_xq(symbol=code)
    except Exception:
        df = None

    if df is None or df.empty or len(df.columns) < 2:
        return {
            "manager_name": None,
            "fund_size_billion": None,
            "fund_type": None,
            "inception_date": None,
        }

    item_col, value_col = df.columns[0], df.columns[1]
    info = {}
    for _, row in df.iterrows():
        key = str(row.get(item_col, "")).strip()
        info[key] = row.get(value_col)

    return {
        "manager_name": info.get(_XQ_KEY_MANAGER),
        "fund_size_billion": _parse_scale_to_billion(str(info.get(_XQ_KEY_SIZE, ""))),
        "fund_type": info.get(_XQ_KEY_TYPE),
        "inception_date": info.get(_XQ_KEY_INCEPTION),
    }
