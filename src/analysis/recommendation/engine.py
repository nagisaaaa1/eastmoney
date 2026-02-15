"""
Recommendation Engine - Main orchestrator for the quantitative recommendation system.

Key features:
1. Uses quantitative factor models for selection (not LLM)
2. Only uses LLM for explanation generation
3. Provides both stock and fund recommendations

Key principles:
- Quantitative models select, LLM explains
- Predict breakouts, don't chase rallies
- Quality and risk-adjusted returns over raw performance
"""
from typing import Dict, List, Optional, Any
from datetime import datetime

from src.data_sources.tushare_client import (
    get_latest_trade_date,
)
from src.data_sources.fund_data_provider import get_fallback_trade_date
from src.storage.db import (
    insert_recommendation_record,
    get_recommendation_performance_stats,
)

from .stock_engine import StockRecommendationEngine
from .fund_engine import FundRecommendationEngine
from .factor_store.cache import factor_cache
from .llm_synthesis.explainer import RecommendationExplainer, explain_recommendations_sync


class RecommendationEngine:
    """
    Recommendation Engine - Quantitative factor-based recommendations.

    This engine uses pre-computed factors and quantitative strategies
    to generate recommendations, with LLM used only for explanations.
    """

    # Industry mapping for preference filtering
    # Maps user-friendly sector names to actual database industry keywords
    SECTOR_KEYWORDS = {
        '医药': ['医药', '制药', '生物制药', '化学制药', '中药', '医疗', '医疗器械', '医疗服务', '疫苗', '药品'],
        '房地产': ['地产', '房产', '房地产', '区域地产', '全国地产', '房产服务'],
        '公用事业': ['水力发电', '火力发电', '电力', '燃气', '水务', '环保', '公用事业'],
        '银行': ['银行', '商业银行'],
        '保险': ['保险'],
        '证券': ['证券', '券商'],
        '科技': ['软件', '互联网', '半导体', '电子', '通信', '计算机', '芯片', '元器件', 'IT'],
        '互联网': ['互联网', '网络', '电商', '软件服务'],
        '新能源': ['新能源', '光伏', '锂电', '风电', '储能', '电池'],
        '消费': ['白酒', '食品', '饮料', '乳制品', '百货', '零售', '商业', '服饰', '家电'],
        '汽车': ['汽车', '汽配', '新能源车'],
        '钢铁': ['钢铁', '特钢'],
        '有色': ['有色', '稀有金属', '黄金', '铜', '铝'],
        '化工': ['化工', '化纤', '化工原料'],
        '机械': ['机械', '专用机械', '机械基件', '工程机械'],
        '军工': ['军工', '航天', '航空', '船舶'],
    }

    def __init__(self, use_llm_explanations: bool = True):
        """
        Initialize the v2 recommendation engine.

        Args:
            use_llm_explanations: Whether to use LLM for generating explanations
        """
        self.stock_engine = StockRecommendationEngine()
        self.fund_engine = FundRecommendationEngine()
        self.use_llm = use_llm_explanations

    def generate_recommendations(
        self,
        mode: str = "all",
        stock_limit: int = 20,
        fund_limit: int = 20,
        user_preferences: Optional[Dict[str, Any]] = None,
        trade_date: str = None,
    ) -> Dict[str, Any]:
        """
        Generate investment recommendations using quantitative models.

        Args:
            mode: "short", "long", or "all"
            stock_limit: Maximum number of stocks to recommend
            fund_limit: Maximum number of funds to recommend
            user_preferences: User preferences for filtering (optional)
            trade_date: Trade date for factor lookup

        Returns:
            Dict containing recommendations and metadata
        """
        start_time = datetime.now()
        import time as _time

        print(f"\n{'='*60}")
        print(f"[EngineV2] Starting recommendation generation")
        print(f"[EngineV2] Mode: {mode}, stock_limit: {stock_limit}, fund_limit: {fund_limit}")
        print(f"{'='*60}")

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = get_fallback_trade_date()
        print(f"[EngineV2] Using trade_date: {trade_date}")

        results = {
            "mode": mode,
            "generated_at": start_time.isoformat(),
            "trade_date": trade_date,
            "engine_version": "v2",
            "short_term": None,
            "long_term": None,
            "metadata": {
                "factor_computation_time": 0,
                "explanation_time": 0,
                "total_time": 0,
            }
        }

        # Generate short-term recommendations
        if mode in ["short", "all"]:
            print(f"\n[EngineV2] --- Generating SHORT-TERM recommendations ---")
            factor_start = _time.time()

            print(f"[EngineV2] Fetching short-term stocks...")
            short_stocks = self.stock_engine.get_recommendations(
                strategy='short_term',
                top_n=stock_limit,
                trade_date=trade_date
            )
            print(f"[EngineV2] Got {len(short_stocks)} short-term stocks")

            print(f"[EngineV2] Fetching short-term funds...")
            short_funds = self.fund_engine.get_recommendations(
                strategy='short_term',
                top_n=fund_limit,
                trade_date=trade_date
            )
            print(f"[EngineV2] Got {len(short_funds)} short-term funds")

            # Apply user preferences if provided
            if user_preferences:
                print(f"[EngineV2] Applying user preferences...")
                short_stocks = self._apply_stock_preferences(short_stocks, user_preferences)
                short_funds = self._apply_fund_preferences(short_funds, user_preferences)

            factor_time = _time.time() - factor_start
            print(f"[EngineV2] Short-term factor retrieval took {factor_time:.2f}s")

            # Add LLM explanations if enabled
            if self.use_llm and (short_stocks or short_funds):
                print(f"[EngineV2] Generating LLM explanations for short-term...")
                llm_start = _time.time()
                short_stocks = explain_recommendations_sync(short_stocks, 'stock', 'short_term')
                short_funds = explain_recommendations_sync(short_funds, 'fund', 'short_term')
                print(f"[EngineV2] LLM explanations took {_time.time() - llm_start:.2f}s")

            print(f"[EngineV2] Building short_term results dict...")
            results["short_term"] = {
                "stocks": short_stocks,
                "funds": short_funds,
                "market_view": self._get_market_summary(),
            }
            print(f"[EngineV2] Short_term results dict built")

            results["metadata"]["factor_computation_time"] = factor_time

        # Generate long-term recommendations
        if mode in ["long", "all"]:
            print(f"\n[EngineV2] --- Generating LONG-TERM recommendations ---")
            long_start = _time.time()

            print(f"[EngineV2] Fetching long-term stocks...")
            long_stocks = self.stock_engine.get_recommendations(
                strategy='long_term',
                top_n=stock_limit,
                trade_date=trade_date
            )
            print(f"[EngineV2] Got {len(long_stocks)} long-term stocks")

            print(f"[EngineV2] Fetching long-term funds...")
            long_funds = self.fund_engine.get_recommendations(
                strategy='long_term',
                top_n=fund_limit,
                trade_date=trade_date
            )
            print(f"[EngineV2] Got {len(long_funds)} long-term funds")

            if user_preferences:
                print(f"[EngineV2] Applying user preferences...")
                long_stocks = self._apply_stock_preferences(long_stocks, user_preferences)
                long_funds = self._apply_fund_preferences(long_funds, user_preferences)

            print(f"[EngineV2] Long-term factor retrieval took {_time.time() - long_start:.2f}s")

            if self.use_llm and (long_stocks or long_funds):
                print(f"[EngineV2] Generating LLM explanations for long-term...")
                llm_start = _time.time()
                long_stocks = explain_recommendations_sync(long_stocks, 'stock', 'long_term')
                long_funds = explain_recommendations_sync(long_funds, 'fund', 'long_term')
                print(f"[EngineV2] LLM explanations took {_time.time() - llm_start:.2f}s")

            print(f"[EngineV2] Building long_term results dict...")
            results["long_term"] = {
                "stocks": long_stocks,
                "funds": long_funds,
                "macro_view": self._get_macro_summary(),
            }
            print(f"[EngineV2] Long_term results dict built")

        print(f"[EngineV2] Calculating total time...")
        results["metadata"]["total_time"] = (datetime.now() - start_time).total_seconds()

        # Record recommendations for performance tracking
        print(f"[EngineV2] Starting _record_recommendations...")
        self._record_recommendations(results)

        print(f"\n{'='*60}")
        print(f"[EngineV2] Recommendation generation completed in {results['metadata']['total_time']:.2f}s")
        print(f"{'='*60}\n")

        return results

    def get_stock_analysis(self, code: str, trade_date: str = None) -> Dict:
        """
        Get comprehensive analysis for a single stock.

        Args:
            code: Stock code
            trade_date: Trade date

        Returns:
            Analysis dict with short-term and long-term recommendations
        """
        from .stock_engine.engine import analyze_stock
        return analyze_stock(code, trade_date)

    def get_fund_analysis(self, code: str, trade_date: str = None) -> Dict:
        """
        Get comprehensive analysis for a single fund.

        Args:
            code: Fund code
            trade_date: Trade date

        Returns:
            Analysis dict with short-term and long-term recommendations
        """
        from .fund_engine.engine import analyze_fund
        return analyze_fund(code, trade_date)

    def get_performance_stats(
        self,
        rec_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict:
        """
        Get recommendation performance statistics.

        Args:
            rec_type: Filter by recommendation type
            start_date: Start date filter
            end_date: End date filter

        Returns:
            Performance statistics by recommendation type
        """
        return get_recommendation_performance_stats(rec_type, start_date, end_date)

    def _match_sector(self, stock_industry: str, sector: str) -> bool:
        """
        Check if a stock's industry matches a sector preference.
        
        Args:
            stock_industry: The industry from database (e.g., "生物制药")
            sector: The user's sector preference (e.g., "医药")
            
        Returns:
            True if the industry matches the sector
        """
        if not stock_industry or not sector:
            return False
            
        # Direct match
        if sector in stock_industry or stock_industry in sector:
            return True
            
        # Check against keyword mapping
        keywords = self.SECTOR_KEYWORDS.get(sector, [])
        for keyword in keywords:
            if keyword in stock_industry or stock_industry in keyword:
                return True
                
        return False

    def _apply_stock_preferences(
        self,
        stocks: List[Dict],
        prefs: Dict[str, Any]
    ) -> List[Dict]:
        """Apply user preferences to filter stocks."""
        filtered = []
        excluded_count = 0
        preferred_count = 0

        excluded_sectors = prefs.get('excluded_sectors', [])
        preferred_sectors = prefs.get('preferred_sectors', [])
        
        print(f"[Preferences] Applying stock preferences:")
        print(f"[Preferences]   excluded_sectors: {excluded_sectors}")
        print(f"[Preferences]   preferred_sectors: {preferred_sectors}")
        print(f"[Preferences]   avoid_st_stocks: {prefs.get('avoid_st_stocks', True)}")
        print(f"[Preferences]   Total stocks to filter: {len(stocks)}")
        
        # Debug: print all stock industries
        print(f"[Preferences]   Stock industries in candidates:")
        for s in stocks[:5]:  # Show first 5
            print(f"[Preferences]     - {s.get('code')} ({s.get('name')}): industry='{s.get('industry', 'EMPTY')}'")

        for stock in stocks:
            # Skip ST stocks if preference set
            if prefs.get('avoid_st_stocks', True):
                name = stock.get('name', '')
                if 'ST' in name or '*ST' in name:
                    excluded_count += 1
                    continue

            stock_industry = stock.get('industry', '') or ''
            
            # Excluded sectors filter - skip stocks in excluded industries
            if excluded_sectors:
                should_exclude = False
                for exc in excluded_sectors:
                    if self._match_sector(stock_industry, exc):
                        print(f"[Preferences]   Excluding {stock.get('code')} ({stock.get('name')}) - industry '{stock_industry}' matches excluded '{exc}'")
                        should_exclude = True
                        break
                if should_exclude:
                    excluded_count += 1
                    continue

            # Preferred sectors filter - ONLY include stocks in preferred industries
            if preferred_sectors:
                is_preferred = False
                for pref in preferred_sectors:
                    if self._match_sector(stock_industry, pref):
                        is_preferred = True
                        preferred_count += 1
                        print(f"[Preferences]   Including {stock.get('code')} ({stock.get('name')}) - industry '{stock_industry}' matches preferred '{pref}'")
                        break
                if not is_preferred:
                    excluded_count += 1
                    continue

            # ROE filter for long-term
            roe = stock.get('factors', {}).get('roe')
            min_roe = prefs.get('min_roe')
            if min_roe and roe and roe < min_roe:
                excluded_count += 1
                continue

            filtered.append(stock)

        print(f"[Preferences] Stock filtering complete: {excluded_count} excluded, {len(filtered)} remaining (preferred matches: {preferred_count})")
        filtered.sort(key=lambda x: x.get('score', 0), reverse=True)
        return filtered

    def _apply_fund_preferences(
        self,
        funds: List[Dict],
        prefs: Dict[str, Any]
    ) -> List[Dict]:
        """Apply user preferences to filter funds."""
        filtered = []
        excluded_count = 0

        preferred_types = prefs.get('preferred_fund_types', [])
        excluded_types = prefs.get('excluded_fund_types', [])
        
        print(f"[Preferences] Applying fund preferences:")
        print(f"[Preferences]   preferred_fund_types: {preferred_types}")
        print(f"[Preferences]   excluded_fund_types: {excluded_types}")
        print(f"[Preferences]   Total funds to filter: {len(funds)}")

        for fund in funds:
            fund_type = fund.get('type', '') or ''

            # Type filter - preferred types (if set, only include matching)
            if preferred_types:
                if not any(pref in fund_type or fund_type in pref for pref in preferred_types):
                    excluded_count += 1
                    continue

            # Type filter - excluded types
            if excluded_types:
                should_exclude = False
                for exc in excluded_types:
                    if exc and fund_type and (exc in fund_type or fund_type in exc):
                        print(f"[Preferences]   Excluding fund {fund.get('code')} ({fund.get('name')}) - type '{fund_type}' matches excluded '{exc}'")
                        should_exclude = True
                        break
                if should_exclude:
                    excluded_count += 1
                    continue

            # Max drawdown filter
            max_dd = fund.get('factors', {}).get('max_drawdown_1y')
            max_dd_tolerance = prefs.get('max_drawdown_tolerance')
            if max_dd_tolerance and max_dd and max_dd > max_dd_tolerance * 100:
                excluded_count += 1
                continue

            filtered.append(fund)

        print(f"[Preferences] Fund filtering complete: {excluded_count} excluded, {len(filtered)} remaining")
        filtered.sort(key=lambda x: x.get('score', 0), reverse=True)
        return filtered

    def _get_market_summary(self) -> str:
        """Get brief market summary for short-term context."""
        print(f"[EngineV2] Getting market summary...")
        try:
            from src.data_sources.akshare_api import get_market_indices
            import concurrent.futures

            # Use timeout to prevent hanging on slow API calls
            print(f"[EngineV2] Calling get_market_indices() with 10s timeout...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(get_market_indices)
                try:
                    indices = future.result(timeout=10)
                except concurrent.futures.TimeoutError:
                    print(f"[EngineV2] get_market_indices() timed out after 10s")
                    return "市场指数数据获取超时"

            print(f"[EngineV2] get_market_indices() returned {type(indices)}")
            if not indices:
                return "市场指数数据暂时不可用"

            parts = []

            # Handle both list format (TuShare) and dict format (AkShare)
            if isinstance(indices, list):
                for item in indices[:3]:
                    name = item.get('name', '')
                    change = item.get('change_pct', item.get('涨跌幅', 'N/A'))
                    if change != 'N/A':
                        try:
                            change_val = float(change)
                            direction = "↑" if change_val > 0 else "↓" if change_val < 0 else "→"
                            parts.append(f"{name}: {direction}{abs(change_val):.2f}%")
                        except:
                            parts.append(f"{name}: {change}%")
                    else:
                        parts.append(f"{name}: {change}")
            else:
                for name, data in list(indices.items())[:3]:
                    change = data.get('涨跌幅', data.get('change_pct', 'N/A'))
                    if change != 'N/A':
                        try:
                            change_val = float(change)
                            direction = "↑" if change_val > 0 else "↓" if change_val < 0 else "→"
                            parts.append(f"{name}: {direction}{abs(change_val):.2f}%")
                        except:
                            parts.append(f"{name}: {change}%")
                    else:
                        parts.append(f"{name}: {change}")

            return " | ".join(parts) if parts else "市场指数数据暂时不可用"
        except Exception as e:
            print(f"Error getting market summary: {e}")
            return "市场指数数据暂时不可用"

    def _get_macro_summary(self) -> str:
        """Get brief macro summary for long-term context."""
        print(f"[EngineV2] Getting macro summary...")
        try:
            from src.data_sources.akshare_api import get_market_indices
            import concurrent.futures

            # Use timeout to prevent hanging on slow API calls
            print(f"[EngineV2] Calling get_market_indices() for macro with 10s timeout...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(get_market_indices)
                try:
                    indices = future.result(timeout=10)
                except concurrent.futures.TimeoutError:
                    print(f"[EngineV2] get_market_indices() for macro timed out after 10s")
                    return "宏观数据获取超时"

            print(f"[EngineV2] get_market_indices() for macro returned {type(indices)}")
            if not indices:
                return "宏观环境分析需要结合最新经济数据"

            # Get major indices status
            parts = []
            major_indices = ['上证指数', '深证成指', '创业板指', '沪深300']

            # Handle both list format (TuShare) and dict format (AkShare)
            if isinstance(indices, list):
                # Build a name->data lookup from the list
                indices_by_name = {item.get('name', ''): item for item in indices}
                for idx_name in major_indices:
                    if idx_name in indices_by_name:
                        data = indices_by_name[idx_name]
                        change = data.get('change_pct', data.get('涨跌幅', 0))
                        try:
                            change_val = float(change)
                            if change_val > 1:
                                parts.append(f"{idx_name}强势")
                            elif change_val < -1:
                                parts.append(f"{idx_name}走弱")
                        except:
                            pass
            else:
                for idx_name in major_indices:
                    if idx_name in indices:
                        data = indices[idx_name]
                        change = data.get('涨跌幅', data.get('change_pct', 0))
                        try:
                            change_val = float(change)
                            if change_val > 1:
                                parts.append(f"{idx_name}强势")
                            elif change_val < -1:
                                parts.append(f"{idx_name}走弱")
                        except:
                            pass

            if parts:
                return "今日市场：" + "，".join(parts[:2]) + "。长期投资需关注基本面和估值。"
            else:
                return "市场震荡整理中，建议关注优质标的长期配置价值。"
        except Exception as e:
            print(f"Error getting macro summary: {e}")
            return "宏观环境分析需要结合最新经济数据"

    def _record_recommendations(self, results: Dict) -> None:
        """Record recommendations for performance tracking."""
        import time
        print(f"[EngineV2] Recording recommendations for performance tracking...")
        start = time.time()

        trade_date = results.get('trade_date', '')
        record_count = 0

        for term in ['short_term', 'long_term']:
            if results.get(term):
                rec_type_prefix = 'short' if term == 'short_term' else 'long'

                # Record stock recommendations (limit to top 5 to reduce DB writes)
                for stock in results[term].get('stocks', [])[:5]:
                    try:
                        insert_recommendation_record({
                            'code': stock.get('code'),
                            'rec_type': f'{rec_type_prefix}_stock',
                            'rec_date': trade_date,
                            'rec_price': stock.get('factors', {}).get('price'),
                            'rec_score': stock.get('score'),
                            'target_return_pct': 5.0 if term == 'short_term' else 10.0,
                            'stop_loss_pct': -3.0 if term == 'short_term' else -5.0,
                        })
                        record_count += 1
                    except Exception as e:
                        print(f"[EngineV2] Failed to record stock {stock.get('code')}: {e}")

                # Record fund recommendations (limit to top 5 to reduce DB writes)
                for fund in results[term].get('funds', [])[:5]:
                    try:
                        insert_recommendation_record({
                            'code': fund.get('code'),
                            'rec_type': f'{rec_type_prefix}_fund',
                            'rec_date': trade_date,
                            'rec_score': fund.get('score'),
                            'target_return_pct': 3.0 if term == 'short_term' else 8.0,
                            'stop_loss_pct': -2.0 if term == 'short_term' else -4.0,
                        })
                        record_count += 1
                    except Exception as e:
                        print(f"[EngineV2] Failed to record fund {fund.get('code')}: {e}")

        print(f"[EngineV2] Recorded {record_count} recommendations in {time.time() - start:.2f}s")


# Convenience function for easy access
def get_recommendations(
    mode: str = "all",
    stock_limit: int = 20,
    fund_limit: int = 20,
    use_llm: bool = True,
    user_preferences: Optional[Dict] = None
) -> Dict:
    """
    Generate recommendations using the quantitative engine.

    This is a convenience function for easy access to the system.
    """
    engine = RecommendationEngine(use_llm_explanations=use_llm)
    return engine.generate_recommendations(
        mode=mode,
        stock_limit=stock_limit,
        fund_limit=fund_limit,
        user_preferences=user_preferences
    )


# Backward compatibility alias
get_v2_recommendations = get_recommendations
RecommendationEngineV2 = RecommendationEngine
