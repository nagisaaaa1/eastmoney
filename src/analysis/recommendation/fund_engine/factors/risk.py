"""
Fund Risk Factors - Risk metrics for fund recommendation.

Key factors:
- Sharpe ratio (20-day, 1-year)
- Sortino ratio
- Calmar ratio
- Maximum drawdown and recovery time
- Volatility metrics
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, List
from datetime import datetime, timedelta

from src.data_sources.tushare_client import format_date_yyyymmdd
from src.data_sources.fund_data_provider import get_fund_nav_with_fallback


class RiskFactors:
    """
    Risk factor computation for funds.

    Uses NAV history to compute risk-adjusted return metrics.
    """

    # Risk-free rate assumption (annualized)
    RISK_FREE_RATE = 0.02  # 2% annual

    @classmethod
    def compute(cls, fund_code: str, trade_date: str) -> Dict:
        """
        Compute all risk factors for a fund.

        Args:
            fund_code: Fund code
            trade_date: Trade date in YYYYMMDD format

        Returns:
            Dict with risk factors
        """
        factors = {
            'volatility_20d': None,
            'volatility_60d': None,
            'sharpe_20d': None,
            'sharpe_1y': None,
            'sortino_1y': None,
            'calmar_1y': None,
            'max_drawdown_1y': None,
            'avg_recovery_days': None,
        }

        try:
            # Get NAV data for past year
            end_date = trade_date
            start_date = format_date_yyyymmdd(
                datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=400)
            )

            nav_df = get_fund_nav_with_fallback(fund_code, start_date, end_date)

            if nav_df is None or len(nav_df) < 20:
                return factors

            # Sort by date ascending
            nav_df = nav_df.sort_values('nav_date')

            # Get NAV column
            nav_col = 'accum_nav' if 'accum_nav' in nav_df.columns else 'unit_nav'
            if nav_col not in nav_df.columns:
                return factors

            navs = nav_df[nav_col].dropna()

            if len(navs) < 20:
                return factors

            # Compute daily returns
            returns = navs.pct_change().dropna()

            # Volatility metrics
            factors['volatility_20d'] = cls._compute_volatility(returns, 20)
            factors['volatility_60d'] = cls._compute_volatility(returns, 60)

            # Sharpe ratios
            factors['sharpe_20d'] = cls._compute_sharpe(returns, 20)
            factors['sharpe_1y'] = cls._compute_sharpe(returns, 250)

            # Sortino ratio (downside risk)
            factors['sortino_1y'] = cls._compute_sortino(returns, 250)

            # Maximum drawdown
            max_dd, avg_recovery = cls._compute_drawdown_metrics(navs)
            factors['max_drawdown_1y'] = max_dd
            factors['avg_recovery_days'] = avg_recovery

            # Calmar ratio
            if max_dd and max_dd > 0:
                annual_return = cls._compute_annual_return(navs)
                factors['calmar_1y'] = round(annual_return / max_dd, 4) if max_dd > 0 else None

        except Exception as e:
            print(f"Error computing risk factors for {fund_code}: {e}")

        return factors

    @classmethod
    def _normalize_fund_code(cls, code: str) -> str:
        """Convert fund code to TuShare format."""
        if '.' in code:
            return code

        # Most funds are off-exchange (.OF)
        if code.startswith(('5', '1')):
            return f"{code}.SH"  # ETFs on Shanghai
        elif code.startswith(('15', '16')):
            return f"{code}.SZ"  # ETFs on Shenzhen
        else:
            return f"{code}.OF"  # Off-exchange funds

    @classmethod
    def _compute_volatility(cls, returns: pd.Series, days: int) -> Optional[float]:
        """Compute annualized volatility over specified period."""
        if len(returns) < days:
            return None

        recent = returns.tail(days)
        daily_vol = recent.std()
        annual_vol = daily_vol * np.sqrt(252)  # Annualize

        return round(annual_vol * 100, 4)  # As percentage

    @classmethod
    def _compute_sharpe(cls, returns: pd.Series, days: int) -> Optional[float]:
        """
        Compute Sharpe ratio.

        Sharpe = (Return - Risk-free) / Volatility
        """
        if len(returns) < days:
            return None

        recent = returns.tail(days)

        # Annualized return
        mean_daily = recent.mean()
        annual_return = mean_daily * 252

        # Annualized volatility
        daily_vol = recent.std()
        annual_vol = daily_vol * np.sqrt(252)

        if annual_vol == 0:
            return None

        sharpe = (annual_return - cls.RISK_FREE_RATE) / annual_vol

        return round(sharpe, 4)

    @classmethod
    def _compute_sortino(cls, returns: pd.Series, days: int) -> Optional[float]:
        """
        Compute Sortino ratio (uses only downside volatility).

        Sortino = (Return - Risk-free) / Downside Volatility
        """
        if len(returns) < days:
            return None

        recent = returns.tail(days)

        # Annualized return
        mean_daily = recent.mean()
        annual_return = mean_daily * 252

        # Downside volatility (only negative returns)
        negative_returns = recent[recent < 0]
        if len(negative_returns) == 0:
            return None

        downside_vol = negative_returns.std() * np.sqrt(252)

        if downside_vol == 0:
            return None

        sortino = (annual_return - cls.RISK_FREE_RATE) / downside_vol

        return round(sortino, 4)

    @classmethod
    def _compute_drawdown_metrics(
        cls,
        navs: pd.Series
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Compute maximum drawdown and average recovery time.

        Returns:
            Tuple of (max_drawdown_pct, avg_recovery_days)
        """
        if len(navs) < 20:
            return None, None

        # Calculate running maximum
        running_max = navs.expanding().max()

        # Calculate drawdown from peak
        drawdown = (navs - running_max) / running_max

        # Maximum drawdown
        max_dd = abs(drawdown.min()) * 100  # As percentage

        # Calculate recovery time for each drawdown period
        recovery_days = []
        in_drawdown = False
        drawdown_start = None

        for i, (nav, peak) in enumerate(zip(navs, running_max)):
            if nav < peak and not in_drawdown:
                in_drawdown = True
                drawdown_start = i
            elif nav >= peak and in_drawdown:
                in_drawdown = False
                if drawdown_start is not None:
                    recovery_days.append(i - drawdown_start)

        avg_recovery = np.mean(recovery_days) if recovery_days else None

        return round(max_dd, 4), round(avg_recovery, 1) if avg_recovery else None

    @classmethod
    def _compute_annual_return(cls, navs: pd.Series) -> float:
        """Compute annualized return from NAV series."""
        if len(navs) < 20:
            return 0

        start_nav = navs.iloc[0]
        end_nav = navs.iloc[-1]
        days = len(navs)

        total_return = (end_nav - start_nav) / start_nav
        annual_return = (1 + total_return) ** (365 / days) - 1

        return annual_return


