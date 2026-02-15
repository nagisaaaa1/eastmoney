"""
Fund research endpoints.

Implements the P0 workflow:
- candidate pool governance
- scoring and ranking
- standardized DCA recommendation output
- stale-while-revalidate report fetch
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.core.utils import sanitize_for_json
from app.models.auth import User
from src.analysis.fund_research import FundResearchService
from src.storage.fund_research_db import (
    get_fund_universe,
    get_fund_universe_count,
    get_universe_last_updated,
)

router = APIRouter(prefix="/api/research/fund", tags=["Fund Research"])

_service = FundResearchService()
_report_refresh_lock = threading.Lock()
_report_refreshing: Dict[Tuple[int, str], bool] = {}
_REPORT_CACHE_TTL_SECONDS = 300


class UniverseSyncRequest(BaseModel):
    full_sync: bool = False
    codes: Optional[List[str]] = None


class FundScoreRequest(BaseModel):
    codes: Optional[List[str]] = None
    top_n: int = Field(default=20, ge=1, le=200)
    min_score: float = Field(default=0.0, ge=0.0, le=100.0)
    refresh_missing: bool = False


class FundRecommendRequest(BaseModel):
    code: str
    base_amount: float = Field(default=30.0, ge=0.0)
    available_cash: Optional[float] = Field(default=None, ge=0.0)
    max_single_day_amount: Optional[float] = Field(default=None, ge=0.0)
    existing_dca_daily_amount: Optional[float] = Field(default=None, ge=0.0)
    max_drawdown_tolerance: Optional[float] = Field(default=None, ge=0.0, le=45.0)
    tactical_boost: Optional[bool] = None
    strict_tactical: bool = True
    analysis_mode: str = Field(default="quick")
    use_global_cash: bool = True
    use_auto_dca: bool = True
    refresh_missing: bool = False


class FundReviewRequest(BaseModel):
    code: str
    decision_id: Optional[int] = Field(default=None, ge=1)
    trade_date: Optional[str] = None
    actual_return_pct: float
    max_drawdown_pct: float = Field(ge=0.0)
    executed_amount: Optional[float] = Field(default=None, ge=0.0)
    followed_plan: bool = True
    market_state: Optional[str] = None
    reflection: Optional[str] = None
    strategy_version: str = "p1"


class FundBatchRecommendRequest(BaseModel):
    codes: Optional[List[str]] = None
    top_n: int = Field(default=10, ge=1, le=50)
    source: str = "ai_top"
    base_amount: float = Field(default=30.0, ge=0.0)
    available_cash: Optional[float] = Field(default=None, ge=0.0)
    max_single_day_amount: Optional[float] = Field(default=None, ge=0.0)
    existing_dca_daily_amount: Optional[float] = Field(default=None, ge=0.0)
    max_drawdown_tolerance: Optional[float] = Field(default=None, ge=0.0, le=45.0)
    tactical_boost: Optional[bool] = None
    strict_tactical: bool = True
    analysis_mode: str = Field(default="quick")
    use_global_cash: bool = True
    use_auto_dca: bool = True
    refresh_missing: bool = False
    auto_start: bool = True
    max_workers: int = Field(default=3, ge=1, le=6)


class FundSelectionRequest(BaseModel):
    top_n: int = Field(default=10, ge=1, le=50)
    candidate_limit: int = Field(default=30, ge=5, le=120)
    min_score: float = Field(default=0.0, ge=0.0, le=100.0)
    refresh_missing: bool = True
    analysis_mode: str = Field(default="deep")


class DCAPlanCreateRequest(BaseModel):
    code: str
    amount_per_cycle: float = Field(gt=0)
    frequency: str = Field(default="daily")
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    execution_weekday: Optional[int] = Field(default=None, ge=0, le=6)
    execution_day: Optional[int] = Field(default=None, ge=1, le=28)
    auto_adjust: bool = True
    max_daily_amount: Optional[float] = Field(default=None, ge=0.0)
    fund_name: Optional[str] = None
    notes: Optional[str] = None


class DCAPlanUpdateRequest(BaseModel):
    action: Optional[str] = Field(default=None, pattern="^(pause|resume|stop)$")
    amount_per_cycle: Optional[float] = Field(default=None, gt=0)
    frequency: Optional[str] = None
    end_date: Optional[str] = None
    execution_weekday: Optional[int] = Field(default=None, ge=0, le=6)
    execution_day: Optional[int] = Field(default=None, ge=1, le=28)
    auto_adjust: Optional[bool] = None
    max_daily_amount: Optional[float] = Field(default=None, ge=0.0)
    notes: Optional[str] = None


class DCASimulateRequest(BaseModel):
    target_date: Optional[str] = None
    max_plans: int = Field(default=20, ge=1, le=500)


def _parse_created_at(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _is_refreshing(user_id: int, code: str) -> bool:
    key = (user_id, code)
    with _report_refresh_lock:
        return _report_refreshing.get(key, False)


def _mark_refreshing(user_id: int, code: str) -> bool:
    key = (user_id, code)
    with _report_refresh_lock:
        if _report_refreshing.get(key):
            return False
        _report_refreshing[key] = True
        return True


def _clear_refreshing(user_id: int, code: str) -> None:
    key = (user_id, code)
    with _report_refresh_lock:
        _report_refreshing[key] = False


async def _refresh_report_task(
    user_id: int,
    code: str,
    base_amount: float,
    *,
    analysis_mode: str = "quick",
    tactical_boost: Optional[bool] = None,
    available_cash: Optional[float] = None,
    max_single_day_amount: Optional[float] = None,
    max_drawdown_tolerance: Optional[float] = None,
    existing_dca_daily_amount: Optional[float] = None,
    use_global_cash: bool = True,
    use_auto_dca: bool = True,
) -> None:
    try:
        await asyncio.to_thread(
            _service.recommend_fund,
            user_id,
            code=code,
            base_amount=base_amount,
            available_cash=available_cash,
            max_single_day_amount=max_single_day_amount,
            tactical_boost=tactical_boost,
            strict_tactical=tactical_boost if tactical_boost is not None else True,
            analysis_mode=analysis_mode,
            max_drawdown_tolerance=max_drawdown_tolerance,
            existing_dca_daily_amount=existing_dca_daily_amount,
            use_global_cash=use_global_cash,
            use_auto_dca=use_auto_dca,
            refresh_missing=False,
        )
    except Exception as exc:
        print(f"Background report refresh failed ({code}): {exc}")
    finally:
        _clear_refreshing(user_id, code)


@router.get("/universe")
async def get_research_universe(
    active_only: bool = True,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
):
    """Get normalized candidate pool used by research workflow."""
    if get_fund_universe_count(current_user.id, active_only=True) == 0:
        await asyncio.to_thread(_service.sync_universe, current_user.id, full_sync=True)

    items = await asyncio.to_thread(
        get_fund_universe,
        current_user.id,
        active_only,
        None,
        max(1, min(limit, 2000)),
    )

    return {
        "policy": {
            "candidate_pool_required": True,
            "scope": "index_off_market_open_end",
            "dca_mode": "medium_long_term",
        },
        "count": len(items),
        "active_only": active_only,
        "last_updated": get_universe_last_updated(current_user.id),
        "items": sanitize_for_json(items),
    }


@router.post("/universe/sync")
async def sync_research_universe(
    request: UniverseSyncRequest,
    current_user: User = Depends(get_current_user),
):
    """Sync candidate pool from market metadata and tracked funds."""
    result = await asyncio.to_thread(
        _service.sync_universe,
        current_user.id,
        full_sync=request.full_sync,
        codes=request.codes,
    )
    return sanitize_for_json(result)


@router.post("/score")
async def score_research_funds(
    request: FundScoreRequest,
    current_user: User = Depends(get_current_user),
):
    """Score funds from candidate pool and return ranked results."""
    result = await asyncio.to_thread(
        _service.score_funds,
        current_user.id,
        codes=request.codes,
        top_n=request.top_n,
        min_score=request.min_score,
        refresh_missing=request.refresh_missing,
    )
    return sanitize_for_json(result)


@router.post("/select")
async def run_ai_selection(
    request: FundSelectionRequest,
    current_user: User = Depends(get_current_user),
):
    """Run AI selection system on candidate pool and return curated picks."""
    try:
        result = await asyncio.to_thread(
            _service.run_ai_selection,
            current_user.id,
            top_n=request.top_n,
            candidate_limit=request.candidate_limit,
            min_score=request.min_score,
            refresh_missing=request.refresh_missing,
            analysis_mode=request.analysis_mode,
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/constraints/suggestions")
async def get_constraint_suggestions(current_user: User = Depends(get_current_user)):
    """Suggest personalized constraints for fund selection/decision."""
    try:
        result = await asyncio.to_thread(
            _service.suggest_personal_constraints,
            current_user.id,
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/recommend")
async def recommend_research_fund(
    request: FundRecommendRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate standardized DCA recommendation for one fund."""
    try:
        result = await asyncio.to_thread(
            _service.recommend_fund,
            current_user.id,
            code=request.code,
            base_amount=request.base_amount,
            available_cash=request.available_cash,
            max_single_day_amount=request.max_single_day_amount,
            existing_dca_daily_amount=request.existing_dca_daily_amount,
            max_drawdown_tolerance=request.max_drawdown_tolerance,
            tactical_boost=request.tactical_boost,
            strict_tactical=request.strict_tactical,
            analysis_mode=request.analysis_mode,
            use_global_cash=request.use_global_cash,
            use_auto_dca=request.use_auto_dca,
            refresh_missing=request.refresh_missing,
        )
        return sanitize_for_json(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


async def _run_batch_job_background(user_id: int, job_id: int, max_workers: int) -> None:
    try:
        await asyncio.to_thread(
            _service.run_batch_job,
            user_id,
            job_id,
            max_workers=max_workers,
        )
    except Exception as exc:
        print(f"Batch job background run failed (job={job_id}): {exc}")


@router.post("/batch/recommend")
async def create_batch_research_job(
    request: FundBatchRecommendRequest,
    current_user: User = Depends(get_current_user),
):
    """Create one batch recommendation job and optionally start it in background."""
    try:
        result = await asyncio.to_thread(
            _service.create_batch_recommendation_job,
            current_user.id,
            codes=request.codes,
            top_n=request.top_n,
            source=request.source,
            base_amount=request.base_amount,
            available_cash=request.available_cash,
            max_single_day_amount=request.max_single_day_amount,
            existing_dca_daily_amount=request.existing_dca_daily_amount,
            max_drawdown_tolerance=request.max_drawdown_tolerance,
            tactical_boost=request.tactical_boost,
            strict_tactical=request.strict_tactical,
            analysis_mode=request.analysis_mode,
            use_global_cash=request.use_global_cash,
            use_auto_dca=request.use_auto_dca,
            refresh_missing=request.refresh_missing,
        )
        job_id = int(result.get("job_id"))
        if request.auto_start:
            asyncio.create_task(
                _run_batch_job_background(current_user.id, job_id, request.max_workers)
            )
        return sanitize_for_json(
            {
                **result,
                "auto_start": request.auto_start,
                "max_workers": request.max_workers,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/batch/jobs")
async def list_batch_research_jobs(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
):
    """List latest batch jobs."""
    try:
        result = await asyncio.to_thread(
            _service.list_batch_history,
            current_user.id,
            max(1, min(limit, 100)),
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/batch/jobs/{job_id}")
async def get_batch_research_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
):
    """Get one batch job detail + progress."""
    try:
        result = await asyncio.to_thread(
            _service.get_batch_job_status,
            current_user.id,
            int(job_id),
        )
        return sanitize_for_json(result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/batch/jobs/{job_id}/retry-failures")
async def retry_failed_batch_research_job(
    job_id: int,
    auto_start: bool = True,
    max_workers: int = 3,
    current_user: User = Depends(get_current_user),
):
    """Retry failed items in one existing batch job."""
    try:
        result = await asyncio.to_thread(
            _service.retry_failed_batch_job,
            current_user.id,
            int(job_id),
        )
        if auto_start:
            asyncio.create_task(
                _run_batch_job_background(
                    current_user.id,
                    int(job_id),
                    max(1, min(max_workers, 6)),
                )
            )
        return sanitize_for_json(
            {
                **result,
                "auto_start": auto_start,
                "max_workers": max(1, min(max_workers, 6)),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/batch/jobs/{job_id}/cancel")
async def cancel_batch_research_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
):
    """Cancel one batch job."""
    try:
        result = await asyncio.to_thread(
            _service.cancel_batch_job,
            current_user.id,
            int(job_id),
        )
        return sanitize_for_json(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/context/global")
async def get_research_global_context(current_user: User = Depends(get_current_user)):
    """Return global cash/portfolio context used by research recommendations."""
    try:
        result = await asyncio.to_thread(_service.get_global_context, current_user.id)
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/context/fund/{code}")
async def get_research_fund_context(
    code: str,
    current_user: User = Depends(get_current_user),
):
    """Return one fund's decision context snapshot."""
    try:
        result = await asyncio.to_thread(_service.get_fund_context, current_user.id, code)
        return sanitize_for_json(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/review")
async def submit_research_review(
    request: FundReviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Submit one review record and write case-library sample."""
    try:
        result = await asyncio.to_thread(
            _service.review_decision,
            current_user.id,
            code=request.code,
            actual_return_pct=request.actual_return_pct,
            max_drawdown_pct=request.max_drawdown_pct,
            trade_date=request.trade_date,
            executed_amount=request.executed_amount,
            followed_plan=request.followed_plan,
            market_state=request.market_state,
            reflection=request.reflection,
            decision_id=request.decision_id,
            strategy_version=request.strategy_version,
        )
        return sanitize_for_json(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/review/summary")
async def get_review_summary(
    code: Optional[str] = None,
    window: int = 20,
    current_user: User = Depends(get_current_user),
):
    """Get review score aggregation and rule optimization suggestions."""
    try:
        result = await asyncio.to_thread(
            _service.get_review_dashboard,
            current_user.id,
            fund_code=code,
            window=max(5, min(window, 200)),
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/cases")
async def get_research_cases(
    code: Optional[str] = None,
    outcome: Optional[str] = None,
    market_state: Optional[str] = None,
    strategy_version: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """Query case library by fund / market state / strategy version."""
    try:
        result = await asyncio.to_thread(
            _service.get_case_library,
            current_user.id,
            fund_code=code,
            outcome=outcome,
            market_state=market_state,
            strategy_version=strategy_version,
            limit=max(1, min(limit, 500)),
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/dca/plans")
async def list_dca_plans_api(
    status: Optional[str] = None,
    code: Optional[str] = None,
    limit: int = 200,
    current_user: User = Depends(get_current_user),
):
    """List DCA/SIP plans for current user."""
    try:
        result = await asyncio.to_thread(
            _service.list_dca_plan_configs,
            current_user.id,
            status=status,
            fund_code=code,
            limit=max(1, min(limit, 500)),
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/dca/plans")
async def create_dca_plan_api(
    request: DCAPlanCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Create one DCA/SIP plan."""
    try:
        result = await asyncio.to_thread(
            _service.create_dca_plan_config,
            current_user.id,
            code=request.code,
            amount_per_cycle=request.amount_per_cycle,
            frequency=request.frequency,
            start_date=request.start_date,
            end_date=request.end_date,
            execution_weekday=request.execution_weekday,
            execution_day=request.execution_day,
            auto_adjust=request.auto_adjust,
            max_daily_amount=request.max_daily_amount,
            fund_name=request.fund_name,
            notes=request.notes,
        )
        return sanitize_for_json(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/dca/plans/{plan_id}")
async def update_dca_plan_api(
    plan_id: int,
    request: DCAPlanUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Update/pause/resume/stop one DCA/SIP plan."""
    try:
        payload = request.dict(exclude_none=True)
        result = await asyncio.to_thread(
            _service.update_dca_plan_config,
            current_user.id,
            int(plan_id),
            updates=payload,
        )
        return sanitize_for_json(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/dca/runs")
async def list_dca_plan_runs_api(
    plan_id: Optional[int] = None,
    code: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
):
    """List DCA/SIP plan simulation/execution history."""
    try:
        result = await asyncio.to_thread(
            _service.get_dca_plan_runs,
            current_user.id,
            plan_id=plan_id,
            fund_code=code,
            limit=max(1, min(limit, 500)),
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/dca/simulate")
async def simulate_dca_today_api(
    request: DCASimulateRequest,
    current_user: User = Depends(get_current_user),
):
    """Simulate due DCA/SIP plans and feed decision engine."""
    try:
        result = await asyncio.to_thread(
            _service.simulate_due_dca_plans,
            current_user.id,
            target_date=request.target_date,
            max_plans=request.max_plans,
        )
        return sanitize_for_json(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/report/{code}")
async def get_research_report(
    code: str,
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
):
    """
    Return latest decision report.

    Stale-while-revalidate behavior:
    - return cached report immediately
    - if stale, trigger background refresh
    - optional `refresh=true` for synchronous refresh
    """
    normalized_code = "".join(ch for ch in str(code) if ch.isdigit())[:6]
    if not normalized_code:
        raise HTTPException(status_code=400, detail="Invalid fund code")

    latest = await asyncio.to_thread(_service.get_latest_report, current_user.id, normalized_code)

    if refresh:
        base_amount = 30.0
        analysis_mode = "quick"
        tactical_boost: Optional[bool] = None
        available_cash: Optional[float] = None
        max_single_day_amount: Optional[float] = None
        max_drawdown_tolerance: Optional[float] = None
        existing_dca_daily_amount: Optional[float] = None
        use_global_cash = True
        use_auto_dca = True
        if latest and latest.get("decision"):
            try:
                latest_decision = latest["decision"]
                base_amount = float(latest_decision.get("base_amount", base_amount))
                analysis_mode = str(latest_decision.get("analysis_mode", analysis_mode))
                tactical_boost = latest_decision.get("tactical_boost_enabled")
                constraints = latest_decision.get("user_constraints") or {}
                available_cash = constraints.get("available_cash")
                max_single_day_amount = constraints.get("max_single_day_amount")
                max_drawdown_tolerance = constraints.get("max_drawdown_tolerance")
                existing_dca_daily_amount = constraints.get("existing_dca_daily_amount")
                use_global_cash = bool(constraints.get("use_global_cash", True))
                use_auto_dca = bool(constraints.get("use_auto_dca", True))
            except Exception:
                pass
        refreshed = await asyncio.to_thread(
            _service.recommend_fund,
            current_user.id,
            code=normalized_code,
            base_amount=base_amount,
            available_cash=available_cash,
            max_single_day_amount=max_single_day_amount,
            tactical_boost=tactical_boost,
            strict_tactical=tactical_boost if tactical_boost is not None else True,
            analysis_mode=analysis_mode,
            max_drawdown_tolerance=max_drawdown_tolerance,
            existing_dca_daily_amount=existing_dca_daily_amount,
            use_global_cash=use_global_cash,
            use_auto_dca=use_auto_dca,
            refresh_missing=True,
        )
        return {
            "available": True,
            "source": "fresh",
            "report": sanitize_for_json(refreshed),
            "cache": {
                "ttl_seconds": _REPORT_CACHE_TTL_SECONDS,
                "refreshing": False,
            },
        }

    if not latest:
        return {
            "available": False,
            "message": "No report yet. Call POST /api/research/fund/recommend first.",
            "cache": {
                "ttl_seconds": _REPORT_CACHE_TTL_SECONDS,
                "refreshing": False,
            },
        }

    created_at = _parse_created_at(latest.get("created_at"))
    age_seconds = int((datetime.now() - created_at).total_seconds()) if created_at else _REPORT_CACHE_TTL_SECONDS + 1
    stale = age_seconds > _REPORT_CACHE_TTL_SECONDS
    refreshing = _is_refreshing(current_user.id, normalized_code)

    if stale and not refreshing and _mark_refreshing(current_user.id, normalized_code):
        base_amount = 30.0
        analysis_mode = "quick"
        tactical_boost: Optional[bool] = None
        available_cash: Optional[float] = None
        max_single_day_amount: Optional[float] = None
        max_drawdown_tolerance: Optional[float] = None
        existing_dca_daily_amount: Optional[float] = None
        use_global_cash = True
        use_auto_dca = True
        try:
            cached_decision = latest.get("decision") or {}
            base_amount = float(cached_decision.get("base_amount", base_amount))
            analysis_mode = str(cached_decision.get("analysis_mode", analysis_mode))
            tactical_boost = cached_decision.get("tactical_boost_enabled")
            constraints = cached_decision.get("user_constraints") or {}
            available_cash = constraints.get("available_cash")
            max_single_day_amount = constraints.get("max_single_day_amount")
            max_drawdown_tolerance = constraints.get("max_drawdown_tolerance")
            existing_dca_daily_amount = constraints.get("existing_dca_daily_amount")
            use_global_cash = bool(constraints.get("use_global_cash", True))
            use_auto_dca = bool(constraints.get("use_auto_dca", True))
        except Exception:
            pass
        asyncio.create_task(
            _refresh_report_task(
                current_user.id,
                normalized_code,
                base_amount,
                analysis_mode=analysis_mode,
                tactical_boost=tactical_boost,
                available_cash=available_cash,
                max_single_day_amount=max_single_day_amount,
                max_drawdown_tolerance=max_drawdown_tolerance,
                existing_dca_daily_amount=existing_dca_daily_amount,
                use_global_cash=use_global_cash,
                use_auto_dca=use_auto_dca,
            )
        )
        refreshing = True

    return {
        "available": True,
        "source": "cache",
        "report": sanitize_for_json(latest.get("decision") or latest),
        "cache": {
            "ttl_seconds": _REPORT_CACHE_TTL_SECONDS,
            "age_seconds": age_seconds,
            "stale": stale,
            "refreshing": refreshing,
        },
    }
