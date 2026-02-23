"""
Category-aware scoring profile for funds.

Equity profile:
- valuation 30%
- momentum/performance 40%
- risk control 30%

Bond profile:
- risk/sharpe 50%
- performance 30%
- manager/size 20%
"""

from __future__ import annotations

from typing import Dict, Optional


def _to_float(value: Optional[float]) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _weighted_average(parts: Dict[str, tuple]) -> float:
    """
    parts: {"name": (score or None, weight)}
    """
    score_sum = 0.0
    weight_sum = 0.0
    for score, weight in parts.values():
        if score is None:
            continue
        score_sum += float(score) * float(weight)
        weight_sum += float(weight)
    if weight_sum <= 0:
        return 50.0
    return round(_clamp(score_sum / weight_sum), 2)


def resolve_asset_category(fund_type: str) -> str:
    text = str(fund_type or "").strip().lower()
    if not text:
        return "other"

    # Use unicode escapes to keep source stable across Windows code pages.
    bond_keywords = (
        "bond",
        "fixed income",
        "\u503a\u5238",      # 债券
        "\u56fa\u6536",      # 固收
        "\u7eaf\u503a",      # 纯债
        "\u4e2d\u77ed\u503a",  # 中短债
        "\u53ef\u8f6c\u503a",  # 可转债
    )
    equity_keywords = (
        "equity",
        "etf",
        "\u80a1\u7968",      # 股票
        "\u6307\u6570",      # 指数
        "\u6df7\u5408",      # 混合
        "\u504f\u80a1",      # 偏股
        "\u8054\u63a5",      # 联接
    )

    if any(keyword in text for keyword in bond_keywords):
        return "bond"
    if any(keyword in text for keyword in equity_keywords):
        return "equity"
    return "other"


def compute_profile_score(factors: Dict, asset_category: str) -> float:
    category = str(asset_category or "other").lower()
    if category == "bond":
        return _compute_bond_profile(factors)
    if category == "equity":
        return _compute_equity_profile(factors)
    # Fallback: balanced profile for unknown category.
    return _weighted_average(
        {
            "perf": (_performance_score(factors), 0.4),
            "risk": (_risk_score(factors), 0.4),
            "valuation": (_valuation_score(factors), 0.2),
        }
    )


def _performance_score(factors: Dict) -> float:
    ret_1m = _to_float(factors.get("return_1m"))
    ret_3m = _to_float(factors.get("return_3m"))
    ret_1y = _to_float(factors.get("return_1y"))

    score_1m = None if ret_1m is None else _clamp(50 + ret_1m * 5)
    score_3m = None if ret_3m is None else _clamp(50 + ret_3m * 2.5)
    score_1y = None if ret_1y is None else _clamp(50 + ret_1y * 1.2)

    return _weighted_average(
        {
            "ret_1m": (score_1m, 0.35),
            "ret_3m": (score_3m, 0.35),
            "ret_1y": (score_1y, 0.30),
        }
    )


def _risk_score(factors: Dict) -> float:
    sharpe_1y = _to_float(factors.get("sharpe_1y"))
    max_dd = _to_float(factors.get("max_drawdown_1y"))
    vol_60d = _to_float(factors.get("volatility_60d"))

    sharpe_score = None if sharpe_1y is None else _clamp((sharpe_1y + 0.5) / 2.0 * 100)
    drawdown_score = None if max_dd is None else _clamp(100 - max_dd * 2)
    vol_score = None if vol_60d is None else _clamp(100 - abs(vol_60d - 18) * 4)

    return _weighted_average(
        {
            "sharpe": (sharpe_score, 0.45),
            "drawdown": (drawdown_score, 0.40),
            "vol": (vol_score, 0.15),
        }
    )


def _valuation_score(factors: Dict) -> float:
    direct = _to_float(factors.get("valuation_score"))
    if direct is not None:
        return _clamp(direct)

    pe_pct = _to_float(factors.get("pe_percentile"))
    if pe_pct is None:
        pe_pct = _to_float(factors.get("index_pe_percentile"))
    if pe_pct is not None and pe_pct > 1:
        pe_pct = pe_pct / 100.0

    if pe_pct is None:
        return 50.0
    return _clamp((1 - pe_pct) * 100)


def _manager_size_score(factors: Dict) -> float:
    tenure = _to_float(factors.get("manager_tenure_years"))
    style = _to_float(factors.get("style_consistency"))
    size = _to_float(factors.get("fund_size"))

    tenure_score = None if tenure is None else _clamp(35 + tenure * 10)
    style_score = style if style is not None else None
    if size is None:
        size_score = None
    elif 1.0 <= size <= 50.0:
        size_score = 88.0
    elif size < 1.0:
        size_score = _clamp(45 + size * 35)
    else:
        size_score = _clamp(88 - (size - 50.0) * 1.2)

    return _weighted_average(
        {
            "tenure": (tenure_score, 0.4),
            "style": (style_score, 0.35),
            "size": (size_score, 0.25),
        }
    )


def _compute_equity_profile(factors: Dict) -> float:
    return _weighted_average(
        {
            "valuation": (_valuation_score(factors), 0.30),
            "performance": (_performance_score(factors), 0.40),
            "risk": (_risk_score(factors), 0.30),
        }
    )


def _compute_bond_profile(factors: Dict) -> float:
    return _weighted_average(
        {
            "risk": (_risk_score(factors), 0.50),
            "performance": (_performance_score(factors), 0.30),
            "manager_size": (_manager_size_score(factors), 0.20),
        }
    )