def compute_risk_score(factors: Dict) -> float:
    """
    Compute overall risk-adjusted score from risk factors.

    Lower risk = higher score for risk-averse investors.

    Components:
    - Sharpe ratio: 35%
    - Sortino ratio: 25%
    - Max drawdown (inverted): 25%
    - Volatility (inverted): 15%

    Returns:
        Score 0-100 (higher = better risk-adjusted profile)
    """
    score = 0
    weights = 0

    # Sharpe ratio (35%)
    sharpe = factors.get('sharpe_1y')
    if sharpe is not None:
        # Sharpe: < 0 = bad, 0.5 = okay, 1 = good, 2+ = excellent
        if sharpe >= 2:
            sharpe_score = 95
        elif sharpe >= 1:
            sharpe_score = 70 + (sharpe - 1) * 25
        elif sharpe >= 0.5:
            sharpe_score = 50 + (sharpe - 0.5) * 40
        elif sharpe >= 0:
            sharpe_score = 30 + sharpe * 40
        else:
            sharpe_score = max(0, 30 + sharpe * 15)
        score += sharpe_score * 0.35
        weights += 0.35

    # Sortino ratio (25%)
    sortino = factors.get('sortino_1y')
    if sortino is not None:
        if sortino >= 2:
            sortino_score = 95
        elif sortino >= 1:
            sortino_score = 70 + (sortino - 1) * 25
        elif sortino >= 0:
            sortino_score = 40 + sortino * 30
        else:
            sortino_score = max(0, 40 + sortino * 20)
        score += sortino_score * 0.25
        weights += 0.25

    # Max drawdown (25%) - lower is better
    max_dd = factors.get('max_drawdown_1y')
    if max_dd is not None:
        # Max DD: < 5% = excellent, 10% = good, 20% = okay, > 30% = bad
        if max_dd < 5:
            dd_score = 95
        elif max_dd < 10:
            dd_score = 80 + (10 - max_dd) * 3
        elif max_dd < 20:
            dd_score = 50 + (20 - max_dd) * 3
        elif max_dd < 30:
            dd_score = 30 + (30 - max_dd) * 2
        else:
            dd_score = max(0, 30 - (max_dd - 30))
        score += dd_score * 0.25
        weights += 0.25

    # Volatility (15%) - moderate is best
    vol = factors.get('volatility_60d')
    if vol is not None:
        # Volatility: < 10% = too low?, 10-20% = good, > 30% = high risk
        if 10 <= vol <= 20:
            vol_score = 80
        elif vol < 10:
            vol_score = 60 + vol * 2
        elif vol <= 30:
            vol_score = 80 - (vol - 20) * 2
        else:
            vol_score = max(0, 60 - (vol - 30))
        score += vol_score * 0.15
        weights += 0.15

    if weights > 0:
        return round(score / weights * 100, 2)

    return 50.0
