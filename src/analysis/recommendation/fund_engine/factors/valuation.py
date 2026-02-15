import logging
from typing import Dict

from src.analysis.utils.fund_mapping import FundIndexMapper
from src.data_sources.index_valuation import IndexValuationSource
from src.storage.db import get_db_connection

logger = logging.getLogger(__name__)


class ValuationFactors:
    """
    计算基金估值因子（基于跟踪指数的历史估值分位）
    """

    @classmethod
    def compute(cls, fund_code: str, trade_date: str = None) -> Dict:
        del trade_date  # 预留字段，当前实现不依赖交易日切片
        factors = {
            "valuation_score": 50.0,  # 默认中性
            "pe_percentile": None,
            "pb_percentile": None,
            "tracking_index": None,
            "index_name": None,
        }

        try:
            fund_name = cls._get_fund_name(fund_code)
            if not fund_name:
                return factors

            index_code = FundIndexMapper.guess_index_code(fund_name)
            if not index_code:
                return factors

            factors["tracking_index"] = index_code

            val_data = IndexValuationSource.fetch_index_valuation(index_code)
            if not val_data:
                return factors

            pe_pct = val_data.get("pe_percentile")
            pb_pct = val_data.get("pb_percentile")

            factors["pe_percentile"] = pe_pct
            factors["pb_percentile"] = pb_pct
            factors["index_name"] = index_code

            if pe_pct is not None:
                score = (1 - pe_pct) * 100
                factors["valuation_score"] = round(max(0, min(100, score)), 2)
                logger.info(
                    "Fund %s (%s) tracks %s: PE rank %.2f -> Score %.2f",
                    fund_code,
                    fund_name,
                    index_code,
                    pe_pct,
                    factors["valuation_score"],
                )

        except Exception as exc:
            logger.error("Valuation compute error for %s: %s", fund_code, exc)

        return factors

    @classmethod
    def _get_fund_name(cls, code: str) -> str:
        try:
            clean_code = str(code or "").split(".")[0]
            if not clean_code:
                return ""

            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM fund_basic WHERE code=?", (clean_code,))
                res = cursor.fetchone()
                return res[0] if res else ""
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Error fetching fund name for %s: %s", code, exc)
            return ""

