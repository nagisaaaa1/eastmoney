"""
LLM synthesis explainer.

Quick mode uses deterministic templates (no LLM call).
Deep mode uses batched LLM prompts for richer reasoning.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List

from src.llm.client import get_llm_client


class RecommendationExplainer:
    """
    Generate human-readable explanations for quantitative recommendations.
    """

    BATCH_SIZE = 10
    MAX_CALLS_PER_CYCLE = 2

    @classmethod
    def generate_template_comment(
        cls,
        factors: Dict,
        strategy: str = "short_term",
        asset_type: str = "fund",
    ) -> str:
        """
        Quick template comment without any LLM call.
        """
        pe_pct = cls._to_float(
            factors.get("pe_percentile")
            if factors.get("pe_percentile") is not None
            else factors.get("index_pe_percentile")
        )
        if pe_pct is not None and pe_pct > 1:
            pe_pct = pe_pct / 100.0

        if pe_pct is None:
            valuation_tag = "估值信息不足"
            pe_text = "NA"
        elif pe_pct <= 0.30:
            valuation_tag = "低估值区间"
            pe_text = f"{pe_pct * 100:.1f}%"
        elif pe_pct >= 0.70:
            valuation_tag = "偏高估值区间"
            pe_text = f"{pe_pct * 100:.1f}%"
        else:
            valuation_tag = "中性估值区间"
            pe_text = f"{pe_pct * 100:.1f}%"

        ret_1y = cls._to_float(factors.get("return_1y"))
        ret_text = "NA" if ret_1y is None else f"{ret_1y:.2f}%"

        max_dd = cls._to_float(factors.get("max_drawdown_1y"))
        if max_dd is None:
            risk_tag = "一般"
        elif max_dd <= 15:
            risk_tag = "优秀"
        elif max_dd <= 30:
            risk_tag = "一般"
        else:
            risk_tag = "偏弱"

        horizon = "短线" if str(strategy).lower() in {"short_term", "momentum"} else "中长期"
        if str(asset_type).lower() == "stock":
            prefix = "股票"
        else:
            prefix = "基金"

        return (
            f"{prefix}{horizon}观察：当前处于{valuation_tag}（PE分位 {pe_text}），"
            f"近一年收益 {ret_text}，风险控制{risk_tag}。"
        )

    @classmethod
    def explain_stock_recommendations(
        cls,
        recommendations: List[Dict],
        strategy: str = "short_term",
        mode: str = "quick",
    ) -> List[Dict]:
        if not recommendations:
            return recommendations

        normalized_mode = str(mode or "quick").strip().lower()
        if normalized_mode != "deep":
            for rec in recommendations:
                rec["explanation"] = cls.generate_template_comment(
                    rec.get("factors", {}),
                    strategy=strategy,
                    asset_type="stock",
                )
            return recommendations

        batches = [
            recommendations[i : i + cls.BATCH_SIZE]
            for i in range(0, len(recommendations), cls.BATCH_SIZE)
        ][: cls.MAX_CALLS_PER_CYCLE]

        explained_recs: List[Dict] = []
        for batch in batches:
            explanations = cls._generate_stock_explanations(batch, strategy)
            for rec, explanation in zip(batch, explanations):
                rec["explanation"] = explanation
                explained_recs.append(rec)

        remaining_start = cls.MAX_CALLS_PER_CYCLE * cls.BATCH_SIZE
        for rec in recommendations[remaining_start:]:
            rec["explanation"] = cls.generate_template_comment(
                rec.get("factors", {}),
                strategy=strategy,
                asset_type="stock",
            )
            explained_recs.append(rec)

        return explained_recs

    @classmethod
    def explain_fund_recommendations(
        cls,
        recommendations: List[Dict],
        strategy: str = "short_term",
        mode: str = "quick",
    ) -> List[Dict]:
        if not recommendations:
            return recommendations

        normalized_mode = str(mode or "quick").strip().lower()
        if normalized_mode != "deep":
            for rec in recommendations:
                rec["explanation"] = cls.generate_template_comment(
                    rec.get("factors", {}),
                    strategy=strategy,
                    asset_type="fund",
                )
            return recommendations

        batches = [
            recommendations[i : i + cls.BATCH_SIZE]
            for i in range(0, len(recommendations), cls.BATCH_SIZE)
        ][: cls.MAX_CALLS_PER_CYCLE]

        explained_recs: List[Dict] = []
        for batch in batches:
            explanations = cls._generate_fund_explanations(batch, strategy)
            for rec, explanation in zip(batch, explanations):
                rec["explanation"] = explanation
                explained_recs.append(rec)

        remaining_start = cls.MAX_CALLS_PER_CYCLE * cls.BATCH_SIZE
        for rec in recommendations[remaining_start:]:
            rec["explanation"] = cls.generate_template_comment(
                rec.get("factors", {}),
                strategy=strategy,
                asset_type="fund",
            )
            explained_recs.append(rec)

        return explained_recs

    @classmethod
    def _generate_stock_explanations(
        cls,
        recommendations: List[Dict],
        strategy: str,
    ) -> List[str]:
        prompt = (
            cls._build_short_term_stock_prompt(recommendations)
            if strategy == "short_term"
            else cls._build_long_term_stock_prompt(recommendations)
        )
        try:
            client = get_llm_client()
            response = client.generate_content(prompt)
            return cls._parse_explanations(response, len(recommendations))
        except Exception:
            return [
                cls.generate_template_comment(
                    rec.get("factors", {}),
                    strategy=strategy,
                    asset_type="stock",
                )
                for rec in recommendations
            ]

    @classmethod
    def _generate_fund_explanations(
        cls,
        recommendations: List[Dict],
        strategy: str,
    ) -> List[str]:
        prompt = (
            cls._build_short_term_fund_prompt(recommendations)
            if strategy == "short_term"
            else cls._build_long_term_fund_prompt(recommendations)
        )
        try:
            client = get_llm_client()
            response = client.generate_content(prompt)
            return cls._parse_explanations(response, len(recommendations))
        except Exception:
            return [
                cls.generate_template_comment(
                    rec.get("factors", {}),
                    strategy=strategy,
                    asset_type="fund",
                )
                for rec in recommendations
            ]

    @classmethod
    def _build_short_term_stock_prompt(cls, recommendations: List[Dict]) -> str:
        payload = []
        for rec in recommendations:
            factors = rec.get("factors", {})
            payload.append(
                {
                    "code": rec.get("code"),
                    "name": rec.get("name"),
                    "score": rec.get("score"),
                    "return_1m": factors.get("return_1m"),
                    "consolidation_score": factors.get("consolidation_score"),
                    "volume_precursor": factors.get("volume_precursor"),
                    "main_inflow_5d": factors.get("main_inflow_5d"),
                }
            )
        return (
            "你是投研分析师。请基于以下短线股票因子，逐条输出30-80字中文解释，"
            "包含逻辑、催化、风险。仅返回JSON数组字符串。\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    @classmethod
    def _build_long_term_stock_prompt(cls, recommendations: List[Dict]) -> str:
        payload = []
        for rec in recommendations:
            factors = rec.get("factors", {})
            payload.append(
                {
                    "code": rec.get("code"),
                    "name": rec.get("name"),
                    "score": rec.get("score"),
                    "roe": factors.get("roe"),
                    "peg_ratio": factors.get("peg_ratio"),
                    "pe_percentile": factors.get("pe_percentile"),
                }
            )
        return (
            "你是投研分析师。请基于以下中长期股票因子，逐条输出30-80字中文解释，"
            "包含质量、估值、风险。仅返回JSON数组字符串。\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    @classmethod
    def _build_short_term_fund_prompt(cls, recommendations: List[Dict]) -> str:
        payload = []
        for rec in recommendations:
            factors = rec.get("factors", {})
            payload.append(
                {
                    "code": rec.get("code"),
                    "name": rec.get("name"),
                    "score": rec.get("score"),
                    "return_1m": factors.get("return_1m"),
                    "sharpe_1y": factors.get("sharpe_1y"),
                    "valuation_score": factors.get("valuation_score"),
                }
            )
        return (
            "你是基金分析师。请基于以下短线基金因子，逐条输出30-80字中文解释，"
            "包含动量、估值、风险。仅返回JSON数组字符串。\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    @classmethod
    def _build_long_term_fund_prompt(cls, recommendations: List[Dict]) -> str:
        payload = []
        for rec in recommendations:
            factors = rec.get("factors", {})
            payload.append(
                {
                    "code": rec.get("code"),
                    "name": rec.get("name"),
                    "score": rec.get("score"),
                    "sharpe_1y": factors.get("sharpe_1y"),
                    "max_drawdown_1y": factors.get("max_drawdown_1y"),
                    "manager_tenure_years": factors.get("manager_tenure_years"),
                    "valuation_score": factors.get("valuation_score"),
                }
            )
        return (
            "你是基金分析师。请基于以下中长期基金因子，逐条输出30-80字中文解释，"
            "包含收益质量、回撤控制、风险。仅返回JSON数组字符串。\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    @classmethod
    def _parse_explanations(cls, response: str, expected_count: int) -> List[str]:
        if not response:
            return ["暂无详细分析"] * expected_count

        try:
            start_idx = response.find("[")
            end_idx = response.rfind("]") + 1
            if start_idx >= 0 and end_idx > start_idx:
                data = json.loads(response[start_idx:end_idx])
                if isinstance(data, list):
                    text_items = [str(item) for item in data]
                    while len(text_items) < expected_count:
                        text_items.append("暂无详细分析")
                    return text_items[:expected_count]
        except Exception:
            pass
        return ["暂无详细分析"] * expected_count

    @staticmethod
    def _to_float(value):
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None


def explain_recommendations_sync(
    recommendations: List[Dict],
    asset_type: str = "stock",
    strategy: str = "short_term",
    mode: str = "quick",
) -> List[Dict]:
    """
    Sync wrapper for recommendation explanation generation.
    """
    if not recommendations:
        return recommendations

    start_time = time.time()
    print(
        f"[LLM Explainer] mode={mode}, asset={asset_type}, strategy={strategy}, count={len(recommendations)}"
    )
    try:
        if asset_type == "stock":
            result = RecommendationExplainer.explain_stock_recommendations(
                recommendations,
                strategy,
                mode=mode,
            )
        else:
            result = RecommendationExplainer.explain_fund_recommendations(
                recommendations,
                strategy,
                mode=mode,
            )
        print(f"[LLM Explainer] completed in {time.time() - start_time:.2f}s")
        return result
    except Exception as exc:
        print(f"[LLM Explainer] failed: {exc}")
        for rec in recommendations:
            rec["explanation"] = RecommendationExplainer.generate_template_comment(
                rec.get("factors", {}),
                strategy=strategy,
                asset_type=asset_type,
            )
        return recommendations

