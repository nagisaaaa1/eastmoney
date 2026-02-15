"""
Fund research service for candidate-pool governance, scoring and DCA decisions.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.analysis.recommendation.fund_engine.engine import FundRecommendationEngine
from src.data_sources.fund_data_provider import get_fallback_trade_date, normalize_fund_code
from src.data_sources.tushare_client import (
    get_latest_trade_date,
    sync_fund_basic,
    tushare_call_with_retry,
)
from src.llm.client import get_llm_client
from src.storage.db import (
    get_db_connection,
    get_default_portfolio,
    get_fund_basic_count,
    get_portfolio_positions,
    get_user_preferences,
    upsert_fund_factors,
)
from src.storage.fund_research_db import (
    cancel_batch_job_items,
    compute_batch_job_counters,
    create_batch_job,
    get_batch_job,
    get_case_library_entries,
    get_latest_context_snapshot,
    get_latest_dca_metric_daily,
    get_fund_universe,
    get_fund_universe_count,
    get_fund_review_records,
    get_latest_recommendation_decision,
    get_recommendation_decision_by_id,
    list_batch_jobs,
    get_missing_universe_codes,
    get_universe_last_updated,
    reset_failed_batch_items,
    save_context_snapshot,
    save_case_library_entry,
    save_fund_review_record,
    save_fund_scorecard,
    save_fund_snapshot,
    save_recommendation_decision,
    update_batch_job_item,
    update_batch_job_status,
    create_dca_plan,
    create_dca_plan_run,
    get_dca_plan,
    get_planned_dca_amount,
    list_dca_plan_runs,
    list_dca_plans,
    mark_fund_universe_all_inactive,
    update_dca_plan,
    set_fund_universe_status,
    upsert_dca_metric_daily,
    upsert_fund_universe_items,
)


INDEX_HINTS = (
    "指数",
    "etf",
    "联接",
    "被动",
    "enhanced index",
    "index",
    "沪深",
    "中证",
    "恒生",
    "nasdaq",
    "标普",
    "msci",
)


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _clamp(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def _parse_date(date_text: Optional[str]) -> Optional[datetime]:
    if not date_text:
        return None
    raw = str(date_text).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _contains_index_hint(*parts: Optional[str]) -> bool:
    text = " ".join((str(part or "") for part in parts)).lower()
    return any(hint in text for hint in INDEX_HINTS)


def _chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _snapshot_hash(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FundResearchService:
    """Service layer for fund candidate pool and recommendation decisions."""

    MIN_FOUND_DAYS = 180
    MIN_FUND_SIZE_BN = 0.5
    MAX_DRAWDOWN_ALLOWED = 45.0

    def __init__(self) -> None:
        self._factor_engine = FundRecommendationEngine()
        self._trading_day_cache: Dict[int, set] = {}

    @staticmethod
    def _confidence_band(confidence: float) -> str:
        if confidence >= 0.75:
            return "high"
        if confidence >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _date_to_key(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    def _load_trading_days_for_year(self, year: int) -> set:
        year_int = int(year)
        if year_int in self._trading_day_cache:
            return self._trading_day_cache[year_int]

        days: set = set()
        start = f"{year_int}0101"
        end = f"{year_int}1231"

        try:
            df = tushare_call_with_retry(
                "trade_cal",
                exchange="SSE",
                start_date=start,
                end_date=end,
            )
            if df is not None and not df.empty and "is_open" in df.columns and "cal_date" in df.columns:
                open_days = df[df["is_open"] == 1]
                for value in open_days["cal_date"].tolist():
                    raw = str(value)
                    if len(raw) == 8 and raw.isdigit():
                        days.add(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
        except Exception:
            pass

        if not days:
            try:
                import akshare as ak  # local import to avoid hard dependency on startup

                df = ak.tool_trade_date_hist_sina()
                if df is not None and not df.empty and "trade_date" in df.columns:
                    for value in df["trade_date"].tolist():
                        raw = str(value)[:10]
                        if raw.startswith(f"{year_int}-"):
                            days.add(raw)
            except Exception:
                pass

        if not days:
            # Last-resort fallback when APIs fail: weekday calendar.
            base = datetime(year_int, 1, 1)
            while base.year == year_int:
                if base.weekday() < 5:
                    days.add(self._date_to_key(base))
                base += timedelta(days=1)

        self._trading_day_cache[year_int] = days
        return days

    def _is_cn_trading_day(self, dt: datetime) -> bool:
        return self._date_to_key(dt) in self._load_trading_days_for_year(dt.year)

    def _next_cn_trading_day(self, dt: datetime) -> datetime:
        cursor = dt
        guard = 0
        while not self._is_cn_trading_day(cursor):
            cursor += timedelta(days=1)
            guard += 1
            if guard > 30:
                break
        return cursor

    def _build_debate_points(self, scorecard: Dict[str, Any]) -> Dict[str, List[str]]:
        factors = scorecard.get("factors", {}) or {}
        total_score = _safe_float(scorecard.get("total_score"), 0.0) or 0.0

        bull_points: List[str] = []
        bear_points: List[str] = []

        sharpe_1y = _safe_float(factors.get("sharpe_1y"))
        if sharpe_1y is not None:
            if sharpe_1y >= 0.8:
                bull_points.append(f"风险收益比表现较好（近1年夏普 {sharpe_1y:.2f}）。")
            elif sharpe_1y <= 0.2:
                bear_points.append(f"风险收益比偏弱（近1年夏普 {sharpe_1y:.2f}）。")

        max_dd = _safe_float(factors.get("max_drawdown_1y"))
        if max_dd is not None:
            if max_dd <= 20:
                bull_points.append(f"回撤控制相对可接受（近1年最大回撤 {max_dd:.1f}%）。")
            elif max_dd >= 35:
                bear_points.append(f"回撤压力偏高（近1年最大回撤 {max_dd:.1f}%）。")

        ret_3m = _safe_float(factors.get("return_3m"))
        if ret_3m is not None:
            if ret_3m <= -8:
                bull_points.append(f"回调后估值位置改善（近3月收益 {ret_3m:.1f}%）。")
            elif ret_3m >= 12:
                bear_points.append(f"中期涨幅偏大，需防止追高（近3月收益 {ret_3m:.1f}%）。")

        manager_tenure = _safe_float(factors.get("manager_tenure_years"))
        if manager_tenure is not None:
            if manager_tenure >= 3:
                bull_points.append(f"基金经理任期较稳定（{manager_tenure:.1f} 年）。")
            elif manager_tenure < 1:
                bear_points.append(f"基金经理任期较短（{manager_tenure:.1f} 年）。")

        if total_score >= 70:
            bull_points.append(f"综合评分较强（{total_score:.1f}）。")
        elif total_score < 50:
            bear_points.append(f"综合评分低于偏好阈值（{total_score:.1f}）。")

        disagreements: List[str] = []
        if bull_points and bear_points:
            disagreements.append(
                "信号出现分歧：估值与回调信号有支撑，但风险/动量仍有争议。"
            )
        if not bull_points:
            bull_points.append("当前因子未出现明确的上行动能。")
        if not bear_points:
            bear_points.append("当前因子未出现主导性的下行风险。")

        return {
            "bull_points": bull_points[:4],
            "bear_points": bear_points[:4],
            "disagreement_points": disagreements[:2],
        }

    def sync_universe(
        self,
        user_id: int,
        *,
        full_sync: bool = False,
        codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Synchronize candidate pool from `fund_basic` and tracked user funds.

        Rules:
        - Only index-like funds are marked eligible for scoring/research.
        - Any explicit `codes` are incrementally patched into the universe.
        """
        normalized_codes = sorted(
            {normalize_fund_code(code) for code in (codes or []) if normalize_fund_code(code)}
        )

        existing_count = get_fund_universe_count(user_id, active_only=True)
        should_full_sync = full_sync or existing_count == 0

        if should_full_sync and get_fund_basic_count() == 0:
            try:
                sync_fund_basic()
            except Exception as exc:
                # Non-fatal: universe can still be bootstrapped from tracked funds.
                print(f"fund_basic sync skipped: {exc}")

        basic_rows = self._load_fund_basic_rows(
            codes=normalized_codes if (normalized_codes and not should_full_sync) else None
        )
        if should_full_sync and not basic_rows:
            basic_rows = self._load_fund_basic_rows(codes=None)

        items = [self._build_universe_item(row, source="fund_basic") for row in basic_rows]

        tracked_rows = self._load_tracked_funds(user_id)
        tracked_items = []
        known_codes = {item["code"] for item in items}
        for row in tracked_rows:
            code = normalize_fund_code(row.get("code"))
            if not code or code in known_codes:
                continue
            tracked_items.append(self._build_universe_item(row, source="tracked_funds"))
            known_codes.add(code)

        merged_items = items + tracked_items
        filtered_items = [
            item for item in merged_items if self._is_universe_candidate_item(item)
        ]
        excluded_by_policy = sorted(
            {
                item["code"]
                for item in merged_items
                if item.get("code") and not self._is_universe_candidate_item(item)
            }
        )

        if should_full_sync:
            # Full sync follows strict policy: only keep current valid candidates as active.
            mark_fund_universe_all_inactive(user_id)

        updated_count = upsert_fund_universe_items(user_id, filtered_items)

        unresolved = get_missing_universe_codes(user_id, normalized_codes) if normalized_codes else []
        if unresolved:
            # Explicitly requested but still unresolved codes should never stay active.
            set_fund_universe_status(user_id, unresolved, status="inactive")

        requested_excluded = [code for code in normalized_codes if code in excluded_by_policy]
        if requested_excluded:
            set_fund_universe_status(user_id, requested_excluded, status="inactive")

        return {
            "status": "ok",
            "full_sync": should_full_sync,
            "input_codes": normalized_codes,
            "fund_basic_items": len(items),
            "tracked_items": len(tracked_items),
            "filtered_by_policy": len(excluded_by_policy),
            "excluded_codes": excluded_by_policy[:100],
            "unresolved_codes": unresolved,
            "updated": updated_count,
            "universe_count": get_fund_universe_count(user_id, active_only=True),
            "last_updated": get_universe_last_updated(user_id),
        }

    def score_funds(
        self,
        user_id: int,
        *,
        codes: Optional[List[str]] = None,
        top_n: int = 20,
        min_score: float = 0.0,
        refresh_missing: bool = False,
    ) -> Dict[str, Any]:
        """Score funds in candidate pool and return ranked results."""
        normalized_codes = sorted(
            {normalize_fund_code(code) for code in (codes or []) if normalize_fund_code(code)}
        )

        if get_fund_universe_count(user_id, active_only=True) == 0:
            self.sync_universe(user_id, full_sync=True)
        elif normalized_codes:
            missing = get_missing_universe_codes(user_id, normalized_codes)
            if missing:
                self.sync_universe(user_id, full_sync=False, codes=missing)

        universe_items = get_fund_universe(
            user_id=user_id,
            active_only=True,
            codes=normalized_codes if normalized_codes else None,
            limit=None,
        )

        if not universe_items:
            return {
                "trade_date": self._current_trade_date(),
                "universe_size": 0,
                "eligible_count": 0,
                "scores": [],
                "rejected": [],
                "missing_factor_count": 0,
            }

        code_list = [item["code"] for item in universe_items]
        factor_rows = self._fetch_latest_factor_rows(code_list)
        missing_factor_codes = [code for code in code_list if code not in factor_rows]

        if refresh_missing and missing_factor_codes:
            self._backfill_missing_factors(missing_factor_codes)
            factor_rows = self._fetch_latest_factor_rows(code_list)
            missing_factor_codes = [code for code in code_list if code not in factor_rows]

        all_scores: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for item in universe_items:
            code = item["code"]
            factors = factor_rows.get(code) or {}
            scorecard = self._build_scorecard(item, factors)
            scorecard["code"] = code
            scorecard["name"] = item.get("name") or code
            scorecard["fund_type"] = item.get("fund_type")
            scorecard["trade_date"] = factors.get("trade_date") or self._current_trade_date(db_format=True)
            scorecard["missing_factors"] = code in missing_factor_codes
            all_scores.append(scorecard)
            if not scorecard["hard_filter_pass"]:
                rejected.append(
                    {
                        "code": code,
                        "name": scorecard["name"],
                        "reasons": scorecard["hard_filter_reasons"],
                    }
                )

        ranked = sorted(
            [
                item
                for item in all_scores
                if item["hard_filter_pass"] and item["total_score"] >= float(min_score)
            ],
            key=lambda row: row["total_score"],
            reverse=True,
        )

        top_scores = ranked[: max(1, int(top_n))]
        for row in top_scores:
            self._persist_score_snapshot(user_id, row["code"], row, factor_rows.get(row["code"]) or {})

        return {
            "trade_date": self._current_trade_date(db_format=True),
            "universe_size": len(universe_items),
            "eligible_count": len(ranked),
            "scores": top_scores,
            "rejected": rejected[:100],
            "missing_factor_count": len(missing_factor_codes),
            "policy": {
                "candidate_pool_required": True,
                "scope": "index_off_market_open_end",
            },
        }

    def _build_global_context(self, user_id: int) -> Dict[str, Any]:
        """Build shared decision context from preferences + portfolio status."""
        preference_row = get_user_preferences(user_id) or {}
        preferences = preference_row.get("preferences") or {}
        total_capital = _safe_float(preferences.get("total_capital"))
        manual_available_cash = _safe_float(preferences.get("available_cash"))

        portfolio = get_default_portfolio(user_id)
        market_value = 0.0
        total_cost = 0.0
        holding_count = 0
        if portfolio:
            positions = get_portfolio_positions(portfolio["id"], user_id=user_id)
            holding_count = len(positions)
            for row in positions:
                current_value = _safe_float(row.get("current_value"))
                total_cost += _safe_float(row.get("total_cost"), 0.0) or 0.0
                market_value += current_value if current_value is not None else (_safe_float(row.get("total_cost"), 0.0) or 0.0)

        if manual_available_cash is not None:
            available_cash = max(0.0, round(manual_available_cash, 2))
            cash_source = "manual_preference"
        elif total_capital is not None:
            available_cash = max(0.0, round(total_capital - market_value, 2))
            cash_source = "derived_total_capital"
        else:
            available_cash = None
            cash_source = "unknown"

        today = datetime.now().strftime("%Y-%m-%d")
        active_plans = list_dca_plans(user_id, status="active", limit=500)
        planned_dca_today = round(get_planned_dca_amount(user_id, today), 2)

        global_context = {
            "preference_version": preference_row.get("updated_at"),
            "total_capital": total_capital,
            "portfolio_id": portfolio.get("id") if portfolio else None,
            "portfolio_name": portfolio.get("name") if portfolio else None,
            "portfolio_market_value": round(market_value, 2),
            "portfolio_total_cost": round(total_cost, 2),
            "holding_count": holding_count,
            "available_cash": available_cash,
            "cash_source": cash_source,
            "active_dca_plan_count": len(active_plans),
            "planned_dca_today": planned_dca_today,
            "planned_dca_date": today,
        }
        return global_context

    def _compute_fund_dca_metrics_30d(
        self,
        user_id: int,
        code: str,
        *,
        force_recompute: bool = False,
    ) -> Dict[str, Any]:
        """Compute rolling 30-day DCA metrics from user transactions."""
        normalized_code = normalize_fund_code(code)
        if not normalized_code:
            return {
                "fund_code": code,
                "avg_daily_amount_30d": 0.0,
                "total_amount_30d": 0.0,
                "active_days_30d": 0,
                "tx_count_30d": 0,
                "window_days": 30,
                "metric_date": datetime.now().strftime("%Y-%m-%d"),
            }

        today = datetime.now().strftime("%Y-%m-%d")
        if not force_recompute:
            cached = get_latest_dca_metric_daily(user_id, normalized_code)
            if cached and str(cached.get("metric_date")) == today:
                return {
                    "fund_code": normalized_code,
                    "avg_daily_amount_30d": round(_safe_float(cached.get("avg_daily_amount_30d"), 0.0) or 0.0, 2),
                    "total_amount_30d": round(_safe_float(cached.get("total_amount_30d"), 0.0) or 0.0, 2),
                    "active_days_30d": int(cached.get("active_days_30d") or 0),
                    "tx_count_30d": int(cached.get("tx_count_30d") or 0),
                    "window_days": 30,
                    "metric_date": cached.get("metric_date") or today,
                    "source": "cache",
                }

        start_date = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
        conn = get_db_connection()
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS tx_count,
                COUNT(DISTINCT date(transaction_date)) AS active_days,
                SUM(COALESCE(total_amount, 0) + COALESCE(fees, 0)) AS total_amount
            FROM transactions
            WHERE user_id = ?
              AND asset_type = 'fund'
              AND asset_code = ?
              AND transaction_type IN ('buy', 'transfer_in')
              AND date(transaction_date) >= date(?)
            """,
            (user_id, normalized_code, start_date),
        ).fetchone()
        conn.close()

        tx_count = int((row["tx_count"] or 0) if row else 0)
        active_days = int((row["active_days"] or 0) if row else 0)
        total_amount = round(_safe_float((row["total_amount"] if row else 0.0), 0.0) or 0.0, 2)
        avg_daily_amount = round(total_amount / 30.0, 2)

        upsert_dca_metric_daily(
            user_id,
            normalized_code,
            today,
            avg_daily_amount_30d=avg_daily_amount,
            total_amount_30d=total_amount,
            active_days_30d=active_days,
            tx_count_30d=tx_count,
        )

        return {
            "fund_code": normalized_code,
            "avg_daily_amount_30d": avg_daily_amount,
            "total_amount_30d": total_amount,
            "active_days_30d": active_days,
            "tx_count_30d": tx_count,
            "window_days": 30,
            "metric_date": today,
            "source": "computed",
        }

    def get_global_context(self, user_id: int) -> Dict[str, Any]:
        """Public API: get and persist latest global decision context."""
        context = self._build_global_context(user_id)
        context_hash = _snapshot_hash(context)
        snapshot_id = save_context_snapshot(
            user_id,
            context_hash=context_hash,
            context=context,
            source={"name": "fund_research_service", "scope": "global"},
            fund_code=None,
        )
        return {
            "context": context,
            "context_hash": context_hash,
            "context_snapshot_id": snapshot_id,
            "latest": get_latest_context_snapshot(user_id),
        }

    def get_fund_context(self, user_id: int, code: str) -> Dict[str, Any]:
        """Public API: get one fund context with global+fund-specific inputs."""
        normalized_code = normalize_fund_code(code)
        if not normalized_code:
            raise ValueError("基金代码无效")

        global_context = self._build_global_context(user_id)
        dca_metrics = self._compute_fund_dca_metrics_30d(user_id, normalized_code, force_recompute=True)
        today = datetime.now().strftime("%Y-%m-%d")
        active_plans = list_dca_plans(
            user_id,
            status="active",
            fund_code=normalized_code,
            limit=50,
        )
        planned_today = round(
            get_planned_dca_amount(user_id, today, fund_code=normalized_code),
            2,
        )
        payload = {
            "code": normalized_code,
            "global_context": global_context,
            "fund_context": {
                "existing_dca_daily_amount": dca_metrics["avg_daily_amount_30d"],
                "dca_metrics_30d": dca_metrics,
                "planned_dca_today": planned_today,
                "active_dca_plans": active_plans,
                "active_dca_plan_count": len(active_plans),
            },
        }
        context_hash = _snapshot_hash(payload)
        snapshot_id = save_context_snapshot(
            user_id,
            fund_code=normalized_code,
            context_hash=context_hash,
            context=payload,
            source={"name": "fund_research_service", "scope": "fund"},
        )
        return {
            "context": payload,
            "context_hash": context_hash,
            "context_snapshot_id": snapshot_id,
            "latest": get_latest_context_snapshot(user_id, fund_code=normalized_code),
        }

    @staticmethod
    def _safe_json_dumps(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        raw = str(text).strip()
        if not raw:
            return None
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        left = raw.find("{")
        right = raw.rfind("}")
        if left >= 0 and right > left:
            try:
                obj = json.loads(raw[left : right + 1])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                return None
        return None

    @staticmethod
    def _normalize_text_response(raw: Any, fallback: str) -> str:
        if raw is None:
            return fallback
        text = str(raw).strip()
        if not text:
            return fallback
        lowered = text.lower()
        if lowered.startswith("error:"):
            return fallback
        return text

    def _invoke_llm_text(
        self,
        llm: Any,
        prompt: str,
        *,
        fallback: str,
    ) -> str:
        if llm is None:
            return fallback
        try:
            raw = llm.generate_content(prompt)
            return self._normalize_text_response(raw, fallback)
        except Exception:
            return fallback

    def _resolve_next_cycle_date(
        self,
        base_date: datetime,
        *,
        frequency: str,
        execution_weekday: Optional[int] = None,
        execution_day: Optional[int] = None,
    ) -> datetime:
        freq = str(frequency or "daily").lower()
        dt = base_date

        if freq == "daily":
            dt = base_date + timedelta(days=1)
        elif freq == "weekly":
            target = 0 if execution_weekday is None else int(execution_weekday)
            target = max(0, min(target, 6))
            dt = base_date + timedelta(days=1)
            while dt.weekday() != target:
                dt += timedelta(days=1)
        elif freq == "monthly":
            target_day = 1 if execution_day is None else max(1, min(int(execution_day), 28))
            if base_date.month == 12:
                year = base_date.year + 1
                month = 1
            else:
                year = base_date.year
                month = base_date.month + 1
            dt = datetime(year, month, target_day)
        else:
            dt = base_date + timedelta(days=1)

        return self._next_cn_trading_day(dt)

    def create_dca_plan_config(
        self,
        user_id: int,
        *,
        code: str,
        amount_per_cycle: float,
        frequency: str = "daily",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        execution_weekday: Optional[int] = None,
        execution_day: Optional[int] = None,
        auto_adjust: bool = True,
        max_daily_amount: Optional[float] = None,
        fund_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_code = normalize_fund_code(code)
        if not normalized_code:
            raise ValueError("??????")
        amount = max(0.0, float(amount_per_cycle))
        if amount <= 0:
            raise ValueError("????????0")

        freq = str(frequency or "daily").lower()
        if freq not in {"daily", "weekly", "monthly"}:
            raise ValueError("frequency must be one of daily/weekly/monthly")

        begin_dt = _parse_date(start_date) or datetime.now()
        begin_dt = begin_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        begin_dt = self._next_cn_trading_day(begin_dt)

        metadata = {"notes": notes} if notes else {}
        payload = {
            "fund_code": normalized_code,
            "fund_name": fund_name or normalized_code,
            "amount_per_cycle": amount,
            "frequency": freq,
            "execution_weekday": execution_weekday,
            "execution_day": execution_day,
            "start_date": begin_dt.strftime("%Y-%m-%d"),
            "end_date": end_date,
            "next_run_date": begin_dt.strftime("%Y-%m-%d"),
            "status": "active",
            "auto_adjust": bool(auto_adjust),
            "max_daily_amount": max_daily_amount,
            "metadata": metadata,
        }
        plan_id = create_dca_plan(user_id, payload)
        plan = get_dca_plan(user_id, plan_id)
        return {"plan_id": plan_id, "plan": plan}

    def list_dca_plan_configs(
        self,
        user_id: int,
        *,
        status: Optional[str] = None,
        fund_code: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        plans = list_dca_plans(
            user_id,
            status=status,
            fund_code=normalize_fund_code(fund_code) if fund_code else None,
            limit=limit,
        )
        return {
            "count": len(plans),
            "plans": plans,
        }

    def update_dca_plan_config(
        self,
        user_id: int,
        plan_id: int,
        *,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan = get_dca_plan(user_id, int(plan_id))
        if not plan:
            raise ValueError("???????")

        next_updates = dict(updates or {})
        if "action" in next_updates:
            action = str(next_updates.get("action") or "").lower()
            if action == "pause":
                next_updates["status"] = "paused"
            elif action == "resume":
                next_updates["status"] = "active"
            elif action == "stop":
                next_updates["status"] = "stopped"

        if next_updates.get("status") == "active":
            base_date = _parse_date(plan.get("next_run_date")) or datetime.now()
            base_date = self._next_cn_trading_day(base_date)
            if base_date < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
                base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                base_date = self._next_cn_trading_day(base_date)
            next_updates.setdefault("next_run_date", base_date.strftime("%Y-%m-%d"))

        changed = update_dca_plan(user_id, int(plan_id), next_updates)
        updated = get_dca_plan(user_id, int(plan_id))
        return {"updated": changed, "plan": updated}

    def simulate_due_dca_plans(
        self,
        user_id: int,
        *,
        target_date: Optional[str] = None,
        max_plans: int = 20,
    ) -> Dict[str, Any]:
        date_text = target_date or datetime.now().strftime("%Y-%m-%d")
        target_dt = _parse_date(date_text) or datetime.now()
        target_dt = self._next_cn_trading_day(target_dt)
        target_date_text = target_dt.strftime("%Y-%m-%d")

        active_plans = list_dca_plans(user_id, status="active", limit=500)
        due_plans = [
            item
            for item in active_plans
            if str(item.get("next_run_date") or "") <= target_date_text
        ][: max(1, min(max_plans, 200))]

        runs: List[Dict[str, Any]] = []
        for plan in due_plans:
            plan_id = int(plan["id"])
            code = normalize_fund_code(plan.get("fund_code"))
            base_amount = _safe_float(plan.get("amount_per_cycle"), 0.0) or 0.0
            if not code or base_amount <= 0:
                create_dca_plan_run(
                    user_id=user_id,
                    plan_id=plan_id,
                    fund_code=code or "",
                    scheduled_date=target_date_text,
                    planned_amount=max(base_amount, 0.0),
                    suggested_amount=0.0,
                    status="skipped",
                    context={"reason": "invalid_plan"},
                )
                update_dca_plan(
                    user_id,
                    plan_id,
                    {
                        "last_run_date": target_date_text,
                        "last_run_status": "skipped",
                    },
                )
                continue

            try:
                decision = self.recommend_fund(
                    user_id,
                    code=code,
                    base_amount=base_amount,
                    max_single_day_amount=_safe_float(plan.get("max_daily_amount")),
                    analysis_mode="quick",
                    use_global_cash=True,
                    use_auto_dca=True,
                    refresh_missing=False,
                )
                suggested_amount = _safe_float(decision.get("suggested_amount"), 0.0) or 0.0
                run_status = "simulated"
                run_context = {
                    "decision_id": decision.get("decision_id"),
                    "action": decision.get("action"),
                    "confidence": decision.get("confidence"),
                }
            except Exception as exc:
                suggested_amount = 0.0
                run_status = "failed"
                run_context = {"error": str(exc)}

            run_id = create_dca_plan_run(
                user_id=user_id,
                plan_id=plan_id,
                fund_code=code,
                scheduled_date=target_date_text,
                planned_amount=base_amount,
                suggested_amount=suggested_amount,
                status=run_status,
                context=run_context,
            )

            next_cycle = self._resolve_next_cycle_date(
                target_dt,
                frequency=str(plan.get("frequency") or "daily"),
                execution_weekday=plan.get("execution_weekday"),
                execution_day=plan.get("execution_day"),
            )
            update_dca_plan(
                user_id,
                plan_id,
                {
                    "next_run_date": next_cycle.strftime("%Y-%m-%d"),
                    "last_run_date": target_date_text,
                    "last_run_status": run_status,
                },
            )
            runs.append(
                {
                    "plan_id": plan_id,
                    "run_id": run_id,
                    "fund_code": code,
                    "planned_amount": base_amount,
                    "suggested_amount": suggested_amount,
                    "status": run_status,
                }
            )

        return {
            "target_date": target_date_text,
            "due_count": len(due_plans),
            "simulated_count": len(runs),
            "runs": runs,
        }

    def get_dca_plan_runs(
        self,
        user_id: int,
        *,
        plan_id: Optional[int] = None,
        fund_code: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        rows = list_dca_plan_runs(
            user_id,
            plan_id=plan_id,
            fund_code=normalize_fund_code(fund_code) if fund_code else None,
            limit=limit,
        )
        return {"count": len(rows), "runs": rows}

    def _build_role_evidence_lines(
        self,
        scorecard: Dict[str, Any],
        user_constraints: Dict[str, Any],
    ) -> List[str]:
        factors = scorecard.get("factors", {}) or {}
        return [
            f"????={_safe_float(scorecard.get('total_score'), 0.0) or 0.0:.2f}",
            f"?1???={_safe_float(factors.get('sharpe_1y'), 0.0) or 0.0:.2f}",
            f"?1?????={_safe_float(factors.get('max_drawdown_1y'), 0.0) or 0.0:.2f}%",
            f"?3???={_safe_float(factors.get('return_3m'), 0.0) or 0.0:.2f}%",
            f"????={_safe_float(user_constraints.get('available_cash'), 0.0) or 0.0:.2f}",
            f"????={_safe_float(user_constraints.get('max_single_day_amount'), 0.0) or 0.0:.2f}",
        ]

    def _run_deep_debate_with_llm(
        self,
        *,
        code: str,
        name: str,
        scorecard: Dict[str, Any],
        action: str,
        suggested_amount: float,
        user_constraints: Dict[str, Any],
        global_context: Dict[str, Any],
        fund_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        role_fallback = self._build_deep_mode_explanation(
            scorecard,
            action=action,
            suggested_amount=suggested_amount,
            user_constraints=user_constraints,
        )
        try:
            llm = get_llm_client()
        except Exception:
            llm = None

        evidence_lines = self._build_role_evidence_lines(scorecard, user_constraints)
        shared_payload = {
            "code": code,
            "name": name,
            "scorecard": scorecard,
            "action": action,
            "suggested_amount": suggested_amount,
            "user_constraints": user_constraints,
            "global_context": {
                "available_cash": global_context.get("available_cash"),
                "total_capital": global_context.get("total_capital"),
                "planned_dca_today": global_context.get("planned_dca_today"),
            },
            "fund_context": {
                "existing_dca_daily_amount": fund_context.get("existing_dca_daily_amount"),
                "planned_dca_today": fund_context.get("planned_dca_today"),
            },
        }
        payload_text = self._safe_json_dumps(shared_payload)

        roles_cfg = [
            ("宏观与风格研究员", "从市场风格与指数风险偏好判断当前建议的顺逆风。"),
            ("指数质量研究员", "从收益风险比、回撤、波动角度评估标的质量。"),
            ("风险控制官", "从回撤容忍、资金上限与执行约束判断建议是否需要降级。"),
            ("执行纪律官", "从定投连续性、当日预算和计划一致性给出执行提醒。"),
        ]

        role_views: List[Dict[str, Any]] = []
        for role, duty in roles_cfg:
            fallback_text = f"{role}：维持规则结论，当前动作={action}，建议金额={suggested_amount:.2f}。"
            prompt = (
                "你是基金中长期研究决策系统中的角色代理。\n"
                f"角色：{role}\n"
                f"职责：{duty}\n"
                "请基于给定数据输出一段不超过120字的结论，格式：结论；关键证据；风险提醒。\n"
                "禁止编造数据，必须引用输入里的具体字段。\n"
                f"输入数据：{payload_text}"
            )
            view = self._invoke_llm_text(llm, prompt, fallback=fallback_text)
            role_views.append(
                {
                    "role": role,
                    "view": view,
                    "evidence": evidence_lines[:4],
                }
            )

        bull_history: List[str] = []
        bear_history: List[str] = []
        last_bear = ""
        for round_idx in range(1, 3):
            bull_fallback = f"多头第{round_idx}轮：评分与约束匹配，维持{action}。"
            bull_prompt = (
                "你在投资委员会辩论中担任多头辩手。\n"
                "目标：支持当前建议动作，但要回应空头观点。\n"
                f"当前建议动作={action}，建议金额={suggested_amount:.2f}。\n"
                f"空头上一轮观点：{last_bear or '（无）'}\n"
                f"数据：{payload_text}\n"
                "输出1段120字以内中文。"
            )
            bull_text = self._invoke_llm_text(llm, bull_prompt, fallback=bull_fallback)
            bull_history.append(bull_text)

            bear_fallback = f"空头第{round_idx}轮：强调回撤与预算约束，建议保守执行。"
            bear_prompt = (
                "你在投资委员会辩论中担任空头辩手。\n"
                "目标：指出当前建议可能的风险，并回应多头观点。\n"
                f"多头上一轮观点：{bull_text}\n"
                f"数据：{payload_text}\n"
                "输出1段120字以内中文。"
            )
            bear_text = self._invoke_llm_text(llm, bear_prompt, fallback=bear_fallback)
            bear_history.append(bear_text)
            last_bear = bear_text

        arbitrator_fallback = role_fallback["debate"]["arbitrator"]
        arbitrator_prompt = (
            "你是基金决策系统的裁决官，请基于角色观点和多空辩论给出最终结论。\n"
            "输出格式：最终动作；建议金额；置信度（低/中/高）；主要分歧点。\n"
            f"角色观点：{self._safe_json_dumps(role_views)}\n"
            f"多头观点：{self._safe_json_dumps(bull_history)}\n"
            f"空头观点：{self._safe_json_dumps(bear_history)}\n"
            f"规则动作={action}，规则金额={suggested_amount:.2f}\n"
        )
        arbitrator = self._invoke_llm_text(llm, arbitrator_prompt, fallback=arbitrator_fallback)

        return {
            "engine": "llm_debate" if llm is not None else "rule_fallback",
            "roles": role_views if llm is not None else role_fallback["roles"],
            "debate": {
                "bull": bull_history if llm is not None else role_fallback["debate"]["bull"],
                "bear": bear_history if llm is not None else role_fallback["debate"]["bear"],
                "arbitrator": arbitrator,
            },
        }

    def _build_deep_mode_explanation(
        self,
        scorecard: Dict[str, Any],
        *,
        action: str,
        suggested_amount: float,
        user_constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Deterministic multi-role debate summary for deep mode."""
        factors = scorecard.get("factors", {}) or {}
        total_score = _safe_float(scorecard.get("total_score"), 0.0) or 0.0
        quality_score = _safe_float(scorecard.get("quality_score"), 0.0) or 0.0
        risk_return_score = _safe_float(scorecard.get("risk_return_score"), 0.0) or 0.0
        valuation_score = _safe_float(scorecard.get("valuation_position_score"), 0.0) or 0.0

        macro_role = {
            "role": "宏观与指数风格",
            "view": "中性",
            "evidence": [
                f"综合评分 {total_score:.1f}，质量 {quality_score:.1f}，风险收益 {risk_return_score:.1f}",
                f"估值位置评分 {valuation_score:.1f}，用于判断中长期分批节奏",
            ],
        }
        if total_score >= 70:
            macro_role["view"] = "偏多"
        elif total_score < 50:
            macro_role["view"] = "偏空"

        risk_role = {
            "role": "风险控制与回撤纪律",
            "view": "中性",
            "evidence": [
                f"1年最大回撤 {(_safe_float(factors.get('max_drawdown_1y'), 0.0) or 0.0):.2f}%",
                f"用户回撤容忍度 {(_safe_float(user_constraints.get('max_drawdown_tolerance'), self.MAX_DRAWDOWN_ALLOWED) or self.MAX_DRAWDOWN_ALLOWED):.2f}%",
            ],
        }
        max_dd = _safe_float(factors.get("max_drawdown_1y"))
        tolerance = _safe_float(user_constraints.get("max_drawdown_tolerance"), self.MAX_DRAWDOWN_ALLOWED)
        if max_dd is not None and tolerance is not None:
            if max_dd <= tolerance:
                risk_role["view"] = "可控"
            else:
                risk_role["view"] = "偏紧"

        discipline_role = {
            "role": "执行纪律与资金约束",
            "view": "中性",
            "evidence": [
                f"建议金额 {suggested_amount:.2f}",
                f"可用现金 {(_safe_float(user_constraints.get('available_cash'), 0.0) or 0.0):.2f}",
                f"单日上限 {(_safe_float(user_constraints.get('max_single_day_amount'), 0.0) or 0.0):.2f}",
                f"既有日定投 {(_safe_float(user_constraints.get('existing_dca_daily_amount'), 0.0) or 0.0):.2f}",
            ],
        }
        if action == "pause":
            discipline_role["view"] = "保守"
        elif action == "add":
            discipline_role["view"] = "可执行"

        long_short_debate = {
            "bull": [
                "评分结构支持继续中长期定投框架",
                "估值与波动维度未出现系统性失真",
            ],
            "bear": [
                "短期回撤与情绪可能继续扰动",
                "资金约束可能限制加仓幅度，需防止追高",
            ],
            "arbitrator": f"裁决结果：{action}，建议金额 {suggested_amount:.2f}",
        }

        return {
            "roles": [macro_role, risk_role, discipline_role],
            "debate": long_short_debate,
        }

    def recommend_fund(
        self,
        user_id: int,
        *,
        code: str,
        base_amount: float,
        available_cash: Optional[float] = None,
        max_single_day_amount: Optional[float] = None,
        tactical_boost: Optional[bool] = None,
        strict_tactical: bool = True,
        max_drawdown_tolerance: Optional[float] = None,
        existing_dca_daily_amount: Optional[float] = None,
        analysis_mode: str = "quick",
        use_global_cash: bool = True,
        use_auto_dca: bool = True,
        refresh_missing: bool = False,
    ) -> Dict[str, Any]:
        """Generate standardized DCA recommendation card for one fund."""
        started_at = datetime.now()
        normalized_code = normalize_fund_code(code)
        if not normalized_code:
            raise ValueError("基金代码无效")

        mode = str(analysis_mode or "quick").strip().lower()
        if mode not in {"quick", "deep"}:
            mode = "quick"

        global_context = self._build_global_context(user_id)
        if use_global_cash and available_cash is None:
            available_cash = _safe_float(global_context.get("available_cash"))

        dca_metrics: Optional[Dict[str, Any]] = None
        raw_existing_dca_daily_amount = existing_dca_daily_amount
        if use_auto_dca and existing_dca_daily_amount is None:
            dca_metrics = self._compute_fund_dca_metrics_30d(user_id, normalized_code)
            existing_dca_daily_amount = _safe_float(dca_metrics.get("avg_daily_amount_30d"), 0.0) or 0.0

        today = datetime.now().strftime("%Y-%m-%d")
        active_dca_plans = list_dca_plans(
            user_id,
            status="active",
            fund_code=normalized_code,
            limit=50,
        )
        planned_dca_today = round(
            get_planned_dca_amount(user_id, today, fund_code=normalized_code),
            2,
        )
        effective_existing_dca = (
            _safe_float(existing_dca_daily_amount, 0.0) or 0.0
        ) + planned_dca_today

        preference_row = get_user_preferences(user_id) or {}
        preferences = preference_row.get("preferences") or {}
        if max_drawdown_tolerance is None:
            pref_drawdown = _safe_float(preferences.get("max_drawdown_tolerance"))
            if pref_drawdown is not None:
                max_drawdown_tolerance = pref_drawdown * 100 if pref_drawdown <= 1 else pref_drawdown

        # Hard rule: ensure candidate pool completeness before research.
        if get_fund_universe_count(user_id, active_only=True) == 0:
            self.sync_universe(user_id, full_sync=True)
        missing = get_missing_universe_codes(user_id, [normalized_code])
        if missing:
            self.sync_universe(user_id, full_sync=False, codes=missing)

        universe = get_fund_universe(user_id=user_id, active_only=True, codes=[normalized_code])
        if not universe:
            raise ValueError(f"基金 {normalized_code} 不在候选池中")

        score_result = self.score_funds(
            user_id,
            codes=[normalized_code],
            top_n=1,
            min_score=0.0,
            refresh_missing=refresh_missing,
        )

        scorecard = None
        if score_result["scores"]:
            scorecard = score_result["scores"][0]
        else:
            # Use rejected info fallback for explicit explanation.
            rejected = next(
                (item for item in score_result.get("rejected", []) if item.get("code") == normalized_code),
                None,
            )
            scorecard = {
                "code": normalized_code,
                "name": universe[0].get("name", normalized_code),
                "total_score": 0.0,
                "quality_score": 0.0,
                "risk_return_score": 0.0,
                "valuation_position_score": 0.0,
                "hard_filter_pass": False,
                "hard_filter_reasons": (rejected or {}).get("reasons", ["insufficient_data"]),
                "factors": {},
                "trade_date": self._current_trade_date(db_format=True),
            }

        factors = scorecard.get("factors", {})
        total_score = float(scorecard.get("total_score", 0.0))
        base_amount = max(0.0, float(base_amount))
        tactical_boost_enabled = strict_tactical if tactical_boost is None else bool(tactical_boost)
        effective_max_drawdown = self.MAX_DRAWDOWN_ALLOWED
        if max_drawdown_tolerance is not None:
            effective_max_drawdown = max(5.0, min(self.MAX_DRAWDOWN_ALLOWED, float(max_drawdown_tolerance)))

        action = "pause"
        multiplier = 0.0
        if scorecard.get("hard_filter_pass"):
            if total_score >= 75:
                action = "add"
                multiplier = 1.2
            elif total_score >= 60:
                action = "add"
                multiplier = 1.0
            elif total_score >= 45:
                action = "hold"
                multiplier = 0.7
            else:
                action = "pause"
                multiplier = 0.0

        tactical_triggered = False
        tactical_boost_reason: List[str] = []
        ret_1m = _safe_float(factors.get("return_1m"), 0.0) or 0.0
        ret_3m = _safe_float(factors.get("return_3m"), 0.0) or 0.0
        sharpe_20d = _safe_float(factors.get("sharpe_20d"), 0.0) or 0.0
        max_dd = _safe_float(factors.get("max_drawdown_1y"), 0.0) or 0.0

        if tactical_boost_enabled and scorecard.get("hard_filter_pass"):
            cond_1 = ret_1m <= -4.0
            cond_2 = ret_3m <= -8.0
            cond_3 = sharpe_20d > 0
            cond_4 = max_dd <= effective_max_drawdown
            tactical_boost_reason.extend(
                [
                    f"近1月收益 <= -4%：{'满足' if cond_1 else '不满足'}（{ret_1m:.2f}%）",
                    f"近3月收益 <= -8%：{'满足' if cond_2 else '不满足'}（{ret_3m:.2f}%）",
                    f"20日夏普 > 0：{'满足' if cond_3 else '不满足'}（{sharpe_20d:.2f}）",
                    f"最大回撤 <= {effective_max_drawdown:.1f}%：{'满足' if cond_4 else '不满足'}（{max_dd:.2f}%）",
                ]
            )
            tactical_triggered = cond_1 and cond_2 and cond_3 and cond_4
            if tactical_triggered:
                multiplier = min(1.5, multiplier + 0.3)
                tactical_boost_reason.append("已触发波段增强（乘数 +0.3）")
        elif not tactical_boost_enabled:
            tactical_boost_reason.append("已关闭波段增强开关")
        else:
            tactical_boost_reason.append("未满足硬性筛选条件，跳过波段增强")

        suggested_amount = round(base_amount * multiplier, 2)
        if available_cash is not None:
            suggested_amount = min(suggested_amount, round(max(0.0, float(available_cash)), 2))
        if max_single_day_amount is not None:
            suggested_amount = min(suggested_amount, round(max(0.0, float(max_single_day_amount)), 2))
        if max_single_day_amount is not None:
            existing_amount = max(0.0, float(effective_existing_dca))
            daily_cap = max(0.0, float(max_single_day_amount))
            residual_capacity = max(0.0, daily_cap - existing_amount)
            suggested_amount = min(suggested_amount, round(residual_capacity, 2))

        completeness = 1.0
        if score_result.get("missing_factor_count", 0) > 0:
            completeness = 0.75
        confidence = round(
                _clamp(total_score * 0.7 + (20 if scorecard.get("hard_filter_pass") else 0) + completeness * 10, 0, 100)
            / 100,
            2,
        )
        confidence_band = self._confidence_band(confidence)
        debate_points = self._build_debate_points(scorecard)

        evidence = self._build_evidence(scorecard, universe[0])
        if available_cash is not None:
            evidence.append(
                {
                    "metric": "全局可用现金",
                    "value": round(float(available_cash), 2),
                    "source": "portfolio+preferences",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        if dca_metrics:
            evidence.append(
                {
                    "metric": "近30天日均定投",
                    "value": round(_safe_float(dca_metrics.get("avg_daily_amount_30d"), 0.0) or 0.0, 2),
                    "source": "transactions",
                    "timestamp": dca_metrics.get("metric_date"),
                }
            )
        if planned_dca_today > 0:
            evidence.append(
                {
                    "metric": "今日计划定投金额",
                    "value": planned_dca_today,
                    "source": "fund_dca_plans",
                    "timestamp": today,
                }
            )
        trigger_conditions = [
            "评分>=60维持基础定投，评分>=75允许提高基础定投。",
            "增强定投仅在回撤+短期修复信号同时满足时触发。",
            "关键风险指标缺失或失真时，建议自动降级为观望。",
        ]
        invalidate_conditions = [
            "基金不再属于候选池（指数ETF/联接）",
            f"1年最大回撤超过{effective_max_drawdown:.0f}%",
            "关键输入数据连续缺失（净值/风险因子）",
        ]
        risk_notes = [
            "本建议为研究决策支持，不包含自动下单。",
            "定投金额需匹配现金流、单日上限、既有定投计划与回撤容忍度。",
            "若市场极端波动，优先执行风险控制规则与暂停条件。",
        ]
        user_constraints = {
            "available_cash": available_cash,
            "max_single_day_amount": max_single_day_amount,
            "existing_dca_daily_amount": existing_dca_daily_amount,
            "effective_existing_dca_daily_amount": round(effective_existing_dca, 2),
            "planned_dca_today": planned_dca_today,
            "max_drawdown_tolerance": effective_max_drawdown,
            "tactical_boost_enabled": tactical_boost_enabled,
            "use_global_cash": bool(use_global_cash),
            "use_auto_dca": bool(use_auto_dca),
        }
        strategy_explanation = (
            f"评分 {total_score:.1f} 对应动作 {action}；"
            f"基础金额 {base_amount:.2f} × 乘数 {multiplier:.2f} = 建议 {suggested_amount:.2f}。"
            "最终结果已按可用现金、单日上限和既有定投占用进行约束。"
        )

        context_payload = {
            "analysis_mode": mode,
            "global_context": global_context,
            "fund_context": {
                "code": normalized_code,
                "existing_dca_daily_amount": raw_existing_dca_daily_amount,
                "effective_existing_dca_daily_amount": round(effective_existing_dca, 2),
                "planned_dca_today": planned_dca_today,
                "active_dca_plans": active_dca_plans,
                "dca_metrics_30d": dca_metrics,
                "use_global_cash": bool(use_global_cash),
                "use_auto_dca": bool(use_auto_dca),
            },
            "decision_input": {
                "base_amount": round(base_amount, 2),
                "available_cash": available_cash,
                "max_single_day_amount": max_single_day_amount,
                "strict_tactical": strict_tactical,
                "tactical_boost": tactical_boost_enabled,
                "max_drawdown_tolerance": max_drawdown_tolerance,
                "existing_dca_daily_amount": raw_existing_dca_daily_amount,
                "effective_existing_dca_daily_amount": round(effective_existing_dca, 2),
                "planned_dca_today": planned_dca_today,
                "use_global_cash": bool(use_global_cash),
                "use_auto_dca": bool(use_auto_dca),
                "refresh_missing": bool(refresh_missing),
            },
        }
        context_hash = _snapshot_hash(context_payload)
        context_snapshot_id = save_context_snapshot(
            user_id,
            fund_code=normalized_code,
            context_hash=context_hash,
            context=context_payload,
            source={"name": "fund_research_service", "scope": "recommend"},
        )

        decision = {
            "code": normalized_code,
            "name": scorecard.get("name", normalized_code),
            "trade_date": scorecard.get("trade_date") or self._current_trade_date(db_format=True),
            "analysis_mode": mode,
            "action": action,
            "base_amount": round(base_amount, 2),
            "suggested_amount": round(suggested_amount, 2),
            "allocation_multiplier": round(multiplier, 2),
            "tactical_boost_enabled": tactical_boost_enabled,
            "tactical_boost_triggered": tactical_triggered,
            "tactical_boost_reason": tactical_boost_reason,
            # backward-compatible aliases
            "strict_tactical_enabled": tactical_boost_enabled,
            "strict_tactical_triggered": tactical_triggered,
            "confidence": confidence,
            "confidence_band": confidence_band,
            "bull_points": debate_points["bull_points"],
            "bear_points": debate_points["bear_points"],
            "disagreement_points": debate_points["disagreement_points"],
            "strategy_explanation": strategy_explanation,
            "user_constraints": user_constraints,
            "scorecard": scorecard,
            "evidence": evidence,
            "trigger_conditions": trigger_conditions,
            "invalidate_conditions": invalidate_conditions,
            "risk_notes": risk_notes,
            "context_hash": context_hash,
            "context_snapshot_id": context_snapshot_id,
            "global_context": global_context,
            "fund_context": {
                "code": normalized_code,
                "existing_dca_daily_amount": raw_existing_dca_daily_amount,
                "effective_existing_dca_daily_amount": round(effective_existing_dca, 2),
                "planned_dca_today": planned_dca_today,
                "active_dca_plans": active_dca_plans,
                "dca_metrics_30d": dca_metrics,
            },
            "generated_at": datetime.now().isoformat(),
        }
        if mode == "deep":
            decision["deep_analysis"] = self._run_deep_debate_with_llm(
                code=normalized_code,
                name=scorecard.get("name", normalized_code),
                scorecard=scorecard,
                action=action,
                suggested_amount=suggested_amount,
                user_constraints=user_constraints,
                global_context=global_context,
                fund_context=decision["fund_context"],
            )

        snapshot_payload = {
            "fund": universe[0],
            "scorecard": scorecard,
            "decision_input": context_payload["decision_input"],
            "global_context": global_context,
            "fund_context": context_payload["fund_context"],
        }
        snapshot_hash = _snapshot_hash(snapshot_payload)
        snapshot_id = save_fund_snapshot(
            user_id=user_id,
            fund_code=normalized_code,
            trade_date=decision["trade_date"],
            snapshot_hash=snapshot_hash,
            snapshot=snapshot_payload,
            source={"name": "fund_research_service", "version": "p1"},
        )
        scorecard_id = save_fund_scorecard(
            user_id=user_id,
            fund_code=normalized_code,
            trade_date=decision["trade_date"],
            snapshot_hash=snapshot_hash,
            scorecard=scorecard,
        )
        decision_id = save_recommendation_decision(
            user_id=user_id,
            fund_code=normalized_code,
            trade_date=decision["trade_date"],
            snapshot_hash=snapshot_hash,
            action=action,
            suggested_amount=suggested_amount,
            confidence=confidence,
            decision=decision,
            snapshot_id=snapshot_id,
            scorecard_id=scorecard_id,
        )
        decision["decision_id"] = decision_id
        decision["latency_ms"] = int((datetime.now() - started_at).total_seconds() * 1000)
        return decision

    def _build_selection_debate(
        self,
        *,
        candidates: List[Dict[str, Any]],
        market_context: Dict[str, Any],
        top_n: int,
    ) -> Dict[str, Any]:
        try:
            llm = get_llm_client()
        except Exception:
            llm = None

        payload = {
            "market_context": market_context,
            "candidate_count": len(candidates),
            "candidates": [
                {
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "score": item.get("total_score"),
                    "return_1m": (item.get("factors") or {}).get("return_1m"),
                    "return_3m": (item.get("factors") or {}).get("return_3m"),
                    "sharpe_1y": (item.get("factors") or {}).get("sharpe_1y"),
                    "max_drawdown_1y": (item.get("factors") or {}).get("max_drawdown_1y"),
                }
                for item in candidates[: max(10, top_n + 4)]
            ],
        }
        payload_text = self._safe_json_dumps(payload)

        role_prompts = [
            ("宏观研究员", "基于市场状态评估当前应偏进攻还是偏防守。"),
            ("指数质量研究员", "比较候选基金风险收益质量，给出最值得保留的标的。"),
            ("风险控制官", "指出回撤、波动、拥挤风险，并给出降风险建议。"),
            ("执行纪律官", "从资金约束和计划一致性角度判断可执行性。"),
        ]

        role_outputs: List[Dict[str, Any]] = []
        for role, duty in role_prompts:
            fallback = f"{role}：维持规则排序，建议先看前{top_n}名并分批执行。"
            prompt = (
                "你在基金精选系统中担任角色代理。\n"
                f"角色：{role}\n"
                f"职责：{duty}\n"
                "请用120字以内输出：判断 + 关键证据 + 风险提示。\n"
                f"输入：{payload_text}"
            )
            text = self._invoke_llm_text(llm, prompt, fallback=fallback)
            role_outputs.append({"role": role, "view": text})

        bull_fallback = "多头：候选池头部质量较高，可优先配置评分靠前标的。"
        bull = self._invoke_llm_text(
            llm,
            (
                "你是基金精选辩论中的多头。\n"
                "目标：支持从候选池中选出更积极的配置组合。\n"
                f"输入：{payload_text}"
            ),
            fallback=bull_fallback,
        )
        bear_fallback = "空头：需警惕高波动与回撤，建议控制集中度与节奏。"
        bear = self._invoke_llm_text(
            llm,
            (
                "你是基金精选辩论中的空头。\n"
                "目标：强调下行风险并提出防守约束。\n"
                f"多头观点：{bull}\n"
                f"输入：{payload_text}"
            ),
            fallback=bear_fallback,
        )
        arb_fallback = "裁决：保留规则前列基金，按风险分层择优，分批执行。"
        arbitrator = self._invoke_llm_text(
            llm,
            (
                "你是基金精选裁决官。\n"
                "请输出：最终精选原则、应保留的基金特征、关键风险约束。\n"
                f"角色观点：{self._safe_json_dumps(role_outputs)}\n"
                f"多头观点：{bull}\n"
                f"空头观点：{bear}\n"
            ),
            fallback=arb_fallback,
        )

        return {
            "engine": "llm_debate" if llm is not None else "rule_fallback",
            "roles": role_outputs,
            "bull": bull,
            "bear": bear,
            "arbitrator": arbitrator,
        }

    def run_ai_selection(
        self,
        user_id: int,
        *,
        top_n: int = 10,
        candidate_limit: int = 30,
        min_score: float = 0.0,
        refresh_missing: bool = True,
        analysis_mode: str = "deep",
    ) -> Dict[str, Any]:
        """AI-heavy selection system for candidate pool."""
        scored = self.score_funds(
            user_id,
            codes=None,
            top_n=max(5, min(candidate_limit, 100)),
            min_score=min_score,
            refresh_missing=refresh_missing,
        )
        ranked = list(scored.get("scores") or [])
        selected = ranked[: max(1, min(top_n, 50))]
        if not selected:
            return {
                "trade_date": scored.get("trade_date") or self._current_trade_date(db_format=True),
                "candidate_count": 0,
                "selected_count": 0,
                "selected": [],
                "debate": {
                    "engine": "rule_fallback",
                    "roles": [],
                    "bull": "候选池为空，无法精选。",
                    "bear": "候选池为空，无法精选。",
                    "arbitrator": "请先补全候选池与因子数据。",
                },
            }

        # Build lightweight market context from candidate cross-section.
        def _avg_factor(key: str) -> float:
            values = [
                _safe_float((item.get("factors") or {}).get(key))
                for item in ranked[: min(len(ranked), 30)]
            ]
            clean = [v for v in values if v is not None]
            if not clean:
                return 0.0
            return round(sum(clean) / len(clean), 2)

        market_context = {
            "avg_score_top30": round(
                sum((_safe_float(item.get("total_score"), 0.0) or 0.0) for item in ranked[:30])
                / max(1, min(len(ranked), 30)),
                2,
            ),
            "avg_return_1m_top30": _avg_factor("return_1m"),
            "avg_return_3m_top30": _avg_factor("return_3m"),
            "avg_sharpe_1y_top30": _avg_factor("sharpe_1y"),
            "avg_drawdown_1y_top30": _avg_factor("max_drawdown_1y"),
        }

        debate = self._build_selection_debate(
            candidates=ranked,
            market_context=market_context,
            top_n=top_n,
        )

        selected_rows: List[Dict[str, Any]] = []
        for idx, row in enumerate(selected, start=1):
            factors = row.get("factors") or {}
            selected_rows.append(
                {
                    "rank": idx,
                    "code": row.get("code"),
                    "name": row.get("name"),
                    "score": row.get("total_score"),
                    "quality_score": row.get("quality_score"),
                    "risk_return_score": row.get("risk_return_score"),
                    "valuation_position_score": row.get("valuation_position_score"),
                    "return_1m": factors.get("return_1m"),
                    "return_3m": factors.get("return_3m"),
                    "sharpe_1y": factors.get("sharpe_1y"),
                    "max_drawdown_1y": factors.get("max_drawdown_1y"),
                }
            )

        return {
            "trade_date": scored.get("trade_date") or self._current_trade_date(db_format=True),
            "candidate_count": len(ranked),
            "selected_count": len(selected_rows),
            "selected": selected_rows,
            "market_context": market_context,
            "debate": debate if str(analysis_mode or "deep").lower() == "deep" else None,
        }

    def suggest_personal_constraints(
        self,
        user_id: int,
    ) -> Dict[str, Any]:
        """Suggest user constraints (cash/day cap/drawdown/tactical) with rule+LLM synthesis."""
        preference_row = get_user_preferences(user_id) or {}
        preferences = preference_row.get("preferences") or {}
        global_context = self._build_global_context(user_id)

        available_cash = _safe_float(global_context.get("available_cash"), 0.0) or 0.0
        total_capital = _safe_float(global_context.get("total_capital"), 0.0) or 0.0
        planned_dca_today = _safe_float(global_context.get("planned_dca_today"), 0.0) or 0.0

        risk_level = str(preferences.get("risk_level") or "moderate").lower()
        drawdown_hint = _safe_float(preferences.get("max_drawdown_tolerance"))
        if drawdown_hint is None:
            drawdown_hint = {"conservative": 0.12, "moderate": 0.2, "aggressive": 0.28}.get(
                risk_level,
                0.2,
            )
        if drawdown_hint <= 1:
            drawdown_hint *= 100

        rule_daily_cap = 0.0
        if available_cash > 0:
            rule_daily_cap = max(30.0, min(available_cash * 0.08, max(total_capital * 0.03, 100.0)))
        rule_daily_cap = round(rule_daily_cap, 2)
        residual_cap = max(0.0, round(rule_daily_cap - planned_dca_today, 2))

        rule_suggestion = {
            "available_cash": round(available_cash, 2),
            "recommended_max_single_day_amount": rule_daily_cap,
            "recommended_residual_today": residual_cap,
            "recommended_max_drawdown_tolerance": round(drawdown_hint, 2),
            "recommended_tactical_boost": bool(risk_level in {"moderate", "aggressive", "speculative"}),
            "risk_level": risk_level,
        }

        ai_suggestion: Optional[Dict[str, Any]] = None
        try:
            llm = get_llm_client()
        except Exception:
            llm = None

        if llm is not None:
            prompt = (
                "你是基金投研系统的约束参数顾问。\n"
                "请基于输入上下文输出JSON，字段：max_single_day_amount, max_drawdown_tolerance, tactical_boost, note。\n"
                "要求：数值务实，不要超过可用现金，回撤容忍度单位是百分比。\n"
                f"输入上下文：{self._safe_json_dumps({'rule': rule_suggestion, 'preferences': preferences, 'global_context': global_context})}"
            )
            raw = self._invoke_llm_text(
                llm,
                prompt,
                fallback=self._safe_json_dumps(
                    {
                        "max_single_day_amount": rule_suggestion["recommended_max_single_day_amount"],
                        "max_drawdown_tolerance": rule_suggestion["recommended_max_drawdown_tolerance"],
                        "tactical_boost": rule_suggestion["recommended_tactical_boost"],
                        "note": "回退到规则建议",
                    }
                ),
            )
            ai_suggestion = self._extract_json_object(raw)

        final_suggestion = {
            "max_single_day_amount": rule_suggestion["recommended_max_single_day_amount"],
            "max_drawdown_tolerance": rule_suggestion["recommended_max_drawdown_tolerance"],
            "tactical_boost": rule_suggestion["recommended_tactical_boost"],
        }
        if ai_suggestion:
            ai_daily = _safe_float(ai_suggestion.get("max_single_day_amount"))
            ai_drawdown = _safe_float(ai_suggestion.get("max_drawdown_tolerance"))
            if ai_daily is not None:
                final_suggestion["max_single_day_amount"] = round(max(0.0, min(ai_daily, available_cash)), 2)
            if ai_drawdown is not None:
                final_suggestion["max_drawdown_tolerance"] = round(max(5.0, min(ai_drawdown, self.MAX_DRAWDOWN_ALLOWED)), 2)
            if ai_suggestion.get("tactical_boost") is not None:
                final_suggestion["tactical_boost"] = bool(ai_suggestion.get("tactical_boost"))

        return {
            "rule_suggestion": rule_suggestion,
            "ai_suggestion": ai_suggestion,
            "final_suggestion": final_suggestion,
            "global_context": global_context,
        }

    def create_batch_recommendation_job(
        self,
        user_id: int,
        *,
        codes: Optional[List[str]] = None,
        top_n: int = 10,
        source: str = "ai_top",
        base_amount: float = 30.0,
        available_cash: Optional[float] = None,
        max_single_day_amount: Optional[float] = None,
        tactical_boost: Optional[bool] = None,
        strict_tactical: bool = True,
        max_drawdown_tolerance: Optional[float] = None,
        existing_dca_daily_amount: Optional[float] = None,
        analysis_mode: str = "quick",
        use_global_cash: bool = True,
        use_auto_dca: bool = True,
        refresh_missing: bool = False,
    ) -> Dict[str, Any]:
        """Create a background batch-research job."""
        normalized_codes = sorted(
            {normalize_fund_code(code) for code in (codes or []) if normalize_fund_code(code)}
        )
        if not normalized_codes:
            scored = self.score_funds(
                user_id,
                codes=None,
                top_n=max(1, min(top_n, 50)),
                min_score=0.0,
                refresh_missing=refresh_missing,
            )
            normalized_codes = [
                item["code"] for item in (scored.get("scores") or []) if item.get("code")
            ][: max(1, min(top_n, 50))]

        if not normalized_codes:
            raise ValueError("未找到可用于批量研究的候选基金")

        global_context = self._build_global_context(user_id)
        input_payload = {
            "codes": normalized_codes,
            "top_n": top_n,
            "source": source,
            "base_amount": base_amount,
            "available_cash": available_cash,
            "max_single_day_amount": max_single_day_amount,
            "tactical_boost": tactical_boost,
            "strict_tactical": strict_tactical,
            "max_drawdown_tolerance": max_drawdown_tolerance,
            "existing_dca_daily_amount": existing_dca_daily_amount,
            "analysis_mode": analysis_mode,
            "use_global_cash": use_global_cash,
            "use_auto_dca": use_auto_dca,
            "refresh_missing": refresh_missing,
        }
        context_payload = {
            "global_context": global_context,
            "created_at": datetime.now().isoformat(),
        }
        job_id = create_batch_job(
            user_id,
            source=source,
            analysis_mode=analysis_mode,
            codes=normalized_codes,
            input_payload=input_payload,
            context_payload=context_payload,
            message=f"批量研究任务已创建，共 {len(normalized_codes)} 只基金",
        )
        return {
            "job_id": job_id,
            "codes": normalized_codes,
            "count": len(normalized_codes),
            "job": get_batch_job(user_id, job_id, include_items=True),
        }

    def run_batch_job(
        self,
        user_id: int,
        job_id: int,
        *,
        max_workers: int = 3,
    ) -> Dict[str, Any]:
        """Execute one batch job in background with bounded concurrency."""
        job = get_batch_job(user_id, job_id, include_items=True)
        if not job:
            raise ValueError("批量任务不存在")

        if job.get("status") in {"cancelled", "completed"}:
            return job

        update_batch_job_status(
            user_id,
            job_id,
            status="running",
            started=True,
            message="批量研究执行中",
        )

        input_cfg = job.get("input") or {}
        pending_items = [
            item for item in (job.get("items") or [])
            if str(item.get("status") or "").lower() in {"pending", "failed"}
        ]
        codes = [item.get("fund_code") for item in pending_items if item.get("fund_code")]

        if not codes:
            counters = compute_batch_job_counters(user_id, job_id)
            final_status = "completed" if counters["failed_count"] == 0 else "completed_with_errors"
            update_batch_job_status(
                user_id,
                job_id,
                status=final_status,
                finished=True,
                message="批量研究已完成",
            )
            return get_batch_job(user_id, job_id, include_items=True) or {}

        workers = max(1, min(int(max_workers), 6, len(codes)))

        def _process_one(fund_code: str) -> Tuple[str, str]:
            current = get_batch_job(user_id, job_id, include_items=False) or {}
            if str(current.get("status", "")).lower() == "cancelled":
                update_batch_job_item(
                    user_id,
                    job_id,
                    fund_code,
                    status="cancelled",
                    error_message="job_cancelled",
                    finished=True,
                )
                return fund_code, "cancelled"

            update_batch_job_item(
                user_id,
                job_id,
                fund_code,
                status="running",
                started=True,
                error_message=None,
            )
            try:
                result = self.recommend_fund(
                    user_id,
                    code=fund_code,
                    base_amount=float(input_cfg.get("base_amount", 30.0) or 30.0),
                    available_cash=_safe_float(input_cfg.get("available_cash")),
                    max_single_day_amount=_safe_float(input_cfg.get("max_single_day_amount")),
                    tactical_boost=input_cfg.get("tactical_boost"),
                    strict_tactical=bool(input_cfg.get("strict_tactical", True)),
                    max_drawdown_tolerance=_safe_float(input_cfg.get("max_drawdown_tolerance")),
                    existing_dca_daily_amount=_safe_float(input_cfg.get("existing_dca_daily_amount")),
                    analysis_mode=str(input_cfg.get("analysis_mode", "quick")),
                    use_global_cash=bool(input_cfg.get("use_global_cash", True)),
                    use_auto_dca=bool(input_cfg.get("use_auto_dca", True)),
                    refresh_missing=bool(input_cfg.get("refresh_missing", False)),
                )
                update_batch_job_item(
                    user_id,
                    job_id,
                    fund_code,
                    status="completed",
                    decision_id=result.get("decision_id"),
                    result=result,
                    error_message=None,
                    finished=True,
                )
                return fund_code, "completed"
            except Exception as exc:
                update_batch_job_item(
                    user_id,
                    job_id,
                    fund_code,
                    status="failed",
                    error_message=str(exc)[:800],
                    finished=True,
                )
                return fund_code, "failed"

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_process_one, code) for code in codes]
            for _future in as_completed(futures):
                compute_batch_job_counters(user_id, job_id)

        counters = compute_batch_job_counters(user_id, job_id)
        latest = get_batch_job(user_id, job_id, include_items=False) or {}
        if str(latest.get("status", "")).lower() == "cancelled":
            final_status = "cancelled"
            message = "任务已取消"
        elif counters["failed_count"] > 0:
            final_status = "completed_with_errors"
            message = (
                f"任务完成：成功 {counters['completed_count']}，失败 {counters['failed_count']}"
            )
        else:
            final_status = "completed"
            message = f"任务完成：共 {counters['completed_count']} 只基金"

        update_batch_job_status(
            user_id,
            job_id,
            status=final_status,
            finished=True,
            message=message,
        )
        return get_batch_job(user_id, job_id, include_items=True) or {}

    def get_batch_job_status(self, user_id: int, job_id: int) -> Dict[str, Any]:
        """Read one batch job with latest counters."""
        counters = compute_batch_job_counters(user_id, job_id)
        job = get_batch_job(user_id, job_id, include_items=True)
        if not job:
            raise ValueError("批量任务不存在")
        job["progress"] = {
            "total": counters["total_count"],
            "completed": counters["completed_count"],
            "failed": counters["failed_count"],
            "cancelled": counters["cancelled_count"],
            "done_ratio": round(
                (
                    (counters["completed_count"] + counters["failed_count"] + counters["cancelled_count"])
                    / max(counters["total_count"], 1)
                ),
                4,
            ),
        }
        return job

    def retry_failed_batch_job(self, user_id: int, job_id: int) -> Dict[str, Any]:
        """Reset failed rows and put job back to pending."""
        reset_count = reset_failed_batch_items(user_id, job_id)
        if reset_count <= 0:
            raise ValueError("没有可重试的失败项")
        compute_batch_job_counters(user_id, job_id)
        update_batch_job_status(
            user_id,
            job_id,
            status="pending",
            finished=False,
            reset_timestamps=True,
            message=f"已重置 {reset_count} 个失败项，等待重跑",
        )
        return {
            "job_id": job_id,
            "reset_count": reset_count,
            "job": get_batch_job(user_id, job_id, include_items=True),
        }

    def cancel_batch_job(self, user_id: int, job_id: int) -> Dict[str, Any]:
        """Cancel one running/pending batch job."""
        changed = cancel_batch_job_items(user_id, job_id)
        compute_batch_job_counters(user_id, job_id)
        update_batch_job_status(
            user_id,
            job_id,
            status="cancelled",
            finished=True,
            message=f"任务已取消（变更 {changed} 条记录）",
        )
        return {
            "job_id": job_id,
            "changed_items": changed,
            "job": get_batch_job(user_id, job_id, include_items=True),
        }

    def list_batch_history(self, user_id: int, limit: int = 20) -> Dict[str, Any]:
        """List historical batch jobs."""
        return {
            "jobs": list_batch_jobs(user_id, limit=max(1, min(limit, 100))),
        }

    def refresh_context_for_transaction_change(
        self,
        user_id: int,
        fund_code: str,
    ) -> Dict[str, Any]:
        """Called after transaction mutations to keep DCA/context fresh."""
        normalized_code = normalize_fund_code(fund_code)
        if not normalized_code:
            return {"updated": False, "reason": "invalid_code"}

        dca = self._compute_fund_dca_metrics_30d(user_id, normalized_code, force_recompute=True)
        context = self.get_fund_context(user_id, normalized_code)
        auto_review = self.auto_review_from_transactions(user_id, normalized_code)
        return {
            "updated": True,
            "fund_code": normalized_code,
            "dca_metrics_30d": dca,
            "context_hash": context.get("context_hash"),
            "auto_review": auto_review,
        }

    def run_daily_context_refresh(self) -> Dict[str, Any]:
        """Daily task: refresh all user/fund DCA metrics and context snapshots."""
        conn = get_db_connection()
        tx_rows = conn.execute(
            """
            SELECT DISTINCT user_id, asset_code
            FROM transactions
            WHERE asset_type = 'fund'
            """
        ).fetchall()
        plan_rows = conn.execute(
            """
            SELECT DISTINCT user_id, fund_code
            FROM fund_dca_plans
            WHERE status = 'active'
            """
        ).fetchall()
        conn.close()

        rows = []
        seen = set()
        for row in tx_rows:
            key = (int(row["user_id"]), normalize_fund_code(row["asset_code"]))
            if key[1] and key not in seen:
                seen.add(key)
                rows.append({"user_id": key[0], "code": key[1]})
        for row in plan_rows:
            key = (int(row["user_id"]), normalize_fund_code(row["fund_code"]))
            if key[1] and key not in seen:
                seen.add(key)
                rows.append({"user_id": key[0], "code": key[1]})

        users_with_plan = sorted({int(row["user_id"]) for row in plan_rows})
        simulated = 0
        for user_id in users_with_plan:
            try:
                self.simulate_due_dca_plans(user_id, target_date=datetime.now().strftime("%Y-%m-%d"), max_plans=200)
                simulated += 1
            except Exception:
                pass

        updated = 0
        failures = 0
        for row in rows:
            user_id = int(row["user_id"])
            code = normalize_fund_code(row["code"])
            if not code:
                continue
            try:
                self._compute_fund_dca_metrics_30d(user_id, code, force_recompute=True)
                self.get_fund_context(user_id, code)
                self.auto_review_from_transactions(user_id, code)
                updated += 1
            except Exception:
                failures += 1
        return {
            "updated": updated,
            "failed": failures,
            "simulated_users": simulated,
            "total": len(rows),
            "run_at": datetime.now().isoformat(),
        }

    def auto_review_from_transactions(
        self,
        user_id: int,
        code: str,
        *,
        trade_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build one lightweight review record from latest decision + today's trade execution.

        This gives users an automatic review baseline. It intentionally uses neutral
        return/drawdown placeholders and can be refined later with realized outcomes.
        """
        normalized_code = normalize_fund_code(code)
        if not normalized_code:
            return {"created": False, "reason": "invalid_code"}

        target_date = trade_date or datetime.now().strftime("%Y-%m-%d")
        latest = get_latest_recommendation_decision(user_id, normalized_code)
        if not latest:
            return {"created": False, "reason": "no_decision"}

        # Avoid duplicate auto-review for the same date.
        recent_reviews = get_fund_review_records(
            user_id=user_id,
            fund_code=normalized_code,
            limit=30,
        )
        for row in recent_reviews:
            row_trade_date = str(row.get("trade_date") or "")
            review_payload = row.get("review") or {}
            if row_trade_date == target_date and review_payload.get("market_state") == "auto":
                return {"created": False, "reason": "already_exists", "review_id": row.get("id")}

        conn = get_db_connection()
        tx_row = conn.execute(
            """
            SELECT SUM(COALESCE(total_amount, 0) + COALESCE(fees, 0)) AS executed_amount
            FROM transactions
            WHERE user_id = ?
              AND asset_type = 'fund'
              AND asset_code = ?
              AND transaction_type IN ('buy', 'transfer_in')
              AND date(transaction_date) = date(?)
            """,
            (user_id, normalized_code, target_date),
        ).fetchone()
        conn.close()

        executed_amount = round(_safe_float((tx_row["executed_amount"] if tx_row else 0.0), 0.0) or 0.0, 2)
        if executed_amount <= 0:
            return {"created": False, "reason": "no_buy_transactions"}

        decision = latest.get("decision") or {}
        suggested_amount = _safe_float(decision.get("suggested_amount"), 0.0) or 0.0
        followed_plan = True
        if suggested_amount > 0:
            drift = abs(executed_amount - suggested_amount) / max(suggested_amount, 1.0)
            followed_plan = drift <= 0.4

        review = self.review_decision(
            user_id,
            code=normalized_code,
            decision_id=latest.get("id"),
            trade_date=target_date,
            actual_return_pct=0.0,
            max_drawdown_pct=0.0,
            executed_amount=executed_amount,
            followed_plan=followed_plan,
            market_state="auto",
            reflection="由交易记录自动生成的复盘基线，待后续收益数据补全后可二次修订。",
            strategy_version="auto",
        )
        return {
            "created": True,
            "review_id": review.get("review_id"),
            "case_id": review.get("case_id"),
            "trade_date": target_date,
            "executed_amount": executed_amount,
        }

    def get_latest_report(self, user_id: int, code: str) -> Optional[Dict[str, Any]]:
        """Return latest stored decision report."""
        return get_latest_recommendation_decision(user_id, normalize_fund_code(code))

    def review_decision(
        self,
        user_id: int,
        *,
        code: str,
        actual_return_pct: float,
        max_drawdown_pct: float,
        trade_date: Optional[str] = None,
        executed_amount: Optional[float] = None,
        followed_plan: bool = True,
        market_state: Optional[str] = None,
        reflection: Optional[str] = None,
        decision_id: Optional[int] = None,
        strategy_version: str = "p1",
    ) -> Dict[str, Any]:
        """P2 review scoring with case-library persistence."""
        normalized_code = normalize_fund_code(code)
        if not normalized_code:
            raise ValueError("基金代码无效")

        record = (
            get_recommendation_decision_by_id(user_id, int(decision_id))
            if decision_id is not None
            else get_latest_recommendation_decision(user_id, normalized_code)
        )
        if not record:
            raise ValueError("未找到可复盘的研究决策")

        decision = record.get("decision") or {}
        action = str(decision.get("action", "hold"))
        suggested_amount = _safe_float(decision.get("suggested_amount"), 0.0) or 0.0
        constraints = decision.get("user_constraints") or {}
        drawdown_tolerance = _safe_float(
            constraints.get("max_drawdown_tolerance"),
            self.MAX_DRAWDOWN_ALLOWED,
        ) or self.MAX_DRAWDOWN_ALLOWED
        confidence = _safe_float(decision.get("confidence"), 0.5) or 0.5

        # 1) Timing score
        if action == "add":
            timing_score = 80.0 if actual_return_pct >= 0 else 35.0
            timing_score += min(15.0, max(-20.0, actual_return_pct * 0.8))
        elif action == "pause":
            timing_score = 80.0 if actual_return_pct <= 0 else 35.0
            timing_score += min(15.0, max(-20.0, -actual_return_pct * 0.8))
        else:  # hold
            timing_score = 75.0 if -2.0 <= actual_return_pct <= 2.0 else 58.0
            timing_score += min(8.0, max(-12.0, -abs(actual_return_pct) * 0.5))
        timing_score = round(_clamp(timing_score), 2)

        # 2) Position discipline vs suggested amount
        if executed_amount is None or suggested_amount <= 0:
            position_score = 70.0 if followed_plan else 55.0
        else:
            diff_ratio = abs(float(executed_amount) - suggested_amount) / max(suggested_amount, 1.0)
            position_score = _clamp(100 - diff_ratio * 90, 15, 100)
            if not followed_plan:
                position_score = _clamp(position_score - 15, 0, 100)
        position_score = round(position_score, 2)

        # 3) Risk control score (realized drawdown vs tolerance)
        if max_drawdown_pct <= drawdown_tolerance:
            risk_score = 92.0 - (max_drawdown_pct / max(drawdown_tolerance, 1.0)) * 25
        else:
            exceed = max_drawdown_pct - drawdown_tolerance
            risk_score = 60.0 - exceed * 2.2
        if action == "pause" and max_drawdown_pct > 0:
            risk_score += 5.0
        risk_score = round(_clamp(risk_score), 2)

        # 4) Plan consistency score
        discipline_score = 88.0 if followed_plan else 52.0
        if executed_amount is not None and suggested_amount > 0:
            drift = abs(float(executed_amount) - suggested_amount) / max(suggested_amount, 1.0)
            discipline_score -= min(22.0, drift * 30)
        discipline_score = round(_clamp(discipline_score), 2)

        composite_score = round(
            (timing_score + position_score + risk_score + discipline_score) / 4.0,
            2,
        )
        if composite_score >= 75:
            outcome = "success"
        elif composite_score >= 55:
            outcome = "neutral"
        else:
            outcome = "failure"

        decision_trade_date = (
            trade_date
            or decision.get("trade_date")
            or record.get("trade_date")
            or self._current_trade_date(db_format=True)
        )
        review_payload = {
            "decision_id": record.get("id"),
            "decision_action": action,
            "decision_confidence": confidence,
            "decision_trade_date": decision.get("trade_date"),
            "actual_return_pct": float(actual_return_pct),
            "max_drawdown_pct": float(max_drawdown_pct),
            "executed_amount": executed_amount,
            "suggested_amount": suggested_amount,
            "followed_plan": bool(followed_plan),
            "market_state": market_state,
            "reflection": reflection,
            "outcome": outcome,
            "composite_score": composite_score,
        }
        review_id = save_fund_review_record(
            user_id=user_id,
            fund_code=normalized_code,
            trade_date=decision_trade_date,
            timing_score=timing_score,
            position_score=position_score,
            risk_score=risk_score,
            discipline_score=discipline_score,
            review=review_payload,
        )

        tags = [action, outcome, f"confidence_{self._confidence_band(confidence)}"]
        if market_state:
            tags.append(f"market_{market_state}")
        case_summary = (
            f"{normalized_code} 决策动作={action}，复盘结果={outcome}，"
            f"收益={actual_return_pct:.2f}%，最大回撤={max_drawdown_pct:.2f}%。"
        )
        case_id = save_case_library_entry(
            user_id=user_id,
            fund_code=normalized_code,
            trade_date=decision_trade_date,
            outcome=outcome,
            market_state=market_state,
            strategy_version=strategy_version,
            summary=case_summary,
            tags=tags,
            payload={
                "decision": decision,
                "review": review_payload,
                "scores": {
                    "timing": timing_score,
                    "position": position_score,
                    "risk": risk_score,
                    "discipline": discipline_score,
                    "composite": composite_score,
                },
            },
            decision_id=record.get("id"),
            review_id=review_id,
        )

        return {
            "review_id": review_id,
            "case_id": case_id,
            "fund_code": normalized_code,
            "trade_date": decision_trade_date,
            "outcome": outcome,
            "scores": {
                "timing": timing_score,
                "position": position_score,
                "risk": risk_score,
                "discipline": discipline_score,
                "composite": composite_score,
            },
            "review": review_payload,
        }

    def get_review_dashboard(
        self,
        user_id: int,
        *,
        fund_code: Optional[str] = None,
        window: int = 20,
    ) -> Dict[str, Any]:
        """Aggregate review stats and produce simple rule-tuning suggestions."""
        rows = get_fund_review_records(
            user_id=user_id,
            fund_code=normalize_fund_code(fund_code) if fund_code else None,
            limit=max(5, min(window, 200)),
        )
        if not rows:
            return {
                "count": 0,
                "averages": {},
                "outcome_distribution": {"success": 0, "neutral": 0, "failure": 0},
                "suggestions": [
                    "暂无复盘样本。建议先累计至少5次记录，再查看参数优化建议。"
                ],
                "rows": [],
            }

        def _avg(key: str) -> float:
            values = [_safe_float(item.get(key), 0.0) or 0.0 for item in rows]
            return round(sum(values) / max(len(values), 1), 2)

        outcome_distribution = {"success": 0, "neutral": 0, "failure": 0}
        for row in rows:
            outcome = str((row.get("review") or {}).get("outcome", "neutral"))
            if outcome not in outcome_distribution:
                outcome = "neutral"
            outcome_distribution[outcome] += 1

        avg_timing = _avg("timing_score")
        avg_position = _avg("position_score")
        avg_risk = _avg("risk_score")
        avg_discipline = _avg("discipline_score")
        avg_composite = round((avg_timing + avg_position + avg_risk + avg_discipline) / 4.0, 2)

        suggestions: List[str] = []
        if avg_timing < 60:
            suggestions.append("择时得分偏低：建议提高加仓门槛，优先评分>=70后再增强定投。")
        if avg_position < 65:
            suggestions.append("仓位纪律偏弱：建议收紧单日上限或降低增强系数。")
        if avg_risk < 65:
            suggestions.append("回撤控制不足：建议下调可容忍回撤阈值并降低战术增强触发频率。")
        if avg_discipline < 70:
            suggestions.append("计划一致性不足：建议先采用固定金额策略，减少临时改动。")
        success_rate = outcome_distribution["success"] / max(len(rows), 1)
        if success_rate < 0.4:
            suggestions.append("成功样本占比较低：建议先缩小候选池到高质量指数基金并延长观察窗口。")
        if not suggestions:
            suggestions.append("当前参数表现稳定，可小步迭代增强触发阈值并持续监控复盘得分。")

        return {
            "count": len(rows),
            "averages": {
                "timing": avg_timing,
                "position": avg_position,
                "risk": avg_risk,
                "discipline": avg_discipline,
                "composite": avg_composite,
            },
            "outcome_distribution": outcome_distribution,
            "suggestions": suggestions,
            "rows": rows,
        }

    def get_case_library(
        self,
        user_id: int,
        *,
        fund_code: Optional[str] = None,
        outcome: Optional[str] = None,
        market_state: Optional[str] = None,
        strategy_version: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Search stored success/failure/reflection cases."""
        entries = get_case_library_entries(
            user_id=user_id,
            fund_code=normalize_fund_code(fund_code) if fund_code else None,
            outcome=outcome,
            market_state=market_state,
            strategy_version=strategy_version,
            limit=limit,
        )
        return {
            "count": len(entries),
            "filters": {
                "fund_code": normalize_fund_code(fund_code) if fund_code else None,
                "outcome": outcome,
                "market_state": market_state,
                "strategy_version": strategy_version,
                "limit": limit,
            },
            "cases": entries,
        }

    def _load_fund_basic_rows(self, codes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        where = ["status = 'L'"]
        params: List[Any] = []

        if codes:
            placeholders = ", ".join("?" for _ in codes)
            where.append(f"code IN ({placeholders})")
            params.extend(codes)

        rows = conn.execute(
            f"""
            SELECT ts_code, code, name, fund_type, invest_type, market, management,
                   found_date, m_fee, c_fee, benchmark
            FROM fund_basic
            WHERE {' AND '.join(where)}
            """,
            tuple(params),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def _load_tracked_funds(self, user_id: int) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT code, name, style
            FROM funds
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def _build_universe_item(self, row: Dict[str, Any], source: str) -> Dict[str, Any]:
        code = normalize_fund_code(row.get("code") or row.get("ts_code") or "")
        name = row.get("name") or code
        fund_type = row.get("fund_type") or row.get("style") or ""
        invest_type = row.get("invest_type")
        market = row.get("market")

        is_index = _contains_index_hint(name, fund_type, invest_type)
        is_etf = bool(str(market or "").upper() == "E" or "etf" in str(name).lower() or "etf" in str(fund_type).lower())
        is_linked = "联接" in str(name or "") or "联接" in str(fund_type or "")
        # Off-market focus: only open-end index-like funds are eligible for this workflow.
        is_dca_eligible = bool(is_index and str(market or "").upper() == "O")

        return {
            "code": code,
            "ts_code": row.get("ts_code"),
            "name": name,
            "fund_type": fund_type,
            "invest_type": invest_type,
            "market": market,
            "management": row.get("management"),
            "found_date": row.get("found_date"),
            "m_fee": _safe_float(row.get("m_fee")),
            "c_fee": _safe_float(row.get("c_fee")),
            "is_index_fund": is_index,
            "is_etf": is_etf,
            "is_linked": is_linked,
            "is_dca_eligible": is_dca_eligible,
            "status": "active",
            "metadata": {
                "source": source,
                "benchmark": row.get("benchmark"),
            },
        }

    def _is_universe_candidate_item(self, item: Dict[str, Any]) -> bool:
        """Hard entry rule for fund universe candidate pool."""
        if not item:
            return False

        if not bool(item.get("is_index_fund")):
            return False
        if not bool(item.get("is_dca_eligible")):
            return False

        fund_type_text = str(item.get("fund_type") or "").strip().lower()
        if fund_type_text in {"unknown", "unk", "na", "n/a", "null"}:
            return False

        name_text = str(item.get("name") or "").strip()
        code_text = str(item.get("code") or "").strip()
        if not name_text:
            return False
        if name_text == code_text and not fund_type_text:
            # Avoid code-only placeholders leaking into candidate pool.
            return False

        return True

    def _fetch_latest_factor_rows(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        if not codes:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        conn = get_db_connection()

        for chunk in _chunked(codes, 300):
            placeholders = ", ".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                WITH latest AS (
                    SELECT code, MAX(trade_date) AS latest_trade_date
                    FROM fund_factors_daily
                    WHERE code IN ({placeholders})
                    GROUP BY code
                )
                SELECT f.*
                FROM fund_factors_daily f
                JOIN latest l
                  ON f.code = l.code
                 AND f.trade_date = l.latest_trade_date
                """,
                tuple(chunk),
            ).fetchall()

            for row in rows:
                data = dict(row)
                result[data["code"]] = data

        conn.close()
        return result

    def _backfill_missing_factors(self, codes: List[str]) -> None:
        if not codes:
            return

        trade_date = self._current_trade_date()
        trade_date_db = self._current_trade_date(db_format=True)

        for code in codes[:40]:  # avoid runaway slow jobs
            try:
                factors = self._factor_engine.compute_factors(code, trade_date=trade_date, use_cache=True)
                if not factors:
                    continue
                factors["code"] = normalize_fund_code(code)
                factors["trade_date"] = trade_date_db
                upsert_fund_factors(factors)
            except Exception as exc:
                print(f"factor backfill failed for {code}: {exc}")

    def _build_scorecard(self, universe_item: Dict[str, Any], factors: Dict[str, Any]) -> Dict[str, Any]:
        found_date = _parse_date(universe_item.get("found_date"))
        age_days = (datetime.now() - found_date).days if found_date else None

        fund_size = _safe_float(factors.get("fund_size"))
        max_dd = _safe_float(factors.get("max_drawdown_1y"))
        sharpe_1y = _safe_float(factors.get("sharpe_1y"))
        volatility_60d = _safe_float(factors.get("volatility_60d"))
        return_1y = _safe_float(factors.get("return_1y"))

        hard_filter_reasons: List[str] = []
        if not universe_item.get("is_index_fund"):
            hard_filter_reasons.append("not_index_like")
        if not universe_item.get("is_dca_eligible"):
            hard_filter_reasons.append("not_dca_eligible")
        if age_days is not None and age_days < self.MIN_FOUND_DAYS:
            hard_filter_reasons.append(f"fund_too_new_lt_{self.MIN_FOUND_DAYS}d")
        if fund_size is not None and fund_size < self.MIN_FUND_SIZE_BN:
            hard_filter_reasons.append(f"fund_size_lt_{self.MIN_FUND_SIZE_BN}bn")
        if max_dd is not None and max_dd > self.MAX_DRAWDOWN_ALLOWED:
            hard_filter_reasons.append(f"max_drawdown_gt_{self.MAX_DRAWDOWN_ALLOWED}%")
        if not factors:
            hard_filter_reasons.append("missing_factor_data")

        hard_filter_pass = len(hard_filter_reasons) == 0

        tenure_years = _safe_float(factors.get("manager_tenure_years"))
        style_consistency = _safe_float(factors.get("style_consistency"))
        m_fee = _safe_float(universe_item.get("m_fee"))
        c_fee = _safe_float(universe_item.get("c_fee"))

        tenure_score = 60.0 if tenure_years is None else _clamp(35 + tenure_years * 10)
        if fund_size is None:
            size_score = 55.0
        elif 1.0 <= fund_size <= 50.0:
            size_score = 88.0
        elif fund_size < 1.0:
            size_score = _clamp(45 + fund_size * 35)
        else:
            size_score = _clamp(88 - (fund_size - 50.0) * 1.2)

        fee_total = None if m_fee is None and c_fee is None else (m_fee or 0.0) + (c_fee or 0.0)
        fee_score = 60.0 if fee_total is None else _clamp(100 - fee_total * 35)
        style_score = 58.0 if style_consistency is None else _clamp(style_consistency)

        quality_score = round(
            tenure_score * 0.30 + size_score * 0.25 + fee_score * 0.25 + style_score * 0.20,
            2,
        )

        sharpe_score = 50.0 if sharpe_1y is None else _clamp((sharpe_1y + 0.5) / 2.0 * 100)
        return_score = 50.0 if return_1y is None else _clamp((return_1y + 8) / 32 * 100)
        drawdown_score = 55.0 if max_dd is None else _clamp(100 - max_dd * 2)
        if volatility_60d is None:
            vol_score = 55.0
        else:
            vol_score = _clamp(100 - abs(volatility_60d - 18) * 4)

        risk_return_score = round(
            sharpe_score * 0.35 + return_score * 0.25 + drawdown_score * 0.25 + vol_score * 0.15,
            2,
        )

        ret_1m = _safe_float(factors.get("return_1m"))
        ret_3m = _safe_float(factors.get("return_3m"))
        valuation_base = 60.0
        if ret_3m is not None:
            if ret_3m <= -12:
                valuation_base = 90.0
            elif ret_3m <= -5:
                valuation_base = 78.0
            elif ret_3m >= 15:
                valuation_base = 30.0
            elif ret_3m >= 8:
                valuation_base = 42.0
        if ret_1m is not None:
            if ret_1m <= -4:
                valuation_base += 8
            elif ret_1m >= 8:
                valuation_base -= 10
        valuation_position_score = round(_clamp(valuation_base), 2)

        total_score = round(
            quality_score * 0.40 + risk_return_score * 0.40 + valuation_position_score * 0.20,
            2,
        )

        return {
            "total_score": total_score,
            "quality_score": quality_score,
            "risk_return_score": risk_return_score,
            "valuation_position_score": valuation_position_score,
            "hard_filter_pass": hard_filter_pass,
            "hard_filter_reasons": hard_filter_reasons,
            "factors": {
                "return_1w": _safe_float(factors.get("return_1w")),
                "return_1m": ret_1m,
                "return_3m": ret_3m,
                "return_1y": return_1y,
                "sharpe_1y": sharpe_1y,
                "sharpe_20d": _safe_float(factors.get("sharpe_20d")),
                "max_drawdown_1y": max_dd,
                "volatility_60d": volatility_60d,
                "manager_tenure_years": tenure_years,
                "fund_size": fund_size,
                "style_consistency": style_consistency,
            },
        }

    def _persist_score_snapshot(
        self,
        user_id: int,
        code: str,
        scorecard: Dict[str, Any],
        factors: Dict[str, Any],
    ) -> Tuple[int, int]:
        snapshot_payload = {
            "fund_code": code,
            "trade_date": scorecard.get("trade_date") or self._current_trade_date(db_format=True),
            "scorecard": scorecard,
            "factors": factors,
        }
        snapshot_hash = _snapshot_hash(snapshot_payload)
        trade_date = scorecard.get("trade_date") or self._current_trade_date(db_format=True)
        snapshot_id = save_fund_snapshot(
            user_id=user_id,
            fund_code=code,
            trade_date=trade_date,
            snapshot_hash=snapshot_hash,
            snapshot=snapshot_payload,
            source={"name": "fund_research_service", "version": "p0"},
        )
        scorecard_id = save_fund_scorecard(
            user_id=user_id,
            fund_code=code,
            trade_date=trade_date,
            snapshot_hash=snapshot_hash,
            scorecard=scorecard,
        )
        return snapshot_id, scorecard_id

    def _build_evidence(self, scorecard: Dict[str, Any], universe_item: Dict[str, Any]) -> List[Dict[str, Any]]:
        factors = scorecard.get("factors", {})
        evidence: List[Dict[str, Any]] = []
        for key, label in (
            ("return_1y", "近1年收益"),
            ("sharpe_1y", "近1年夏普"),
            ("max_drawdown_1y", "近1年最大回撤"),
            ("volatility_60d", "近60日波动率"),
            ("fund_size", "基金规模(亿)"),
            ("manager_tenure_years", "经理任期(年)"),
        ):
            value = factors.get(key)
            if value is not None:
                evidence.append(
                    {
                        "metric": label,
                        "value": value,
                        "source": "fund_factors_daily",
                        "timestamp": scorecard.get("trade_date"),
                    }
                )

        evidence.append(
            {
                "metric": "候选池约束",
                "value": "指数ETF/联接",
                "source": "fund_universe",
                "timestamp": universe_item.get("updated_at"),
            }
        )
        return evidence

    def _current_trade_date(self, db_format: bool = False) -> str:
        trade_date = get_latest_trade_date()
        if not trade_date:
            trade_date = get_fallback_trade_date()
        if db_format:
            return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        return trade_date
