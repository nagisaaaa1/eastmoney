# Router modules
from .health import router as health_router
from .auth import router as auth_router
from .settings import router as settings_router
from .funds import router as funds_router
from .stocks import router as stocks_router
from .market import router as market_router
from .reports import router as reports_router
from .commodities import router as commodities_router
from .sentiment import router as sentiment_router
from .dashboard import router as dashboard_router
from .widgets import router as widgets_router
from .news import router as news_router
from .recommendations import router as recommendations_router
from .assistant import router as assistant_router
from .preferences import router as preferences_router
from .details import router as details_router
from .compare import router as compare_router
from .alerts import router as alerts_router
from .admin import router as admin_router
from .generate import router as generate_router
from .portfolios import router as portfolios_router
from .fund_research import router as fund_research_router

__all__ = [
    'health_router', 'auth_router', 'settings_router', 'funds_router',
    'stocks_router', 'market_router', 'reports_router', 'commodities_router',
    'sentiment_router', 'dashboard_router', 'widgets_router', 'news_router',
    'recommendations_router', 'assistant_router', 'preferences_router',
    'details_router', 'compare_router', 'alerts_router', 'admin_router',
    'generate_router', 'portfolios_router', 'fund_research_router'
]
