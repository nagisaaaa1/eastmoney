"""
Fund recommendation engine.

This engine now supports category-aware profile scoring:
- equity funds: valuation + momentum/performance + risk
- bond funds: risk + performance + manager/size
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from src.analysis.recommendation.factor_store.cache import factor_cache
from src.data_sources.tushare_client import format_date_yyyymmdd, get_latest_trade_date
from src.storage.db import get_db_connection

from .factors.manager import ManagerFactors
from .factors.performance import PerformanceFactors
from .factors.risk import RiskFactors
from .factors.valuation import ValuationFactors
from .strategies.alpha import AlphaStrategy, get_alpha_recommendation
from .strategies.momentum import MomentumStrategy, get_momentum_recommendation
from .strategies.scoring_profile import compute_profile_score, resolve_asset_category

logger = logging.getLogger(__name__)


def _to_float(value: Optional[float]) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class FundRecommendationEngine:
    DEFAULT_TOP_N = 20
    MIN_SCORE_SHORT = 55
    MIN_SCORE_LONG = 55

    def compute_factors(
        self,
        fund_code: str,
        trade_date: str = None,
        use_cache: bool = True,
    ) -> Dict:
        code = str(fund_code or "").split(".")[0]
        if not code:
            return {}

        if not trade_date:
            trade_date = get_latest_trade_date() or format_date_yyyymmdd()
        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

        if use_cache:
            cached = factor_cache.get_fund_factors(code, trade_date_db)
            if cached:
                return cached

        logger.info("Computing fund factors for %s (%s)", code, trade_date)
        try:
            performance = PerformanceFactors.compute(code, trade_date)
            risk = RiskFactors.compute(code, trade_date)
            manager = ManagerFactors.compute(code, trade_date)
            valuation = ValuationFactors.compute(code, trade_date)
        except Exception as exc:
            logger.error("Factor computation failed for %s: %s", code, exc)
            return {}

        factors = {
            **performance,
            **risk,
            **manager,
            **valuation,
            "update_time": time.time(),
        }

        fund_type = self._get_fund_type(code)
        asset_category = resolve_asset_category(fund_type)
        profile_score = compute_profile_score(factors, asset_category)

        short_base = MomentumStrategy.compute_score(factors)
        long_base = AlphaStrategy.compute_score(factors)

        profile_weight = 0.55 if asset_category == "bond" else 0.40
        short_score = self._blend_score(short_base, profile_score, profile_weight)
        long_score = self._blend_score(long_base, profile_score, profile_weight)

        factors["fund_type"] = fund_type
        factors["asset_category"] = asset_category
        factors["profile_score"] = profile_score
        factors["short_term_base_score"] = short_base
        factors["long_term_base_score"] = long_base
        factors["short_term_score"] = short_score
        factors["long_term_score"] = long_score

        if use_cache and factors:
            factor_cache.set_fund_factors(code, trade_date_db, factors)
        return factors

    def get_recommendations(
        self,
        strategy: str = "short_term",
        top_n: int = None,
        trade_date: str = None,
        min_score: float = None,
        use_cache: bool = True,
    ) -> List[Dict]:
        if top_n is None:
            top_n = self.DEFAULT_TOP_N
        if min_score is None:
            min_score = self.MIN_SCORE_SHORT if strategy == "short_term" else self.MIN_SCORE_LONG

        if not trade_date:
            trade_date = get_latest_trade_date() or format_date_yyyymmdd()
        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

        candidates = factor_cache.get_top_funds(
            trade_date_db,
            score_type=strategy,
            limit=top_n * 3,
            min_score=min_score,
        )

        recommendations: List[Dict] = []
        for factor_row in candidates:
            code = factor_row.get("code")
            if not code:
                continue

            factor_row = self._ensure_profile_fields(code, factor_row, trade_date)

            if strategy == "short_term":
                rec = get_momentum_recommendation(factor_row, include_reasoning=True)
            else:
                rec = get_alpha_recommendation(factor_row, include_reasoning=True)

            fund_info = self._get_fund_info(code)
            rec.update(
                {
                    "code": code,
                    "name": fund_info.get("name", ""),
                    "type": fund_info.get("type", ""),
                    "trade_date": trade_date_db,
                    "factors": {
                        "score": factor_row.get(f"{strategy}_score"),
                        "asset_category": factor_row.get("asset_category"),
                        "profile_score": factor_row.get("profile_score"),
                        "valuation_score": factor_row.get("valuation_score"),
                        "pe_percentile": factor_row.get("pe_percentile"),
                        "tracking_index": factor_row.get("tracking_index"),
                        "sharpe_1y": factor_row.get("sharpe_1y"),
                        "max_drawdown_1y": factor_row.get("max_drawdown_1y"),
                        "return_1y": factor_row.get("return_1y"),
                    },
                }
            )
            recommendations.append(rec)
            if len(recommendations) >= top_n:
                break

        return recommendations

    def get_single_recommendation(
        self,
        fund_code: str,
        strategy: str = "short_term",
        trade_date: str = None,
    ) -> Dict:
        code = str(fund_code or "").split(".")[0]
        if not code:
            return {"code": "", "name": "", "type": "", "score": 0, "all_factors": {}}

        if not trade_date:
            trade_date = get_latest_trade_date() or format_date_yyyymmdd()

        factors = self.compute_factors(code, trade_date=trade_date, use_cache=True)
        if not factors:
            return {
                "code": code,
                "name": code,
                "type": "",
                "trade_date": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}",
                "score": 0,
                "reason": "因子计算失败",
                "all_factors": {},
            }

        if strategy == "short_term":
            rec = get_momentum_recommendation(factors, include_reasoning=True)
        else:
            rec = get_alpha_recommendation(factors, include_reasoning=True)

        fund_info = self._get_fund_info(code)
        rec.update(
            {
                "code": code,
                "name": fund_info.get("name", ""),
                "type": fund_info.get("type", ""),
                "trade_date": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}",
                "all_factors": factors,
            }
        )
        return rec

    def compare_funds(
        self,
        codes: List[str],
        strategy: str = "short_term",
        trade_date: str = None,
    ) -> List[Dict]:
        rows = [self.get_single_recommendation(code, strategy, trade_date) for code in codes]
        rows.sort(key=lambda item: item.get("score", 0), reverse=True)
        return rows

    @staticmethod
    def _blend_score(base_score: float, profile_score: float, profile_weight: float) -> float:
        base = _to_float(base_score)
        profile = _to_float(profile_score)
        if base is None and profile is None:
            return 50.0
        if base is None:
            return round(_clamp(profile or 50.0), 2)
        if profile is None:
            return round(_clamp(base), 2)
        w = _clamp(profile_weight, 0.0, 1.0)
        return round(_clamp(base * (1.0 - w) + profile * w), 2)

    def _ensure_profile_fields(self, code: str, factors: Dict, trade_date: str) -> Dict:
        """
        Enrich DB-loaded factors with profile fields when missing.
        """
        row = dict(factors or {})
        row.setdefault("code", code)
        fund_type = row.get("fund_type") or self._get_fund_type(code)
        row["fund_type"] = fund_type

        category = row.get("asset_category") or resolve_asset_category(fund_type)
        row["asset_category"] = category
        if row.get("profile_score") is None:
            row["profile_score"] = compute_profile_score(row, category)

        # If valuation fields are missing due to historical DB rows, compute quickly.
        if row.get("valuation_score") is None or row.get("tracking_index") is None:
            valuation = ValuationFactors.compute(code, trade_date)
            for key, value in valuation.items():
                if row.get(key) is None:
                    row[key] = value

        return row

    def _get_fund_type(self, code: str) -> str:
        info = self._get_fund_info(code)
        return str(info.get("type") or "")

    def _get_fund_info(self, code: str) -> Dict:
        try:
            conn = get_db_connection()
            try:
                cur = conn.execute("SELECT name, style FROM funds WHERE code=?", (code,))
                row = cur.fetchone()
                if row:
                    return {"name": row[0] or code, "type": row[1] or ""}

                cur = conn.execute("SELECT name, fund_type FROM fund_basic WHERE code=?", (code,))
                row = cur.fetchone()
                if row:
                    return {"name": row[0] or code, "type": row[1] or ""}
                return {"name": code, "type": ""}
            finally:
                conn.close()
        except Exception:
            return {"name": code, "type": ""}


def get_momentum_picks(top_n: int = 20, trade_date: str = None) -> List[Dict]:
    engine = FundRecommendationEngine()
    return engine.get_recommendations(strategy="short_term", top_n=top_n, trade_date=trade_date)


def get_alpha_picks(top_n: int = 20, trade_date: str = None) -> List[Dict]:
    engine = FundRecommendationEngine()
    return engine.get_recommendations(strategy="long_term", top_n=top_n, trade_date=trade_date)


def analyze_fund(code: str, trade_date: str = None) -> Dict:
    engine = FundRecommendationEngine()
    short_term = engine.get_single_recommendation(code, "short_term", trade_date)
    long_term = engine.get_single_recommendation(code, "long_term", trade_date)
    return {
        "code": code,
        "name": short_term.get("name", ""),
        "type": short_term.get("type", ""),
        "trade_date": short_term.get("trade_date", ""),
        "short_term": short_term,
        "long_term": long_term,
        "factors": short_term.get("all_factors", {}),
    }
