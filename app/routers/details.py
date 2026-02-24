"""
Stock and fund details endpoints.
"""
import asyncio
from fastapi import APIRouter, HTTPException, Depends
import akshare as ak

from app.models.auth import User
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/details", tags=["Details"])


@router.get("/stock/{code}")
async def get_stock_details(code: str, current_user: User = Depends(get_current_user)):
    """Get detailed stock information."""
    try:
        # Get basic info
        spot_df = ak.stock_zh_a_spot_em()
        stock_info = spot_df[spot_df['代码'] == code]

        if stock_info.empty:
            raise HTTPException(status_code=404, detail="Stock not found")

        stock_data = stock_info.iloc[0].to_dict()

        # Get historical data (last 60 days)
        try:
            hist_df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
            if not hist_df.empty:
                hist_df = hist_df.tail(60)
                history = hist_df.to_dict('records')
            else:
                history = []
        except Exception:
            history = []

        # Get financial indicators
        try:
            financial_df = ak.stock_financial_analysis_indicator(symbol=code)
            if not financial_df.empty:
                financial_data = financial_df.iloc[0].to_dict()
            else:
                financial_data = {}
        except Exception:
            financial_data = {}

        return {
            "code": code,
            "name": stock_data.get('名称'),
            "price": stock_data.get('最新价'),
            "change_pct": stock_data.get('涨跌幅'),
            "volume": stock_data.get('成交量'),
            "turnover": stock_data.get('成交额'),
            "pe": stock_data.get('市盈率-动态'),
            "pb": stock_data.get('市净率'),
            "market_cap": stock_data.get('总市值'),
            "history": history,
            "financial": financial_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fund/{code}")
async def get_fund_details(code: str, current_user: User = Depends(get_current_user)):
    """Get detailed fund information."""
    try:
        # Get fund basic info
        try:
            info_df = ak.fund_individual_basic_info_xq(symbol=code)
            basic_info = info_df.to_dict() if not info_df.empty else {}
        except Exception:
            basic_info = {}

        # Get fund NAV history
        try:
            nav_df = ak.fund_open_fund_info_em(fund=code, indicator="单位净值走势")
            if not nav_df.empty:
                nav_df = nav_df.tail(180)  # Last 180 days
                nav_history = nav_df.to_dict('records')
            else:
                nav_history = []
        except Exception:
            nav_history = []

        # Get fund manager info
        try:
            manager_df = ak.fund_manager_em(fund=code)
            manager_info = manager_df.to_dict('records') if not manager_df.empty else []
        except Exception:
            manager_info = []

        # Get holdings info
        try:
            holdings_df = ak.fund_portfolio_hold_em(symbol=code, date="")
            if not holdings_df.empty:
                holdings = holdings_df.head(10).to_dict('records')
            else:
                holdings = []
        except Exception:
            holdings = []

        return {
            "code": code,
            "name": basic_info.get('基金简称'),
            "type": basic_info.get('基金类型'),
            "basic_info": basic_info,
            "nav_history": nav_history,
            "manager_info": manager_info,
            "top_holdings": holdings,
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
