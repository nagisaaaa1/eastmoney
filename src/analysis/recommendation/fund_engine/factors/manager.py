"""
Fund Manager Factors - Manager quality metrics for fund recommendation.

Key factors:
- Manager tenure
- Bull/bear market alpha consistency
- Style consistency
- Fund size appropriateness
"""
import pandas as pd
from typing import Dict, Optional
from datetime import datetime, timedelta

from src.data_sources.tushare_client import (
    tushare_call_with_retry,
    format_date_yyyymmdd,
)
from src.data_sources.fund_data_provider import (
    get_fund_basic_snapshot,
    get_fund_nav_with_fallback,
)


class ManagerFactors:
    """
    Manager factor computation for funds.

    Evaluates fund manager quality based on experience and performance consistency.
    """

    # Optimal fund size range (in billion CNY)
    OPTIMAL_SIZE_MIN = 1.0  # Too small = liquidity risk
    OPTIMAL_SIZE_MAX = 50.0  # Too large = hard to beat market

    @classmethod
    def compute(cls, fund_code: str, trade_date: str) -> Dict:
        """
        Compute all manager factors for a fund.

        Args:
            fund_code: Fund code
            trade_date: Trade date in YYYYMMDD format

        Returns:
            Dict with manager factors
        """
        factors = {
            'manager_tenure_years': None,
            'manager_alpha_bull': None,
            'manager_alpha_bear': None,
            'style_consistency': None,
            'fund_size': None,
        }

        ts_code = cls._normalize_fund_code(fund_code)

        # Snapshot fallback from AkShare (size/manager metadata).
        try:
            size_billion = get_fund_basic_snapshot(fund_code).get('fund_size_billion')
            if size_billion is not None:
                factors['fund_size'] = round(float(size_billion), 2)
        except Exception:
            pass

        # TuShare manager tenure and size when available.
        try:
            manager_df = tushare_call_with_retry('fund_manager', ts_code=ts_code)
            if manager_df is not None and not manager_df.empty:
                factors['manager_tenure_years'] = cls._compute_tenure(manager_df, trade_date)
        except Exception as e:
            print(f"Manager tenure fetch failed for {fund_code}: {e}")

        try:
            basic_df = tushare_call_with_retry(
                'fund_daily',
                ts_code=ts_code,
                start_date=trade_date,
                end_date=trade_date
            )
            if basic_df is not None and not basic_df.empty and 'total_nav' in basic_df.columns:
                total_nav = basic_df['total_nav'].iloc[0]
                if pd.notna(total_nav):
                    factors['fund_size'] = round(float(total_nav) / 1e9, 2)
        except Exception as e:
            print(f"Fund size fetch failed for {fund_code}: {e}")

        # Compute alpha/style from NAV regardless of TuShare availability.
        try:
            nav_factors = cls._compute_nav_based_factors(fund_code, trade_date)
            factors.update(nav_factors)
        except Exception as e:
            print(f"NAV-based manager factors failed for {fund_code}: {e}")

        return factors

    @classmethod
    def _normalize_fund_code(cls, code: str) -> str:
        """Convert fund code to TuShare format."""
        if '.' in code:
            return code

        if code.startswith(('5', '1')):
            return f"{code}.SH"
        elif code.startswith(('15', '16')):
            return f"{code}.SZ"
        else:
            return f"{code}.OF"

    @classmethod
    def _compute_tenure(cls, manager_df: pd.DataFrame, trade_date: str) -> Optional[float]:
        """
        Compute current manager's tenure in years.

        Takes the tenure of the manager who is currently managing the fund.
        """
        try:
            # Filter for current manager (end_date is null or in future)
            current_trade = datetime.strptime(trade_date, '%Y%m%d')

            for _, row in manager_df.iterrows():
                end_date = row.get('end_date')
                start_date = row.get('begin_date')

                if start_date is None:
                    continue

                # Check if this manager is current.
                # TuShare often returns NaN for ongoing manager end_date.
                if end_date is None or pd.isna(end_date) or (
                    pd.notna(end_date) and
                    datetime.strptime(str(end_date), '%Y%m%d') > current_trade
                ):
                    # Calculate tenure
                    start_dt = datetime.strptime(str(start_date), '%Y%m%d')
                    tenure_days = (current_trade - start_dt).days
                    return round(tenure_days / 365, 2)

            return None

        except Exception:
            return None

    @classmethod
    def _compute_nav_based_factors(cls, fund_code: str, trade_date: str) -> Dict:
        """
        Compute alpha and style factors from NAV history.

        This is a simplified implementation - full alpha calculation
        would need benchmark comparison.
        """
        factors = {
            'manager_alpha_bull': None,
            'manager_alpha_bear': None,
            'style_consistency': None,
        }

        try:
            # Get 2 years of NAV data
            end_date = trade_date
            start_date = format_date_yyyymmdd(
                datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=730)
            )

            nav_df = get_fund_nav_with_fallback(fund_code, start_date, end_date)

            if nav_df is None or len(nav_df) < 100:
                return factors

            # Sort and get NAV column
            date_col = 'nav_date'
            nav_df = nav_df.sort_values(date_col)

            nav_col = 'accum_nav' if 'accum_nav' in nav_df.columns else 'unit_nav'
            if nav_col not in nav_df.columns:
                return factors

            # Calculate monthly returns
            nav_df['returns'] = nav_df[nav_col].pct_change()
            monthly_returns = nav_df.groupby(
                pd.to_datetime(nav_df[date_col]).dt.to_period('M')
            )['returns'].sum()

            if len(monthly_returns) < 12:
                return factors

            # Style consistency: standard deviation of monthly rankings
            # Lower std = more consistent style
            return_std = monthly_returns.std()
            # Normalize: std < 0.02 = very consistent, std > 0.1 = erratic
            consistency_score = max(0, min(100, 100 - return_std * 500))
            factors['style_consistency'] = round(consistency_score, 2)

            # Simplified alpha calculation
            # Positive months = bull, negative months = bear
            positive_months = monthly_returns[monthly_returns > 0]
            negative_months = monthly_returns[monthly_returns < 0]

            if len(positive_months) > 0:
                # Alpha in bull markets: excess return above average
                avg_positive = positive_months.mean() * 100
                factors['manager_alpha_bull'] = round(avg_positive, 4)

            if len(negative_months) > 0:
                # Alpha in bear markets: how much less negative than average
                avg_negative = negative_months.mean() * 100
                # Less negative = better defense
                factors['manager_alpha_bear'] = round(-avg_negative, 4)

        except Exception as e:
            print(f"Error computing NAV-based factors: {e}")

        return factors


