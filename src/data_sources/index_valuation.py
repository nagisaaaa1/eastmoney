"""
Index valuation data source for PE/PB based valuation scoring.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Dict, Optional, Sequence

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class IndexValuationSource:
    """
    Fetch index valuation data (PE/PB and their historical percentiles).
    """

    LOOKBACK_WINDOW = 250 * 5
    CACHE_TTL_SECONDS = 60 * 60 * 24
    LEGULEGU_SYMBOL_BY_CODE = {
        "000016": "上证50",
        "000300": "沪深300",
        "000009": "上证380",
        "000688": "创业板50",
        "000905": "中证500",
        "000010": "上证180",
        "399324": "深证红利",
        "399330": "深证100",
        "000852": "中证1000",
        "000015": "上证红利",
        "000903": "中证100",
        "000906": "中证800",
    }

    @classmethod
    def fetch_index_valuation(cls, index_code: str) -> Optional[Dict[str, Any]]:
        """
        Get current PE/PB and historical percentile for a given index code.
        """
        clean_code = cls._normalize_index_code(index_code)
        if not clean_code:
            return None

        cache_bucket = int(time.time() // cls.CACHE_TTL_SECONDS)
        return cls._fetch_index_valuation_cached(clean_code, cache_bucket)

    @staticmethod
    @lru_cache(maxsize=64)
    def _fetch_index_valuation_cached(
        clean_code: str, cache_bucket: int
    ) -> Optional[Dict[str, Any]]:
        # cache_bucket is intentionally part of the cache key for TTL behavior.
        del cache_bucket

        try:
            raw_df = IndexValuationSource._fetch_legulegu_frame(clean_code)
            if raw_df is None or raw_df.empty:
                return None

            df = IndexValuationSource._normalize_valuation_frame(raw_df)
            if df.empty:
                return None

            history = df.tail(IndexValuationSource.LOOKBACK_WINDOW)
            if history.empty:
                return None

            latest = history.iloc[-1]
            current_pe = float(latest["pe"])
            current_pb = float(latest["pb"])

            pe_series = history["pe"].astype(float)
            pb_series = history["pb"].astype(float)
            if pe_series.empty or pb_series.empty:
                return None

            pe_rank = float((pe_series < current_pe).sum() / len(pe_series))
            pb_rank = float((pb_series < current_pb).sum() / len(pb_series))

            return {
                "index_code": clean_code,
                "pe": round(current_pe, 2),
                "pe_percentile": round(pe_rank, 4),
                "pb": round(current_pb, 2),
                "pb_percentile": round(pb_rank, 4),
                "source": "legulegu_akshare",
                "date": latest["date"].strftime("%Y-%m-%d"),
            }
        except Exception as exc:
            logger.error("Failed to fetch valuation for index %s: %s", clean_code, exc)
            return None

    @staticmethod
    def _fetch_legulegu_frame(clean_code: str) -> pd.DataFrame:
        """
        Fetch valuation history from Legulegu via AkShare.
        """
        symbol_candidates = []
        mapped_symbol = IndexValuationSource.LEGULEGU_SYMBOL_BY_CODE.get(clean_code)
        if mapped_symbol:
            symbol_candidates.append(mapped_symbol)
        symbol_candidates.append(clean_code)

        for symbol in symbol_candidates:
            try:
                pe_raw = ak.stock_index_pe_lg(symbol=symbol)
                pb_raw = ak.stock_index_pb_lg(symbol=symbol)
                pe_df = IndexValuationSource._normalize_metric_frame(
                    pe_raw,
                    date_candidates=("date", "日期", "trade_date", "cal_date"),
                    value_candidates=("滚动市盈率", "市盈率", "pe", "pe_ttm", "等权滚动市盈率"),
                    value_name="pe",
                )
                pb_df = IndexValuationSource._normalize_metric_frame(
                    pb_raw,
                    date_candidates=("date", "日期", "trade_date", "cal_date"),
                    value_candidates=("市净率", "pb", "pb_lf", "等权市净率"),
                    value_name="pb",
                )
                if pe_df.empty or pb_df.empty:
                    continue
                merged = pe_df.merge(pb_df, on="date", how="inner")
                if not merged.empty:
                    return merged
            except Exception as exc:
                logger.warning("Legulegu source failed for %s via %s: %s", clean_code, symbol, exc)

        return pd.DataFrame()

    @staticmethod
    def _normalize_index_code(index_code: str) -> str:
        text = str(index_code or "").strip()
        if not text:
            return ""
        return text.split(".")[0].strip()

    @staticmethod
    def _pick_col(columns: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
        col_map = {str(col).strip().lower(): str(col) for col in columns}
        for candidate in candidates:
            key = str(candidate).strip().lower()
            if key in col_map:
                return col_map[key]
        return None

    @staticmethod
    def _normalize_valuation_frame(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "pe", "pb"])

        if {"date", "pe", "pb"}.issubset(set(df.columns)):
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(df["date"], errors="coerce"),
                    "pe": pd.to_numeric(df["pe"], errors="coerce"),
                    "pb": pd.to_numeric(df["pb"], errors="coerce"),
                }
            )
        else:
            date_col = IndexValuationSource._pick_col(
                df.columns, ("date", "日期", "trade_date", "cal_date")
            )
            pe_col = IndexValuationSource._pick_col(
                df.columns,
                (
                    "pe",
                    "市盈率",
                    "pe_ttm",
                    "滚动市盈率",
                    "等权市盈率",
                    "中位数市盈率",
                ),
            )
            pb_col = IndexValuationSource._pick_col(
                df.columns,
                (
                    "pb",
                    "市净率",
                    "pb_lf",
                    "等权市净率",
                    "中位数市净率",
                ),
            )
            if not date_col or not pe_col or not pb_col:
                return pd.DataFrame(columns=["date", "pe", "pb"])
            frame = pd.DataFrame()
            frame["date"] = pd.to_datetime(df[date_col], errors="coerce")
            frame["pe"] = pd.to_numeric(df[pe_col], errors="coerce")
            frame["pb"] = pd.to_numeric(df[pb_col], errors="coerce")

        frame = frame.dropna(subset=["date", "pe", "pb"], how="any")
        if frame.empty:
            return frame

        frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        return frame.reset_index(drop=True)

    @staticmethod
    def _normalize_metric_frame(
        df: pd.DataFrame,
        *,
        date_candidates: Sequence[str],
        value_candidates: Sequence[str],
        value_name: str,
    ) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", value_name])

        date_col = IndexValuationSource._pick_col(df.columns, date_candidates)
        value_col = IndexValuationSource._pick_col(df.columns, value_candidates)
        if not date_col or not value_col:
            return pd.DataFrame(columns=["date", value_name])

        frame = pd.DataFrame()
        frame["date"] = pd.to_datetime(df[date_col], errors="coerce")
        frame[value_name] = pd.to_numeric(df[value_col], errors="coerce")
        frame = frame.dropna(subset=["date", value_name], how="any")
        if frame.empty:
            return frame

        frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        return frame.reset_index(drop=True)


if __name__ == "__main__":
    print("Fetching 000300 (HS300)...")
    print(IndexValuationSource.fetch_index_valuation("000300"))
