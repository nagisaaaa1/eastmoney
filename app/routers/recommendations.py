"""
Recommendations endpoints.
V2 quantitative factor-based recommendations engine.
"""
from datetime import datetime
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.models.auth import User
from app.core.dependencies import get_current_user
from app.core.utils import sanitize_for_json

router = APIRouter(prefix="/api/recommend", tags=["Recommendations"])


class RecommendationRequest(BaseModel):
    mode: str = "all"  # "short", "long", "all"
    stock_limit: int = 20
    fund_limit: int = 20
    use_explanations: bool = True
    explanation_mode: str = "quick"  # "quick" or "deep"


@router.post("/generate")
async def generate_recommendations(
    request: RecommendationRequest = None,
    current_user: User = Depends(get_current_user)
):
    """
    Generate AI investment recommendations using quantitative factor-based engine.

    - mode: "short" (7+ days), "long" (3+ months), or "all"
    - stock_limit: Maximum number of stocks to recommend
    - fund_limit: Maximum number of funds to recommend
    - use_explanations: Whether to use LLM to generate explanations
    """
    import time as _time
    import asyncio
    request_start = _time.time()
    print(f"[Router] /generate endpoint called at {request_start}")

    mode = request.mode if request else "all"
    stock_limit = request.stock_limit if request else 20
    fund_limit = request.fund_limit if request else 20
    use_explanations = request.use_explanations if request else True
    explanation_mode = request.explanation_mode if request else "quick"

    if mode not in ["short", "long", "all"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'short', 'long', or 'all'.")

    try:
        from src.analysis.recommendation import RecommendationEngine
        from src.storage.db import get_user_preferences

        # Load user preferences
        user_preferences = None
        try:
            prefs_data = get_user_preferences(current_user.id)
            if prefs_data and prefs_data.get('preferences'):
                user_preferences = prefs_data.get('preferences')
        except Exception:
            pass

        # Define synchronous engine work
        def run_engine():
            engine = RecommendationEngine(use_llm_explanations=use_explanations)
            return engine.generate_recommendations(
                mode=mode,
                stock_limit=stock_limit,
                fund_limit=fund_limit,
                user_preferences=user_preferences,
                explanation_mode=explanation_mode,
            )

        # Run engine in thread pool to avoid blocking event loop
        print(f"[Router] Starting engine in thread pool...")
        engine_start = _time.time()
        results = await asyncio.to_thread(run_engine)
        print(f"[Router] Engine completed in {_time.time() - engine_start:.2f}s")

        # Sanitize results
        print(f"[Router] Sanitizing results...")
        sanitize_start = _time.time()
        results = sanitize_for_json(results)
        print(f"[Router] Sanitize completed in {_time.time() - sanitize_start:.2f}s")

        # Save to database for persistence (also in thread pool)
        print(f"[Router] Saving to database...")
        save_start = _time.time()
        from src.storage.db import save_recommendation_report

        def save_to_db():
            save_recommendation_report({
                "mode": mode,
                "recommendations_json": results,
                "market_context": results.get("metadata", {})
            }, user_id=current_user.id)

        await asyncio.to_thread(save_to_db)
        print(f"[Router] Database save completed in {_time.time() - save_start:.2f}s")

        print(f"[Router] Total request time: {_time.time() - request_start:.2f}s")
        return {
            "status": "completed",
            "result": results
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stocks/short")
async def get_short_term_stock_recommendations(
    limit: int = 20,
    min_score: float = 60,
    current_user: User = Depends(get_current_user)
):
    """Get short-term stock recommendations (7+ days)."""
    try:
        from src.analysis.recommendation.stock_engine import StockRecommendationEngine
        from src.data_sources.tushare_client import get_latest_trade_date

        engine = StockRecommendationEngine()
        trade_date = get_latest_trade_date()

        recommendations = engine.get_recommendations(
            strategy='short_term',
            top_n=limit,
            trade_date=trade_date,
            min_score=min_score
        )

        return {
            "recommendations": sanitize_for_json(recommendations),
            "trade_date": trade_date,
            "engine_version": "v2"
        }

    except Exception as e:
        print(f"Error: {e}")
        return {"recommendations": [], "error": str(e)}


@router.get("/stocks/long")
async def get_long_term_stock_recommendations(
    limit: int = 20,
    min_score: float = 60,
    current_user: User = Depends(get_current_user)
):
    """Get long-term stock recommendations (3+ months)."""
    try:
        from src.analysis.recommendation.stock_engine import StockRecommendationEngine
        from src.data_sources.tushare_client import get_latest_trade_date

        engine = StockRecommendationEngine()
        trade_date = get_latest_trade_date()

        recommendations = engine.get_recommendations(
            strategy='long_term',
            top_n=limit,
            trade_date=trade_date,
            min_score=min_score
        )

        return {
            "recommendations": sanitize_for_json(recommendations),
            "trade_date": trade_date,
            "engine_version": "v2"
        }

    except Exception as e:
        print(f"Error: {e}")
        return {"recommendations": [], "error": str(e)}


@router.get("/funds/short")
async def get_short_term_fund_recommendations(
    limit: int = 20,
    min_score: float = 55,
    current_user: User = Depends(get_current_user)
):
    """Get short-term fund recommendations (7+ days)."""
    try:
        from src.analysis.recommendation.fund_engine import FundRecommendationEngine
        from src.data_sources.tushare_client import get_latest_trade_date

        engine = FundRecommendationEngine()
        trade_date = get_latest_trade_date()

        recommendations = engine.get_recommendations(
            strategy='short_term',
            top_n=limit,
            trade_date=trade_date,
            min_score=min_score
        )

        return {
            "recommendations": sanitize_for_json(recommendations),
            "trade_date": trade_date,
            "engine_version": "v2"
        }

    except Exception as e:
        print(f"Error: {e}")
        return {"recommendations": [], "error": str(e)}


@router.get("/funds/long")
async def get_long_term_fund_recommendations(
    limit: int = 20,
    min_score: float = 55,
    current_user: User = Depends(get_current_user)
):
    """Get long-term fund recommendations (3+ months)."""
    try:
        from src.analysis.recommendation.fund_engine import FundRecommendationEngine
        from src.data_sources.tushare_client import get_latest_trade_date

        engine = FundRecommendationEngine()
        trade_date = get_latest_trade_date()

        recommendations = engine.get_recommendations(
            strategy='long_term',
            top_n=limit,
            trade_date=trade_date,
            min_score=min_score
        )

        return {
            "recommendations": sanitize_for_json(recommendations),
            "trade_date": trade_date,
            "engine_version": "v2"
        }

    except Exception as e:
        print(f"Error: {e}")
        return {"recommendations": [], "error": str(e)}


@router.get("/latest")
async def get_latest_recommendations(
    current_user: User = Depends(get_current_user)
):
    """Get the latest recommendation report."""
    try:
        from src.storage.db import get_latest_recommendation_report

        report = get_latest_recommendation_report(user_id=current_user.id)

        if not report:
            return {
                "available": False,
                "message": "No recommendations available. Please generate first using POST /api/recommend/generate"
            }

        return {
            "available": True,
            "data": report.get("recommendations_json", {}),
            "generated_at": report.get("generated_at"),
            "mode": report.get("mode"),
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_recommendation_history(
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    """Get historical recommendation reports."""
    try:
        from src.storage.db import get_recommendation_reports

        reports = get_recommendation_reports(user_id=current_user.id, limit=limit)

        # Return summaries without full content
        summaries = []
        for r in reports:
            data = r.get("recommendations_json", {})
            summaries.append({
                "id": r.get("id"),
                "mode": r.get("mode"),
                "generated_at": r.get("generated_at"),
                "short_term_count": len(data.get("short_term", {}).get("short_term_stocks", [])) if data.get("short_term") else 0,
                "long_term_count": len(data.get("long_term", {}).get("long_term_stocks", [])) if data.get("long_term") else 0,
            })

        return {"reports": summaries}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Analysis and Admin Endpoints
# =============================================================================

@router.get("/analyze/stock/{code}")
async def analyze_stock_v2(
    code: str,
    current_user: User = Depends(get_current_user)
):
    """Get comprehensive analysis for a single stock using v2 engine."""
    try:
        from src.analysis.recommendation.stock_engine.engine import analyze_stock

        result = analyze_stock(code)
        return sanitize_for_json(result)

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyze/fund/{code}")
async def analyze_fund_v2(
    code: str,
    current_user: User = Depends(get_current_user)
):
    """Get comprehensive analysis for a single fund using v2 engine."""
    try:
        from src.analysis.recommendation.fund_engine.engine import analyze_fund

        result = analyze_fund(code)
        return sanitize_for_json(result)

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
async def get_recommendation_performance(
    rec_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get recommendation performance statistics.

    Shows how past recommendations performed (hit rate, average return, etc.)
    """
    try:
        from src.storage.db import get_recommendation_performance_stats

        stats = get_recommendation_performance_stats(rec_type, start_date, end_date)

        return {
            "stats": stats,
            "filters": {
                "rec_type": rec_type,
                "start_date": start_date,
                "end_date": end_date
            }
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compute-factors")
async def trigger_factor_computation(
    asset_type: str = "stock",
    universe: str = "market_otc",
    current_user: User = Depends(get_current_user)
):
    """
    Manually trigger factor computation.

    This is normally run automatically at 6:00 AM.
    Admin only endpoint.
    """
    # TODO: Add admin check

    try:
        from src.analysis.recommendation.factor_store.daily_computer import daily_computer
        from src.data_sources.tushare_client import get_latest_trade_date
        from src.data_sources.fund_data_provider import get_fallback_trade_date

        if daily_computer.is_running:
            return {
                "status": "already_running",
                "progress": daily_computer.progress
            }

        if asset_type not in {"stock", "fund", "all"}:
            raise HTTPException(status_code=400, detail="asset_type must be one of: stock, fund, all")

        trade_date = get_latest_trade_date()
        if not trade_date:
            trade_date = get_fallback_trade_date()

        # Start computation in background
        import threading

        def run_target():
            if asset_type == "stock":
                daily_computer.compute_all_stock_factors(trade_date)
            elif asset_type == "fund":
                daily_computer.compute_all_fund_factors(trade_date, universe=universe)
            else:
                daily_computer.compute_all_stock_factors(trade_date)
                daily_computer.compute_all_fund_factors(trade_date, universe=universe)

        thread = threading.Thread(target=run_target)
        thread.start()

        return {
            "status": "started",
            "trade_date": trade_date,
            "asset_type": asset_type,
            "universe": universe,
            "message": "Factor computation started in background"
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/factor-status")
async def get_factor_computation_status(
    current_user: User = Depends(get_current_user)
):
    """Get the status of factor computation."""
    try:
        from src.analysis.recommendation.factor_store.daily_computer import daily_computer
        from src.analysis.recommendation.factor_store.cache import factor_cache

        return {
            "is_running": daily_computer.is_running,
            "progress": daily_computer.progress,
            "cache_stats": factor_cache.get_stats()
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
