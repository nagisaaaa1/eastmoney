"""
Generate report endpoints.
"""
import asyncio
from fastapi import APIRouter, HTTPException, Depends

from app.models.settings import GenerateRequest
from app.models.auth import User
from app.core.dependencies import get_current_user
from src.storage.db import get_active_funds
from src.scheduler.manager import scheduler_manager

router = APIRouter(prefix="/api/generate", tags=["Generate"])


@router.post("/{mode}")
async def generate_report_endpoint(
    mode: str,
    request: GenerateRequest = None,
    current_user: User = Depends(get_current_user)
):
    """Generate pre-market or post-market report."""
    if mode not in ["pre", "post"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'pre' or 'post'.")

    fund_code = request.fund_code if request else None
    force_run = bool(request.force) if request else False

    try:
        print(f"Generating {mode}-market report for User {current_user.id}... (Fund: {fund_code if fund_code else 'ALL'})")

        if fund_code:
            await asyncio.to_thread(
                scheduler_manager.run_analysis_task,
                fund_code,
                mode,
                user_id=current_user.id,
                force_run=force_run,
            )
            return {
                "status": "success",
                "message": f"Task triggered for {fund_code}",
                "force": force_run,
            }
        else:
            funds = get_active_funds(user_id=current_user.id)
            results = []
            for fund in funds:
                try:
                    await asyncio.to_thread(
                        scheduler_manager.run_analysis_task,
                        fund['code'],
                        mode,
                        user_id=current_user.id,
                        force_run=force_run,
                    )
                    results.append(fund['code'])
                except:
                    pass
            return {
                "status": "success",
                "message": f"Triggered tasks for {len(results)} funds",
                "force": force_run,
            }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