def compute_manager_score(factors: Dict) -> float:
    """
    Compute overall manager quality score.

    Components:
    - Tenure: 25% (experience matters)
    - Bull market alpha: 25%
    - Bear market alpha: 25%
    - Style consistency: 15%
    - Size appropriateness: 10%

    Returns:
        Score 0-100 (higher = better manager quality)
    """
    score = 0
    weights = 0

    # Tenure score (25%)
    tenure = factors.get('manager_tenure_years')
    if tenure is not None:
        # 0-1 year: 30, 1-3 years: 50, 3-5 years: 70, 5+ years: 85+
        if tenure >= 5:
            tenure_score = min(95, 85 + (tenure - 5) * 2)
        elif tenure >= 3:
            tenure_score = 70 + (tenure - 3) * 7.5
        elif tenure >= 1:
            tenure_score = 50 + (tenure - 1) * 10
        else:
            tenure_score = 30 + tenure * 20
        score += tenure_score * 0.25
        weights += 0.25

    # Bull market alpha (25%)
    alpha_bull = factors.get('manager_alpha_bull')
    if alpha_bull is not None:
        # Monthly alpha: 0% = 50, 1% = 70, 2%+ = 90
        if alpha_bull >= 2:
            alpha_score = 90 + min(10, (alpha_bull - 2) * 5)
        elif alpha_bull >= 1:
            alpha_score = 70 + (alpha_bull - 1) * 20
        elif alpha_bull >= 0:
            alpha_score = 50 + alpha_bull * 20
        else:
            alpha_score = max(0, 50 + alpha_bull * 25)
        score += alpha_score * 0.25
        weights += 0.25

    # Bear market alpha (25%)
    alpha_bear = factors.get('manager_alpha_bear')
    if alpha_bear is not None:
        # Positive = good defense (lost less)
        if alpha_bear >= 1:
            alpha_score = 80 + min(20, alpha_bear * 10)
        elif alpha_bear >= 0:
            alpha_score = 60 + alpha_bear * 20
        else:
            alpha_score = max(0, 60 + alpha_bear * 30)
        score += alpha_score * 0.25
        weights += 0.25

    # Style consistency (15%)
    consistency = factors.get('style_consistency')
    if consistency is not None:
        score += consistency * 0.15
        weights += 0.15

    # Size appropriateness (10%)
    size = factors.get('fund_size')
    if size is not None:
        if ManagerFactors.OPTIMAL_SIZE_MIN <= size <= ManagerFactors.OPTIMAL_SIZE_MAX:
            size_score = 90
        elif size < ManagerFactors.OPTIMAL_SIZE_MIN:
            # Too small
            size_score = 50 + (size / ManagerFactors.OPTIMAL_SIZE_MIN) * 40
        else:
            # Too large
            excess = (size - ManagerFactors.OPTIMAL_SIZE_MAX) / ManagerFactors.OPTIMAL_SIZE_MAX
            size_score = max(30, 90 - excess * 50)
        score += size_score * 0.10
        weights += 0.10

    if weights > 0:
        return round(score / weights * 100, 2)

    return 50.0
