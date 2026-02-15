from typing import Dict, List
import time
import logging

from src.data_sources.tushare_client import (
    get_latest_trade_date,
    format_date_yyyymmdd,
)
from src.storage.db import get_db_connection
from src.analysis.recommendation.factor_store.cache import factor_cache

# 因子计算器
from .factors.performance import PerformanceFactors
from .factors.risk import RiskFactors
from .factors.manager import ManagerFactors
from .factors.valuation import ValuationFactors

# 策略打分器
from .strategies.momentum import MomentumStrategy, get_momentum_recommendation
from .strategies.alpha import AlphaStrategy, get_alpha_recommendation

logger = logging.getLogger(__name__)


class FundRecommendationEngine:
    """
    基金推荐引擎核心类
    """

    DEFAULT_TOP_N = 20
    MIN_SCORE_SHORT = 55
    MIN_SCORE_LONG = 55

    def __init__(self):
        pass

    def compute_factors(
        self,
        fund_code: str,
        trade_date: str = None,
        use_cache: bool = True,
    ) -> Dict:
        """
        计算单只基金所有因子
        """
        code = fund_code.split(".")[0]

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

        if use_cache:
            cached = factor_cache.get_fund_factors(code, trade_date_db)
            if cached:
                return cached

        logger.info("Computing factors for %s on %s...", code, trade_date)

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

        factors["short_term_score"] = MomentumStrategy.compute_score(factors)
        factors["long_term_score"] = AlphaStrategy.compute_score(factors)

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
        """
        获取推荐列表
        """
        if top_n is None:
            top_n = self.DEFAULT_TOP_N
        if min_score is None:
            min_score = self.MIN_SCORE_SHORT if strategy == "short_term" else self.MIN_SCORE_LONG

        if not trade_date:
            trade_date = get_latest_trade_date() or format_date_yyyymmdd()

        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

        cached_factors_list = factor_cache.get_top_funds(
            trade_date_db,
            score_type=strategy,
            limit=top_n * 3,
            min_score=min_score,
        )

        recommendations = []
        for factors in cached_factors_list:
            code = factors.get("code")
            if not code:
                continue

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
                    "trade_date": trade_date_db,
                    "factors": {
                        "score": factors.get(f"{strategy}_score"),
                        "valuation_score": factors.get("valuation_score"),
                        "pe_percentile": factors.get("pe_percentile"),
                        "tracking_index": factors.get("tracking_index"),
                        "sharpe_1y": factors.get("sharpe_1y"),
                        "max_drawdown_1y": factors.get("max_drawdown_1y"),
                        "return_1y": factors.get("return_1y"),
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
        """
        获取单只基金推荐（兼容旧调用路径）
        """
        code = fund_code.split(".")[0]
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

    def _get_fund_info(self, code: str) -> Dict:
        """
        获取基金名称等基础信息
        """
        try:
            conn = get_db_connection()
            try:
                cur = conn.execute("SELECT name, style FROM funds WHERE code=?", (code,))
                row = cur.fetchone()
                if row:
                    return {"name": row[0], "type": row[1]}

                cur = conn.execute("SELECT name, fund_type FROM fund_basic WHERE code=?", (code,))
                row = cur.fetchone()
                return {"name": row[0] if row else code, "type": row[1] if row else ""}
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

