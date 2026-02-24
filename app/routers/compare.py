"""
Comparison endpoints.
"""
from typing import List
from fastapi import APIRouter, HTTPException, Depends
import akshare as ak

from app.models.auth import User
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/compare", tags=["Compare"])


@router.post("/stocks")
async def compare_stocks(codes: List[str], current_user: User = Depends(get_current_user)):
    """Compare multiple stocks side by side."""
    try:
        if len(codes) < 2 or len(codes) > 5:
            raise HTTPException(status_code=400, detail="Please select 2-5 stocks to compare")

        spot_df = ak.stock_zh_a_spot_em()
        comparisons = []

        for code in codes:
            stock_info = spot_df[spot_df['代码'] == code]
            if not stock_info.empty:
                stock_data = stock_info.iloc[0]
                comparisons.append({
                    "code": code,
                    "name": stock_data.get('名称'),
                    "price": stock_data.get('最新价'),
                    "change_pct": stock_data.get('涨跌幅'),
                    "pe": stock_data.get('市盈率-动态'),
                    "pb": stock_data.get('市净率'),
                    "market_cap": stock_data.get('总市值'),
                    "volume_ratio": stock_data.get('量比'),
                    "turnover_rate": stock_data.get('换手率'),
                    "amplitude": stock_data.get('振幅'),
                })

        if not comparisons:
            raise HTTPException(status_code=404, detail="No valid stocks found")

        return {"stocks": comparisons}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/funds")
async def compare_funds(codes: List[str], current_user: User = Depends(get_current_user)):
    """Compare multiple funds side by side."""
    try:
        if len(codes) < 2 or len(codes) > 5:
            raise HTTPException(status_code=400, detail="Please select 2-5 funds to compare")

        comparisons = []

        for code in codes:
            try:
                # Get fund ranking data
                rank_data = None
                for fund_type in ["股票型", "混合型", "指数型"]:
                    try:
                        df = ak.fund_open_fund_rank_em(symbol=fund_type)
                        fund_row = df[df['基金代码'] == code]
                        if not fund_row.empty:
                            rank_data = fund_row.iloc[0]
                            break
                    except Exception:
                        continue

                if rank_data is not None:
                    comparisons.append({
                        "code": code,
                        "name": rank_data.get('基金简称'),
                        "fund_type": fund_type,
                        "nav": rank_data.get('单位净值'),
                        "return_1w": rank_data.get('近1周'),
                        "return_1m": rank_data.get('近1月'),
                        "return_3m": rank_data.get('近3月'),
                        "return_6m": rank_data.get('近6月'),
                        "return_1y": rank_data.get('近1年'),
                        "return_3y": rank_data.get('近3年'),
                    })
            except Exception:
                continue

        if not comparisons:
            raise HTTPException(status_code=404, detail="No valid funds found")

        return {"funds": comparisons}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
