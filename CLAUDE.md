# VAlpha Terminal - Project Configuration

## Project Overview

**VAlpha Terminal** - AI-powered financial intelligence platform for Chinese A-stock market analysis.

Full-stack application: FastAPI backend + React 19 frontend, with fund screening, portfolio management, stock monitoring, AI recommendations, and market sentiment analysis.

---

## Tech Stack

### Backend
| Technology | Purpose |
|-----------|---------|
| Python 3.10+ | Primary language |
| FastAPI + Uvicorn | Async web framework |
| SQLite (funds.db) | Primary database |
| Redis | Optional caching |
| APScheduler | Background task scheduling |
| AkShare / TuShare / yFinance | Market data providers |
| Gemini / OpenAI / Qwen (DashScope) | LLM providers |
| Tavily | Web search for sentiment |

### Frontend
| Technology | Purpose |
|-----------|---------|
| React 19 + TypeScript 5.9 | UI framework |
| Vite 7 | Build tool |
| Material-UI 7 + Tailwind CSS | Styling |
| ECharts 6 + Recharts | Data visualization |
| Zustand | State management |
| i18next | Internationalization (zh/en) |
| React Router 7 | Routing |

---

## Architecture

### Directory Structure

```
D:\eastmoney/
├── app/                    # FastAPI application layer
│   ├── core/               # Config, cache, dependencies, helpers
│   ├── models/             # Pydantic request/response models
│   ├── routers/            # API endpoint handlers (20+ routers)
│   ├── main.py             # Application factory (create_app)
│   └── static.py           # Static file serving & SPA routing
├── src/                    # Core business logic
│   ├── analysis/           # Analysis engines
│   │   ├── fund/           # Fund diagnosis, risk, comparison
│   │   ├── portfolio/      # Portfolio risk, correlation, stress test
│   │   ├── recommendation/ # Factor-based + LLM recommendation engine
│   │   ├── sentiment/      # Market sentiment (news, social, money flow)
│   │   ├── commodities/    # Gold/silver analysis
│   │   ├── strategies/     # Strategy pattern (base → equity/stock/commodity)
│   │   ├── fund_research/  # Fund research workflow (screening + scoring)
│   │   └── utils/          # Shared analysis utilities
│   ├── data_sources/       # Data provider abstraction layer
│   ├── llm/                # LLM client + prompts + tool calling
│   ├── scheduler/          # APScheduler task management
│   ├── storage/            # SQLite database operations
│   ├── services/           # Business services (news, assistant, email)
│   └── cache/              # Cache management
├── web/                    # React frontend
│   └── src/
│       ├── pages/          # Page components
│       ├── components/     # Reusable UI components
│       ├── widgets/        # Dashboard grid widgets
│       ├── locales/        # i18n translations (zh/en)
│       ├── api.ts          # Axios API client
│       └── theme/          # MUI theming
├── config/                 # Runtime config (funds.json, cache)
├── reports/                # Generated analysis reports (markdown)
├── docker/                 # Docker deployment
└── scripts/                # Utility scripts
```

### Key Patterns

| Pattern | Usage | Reference (TradingAgents) |
|---------|-------|--------------------------|
| **Strategy** | `src/analysis/strategies/` - base → equity/stock/commodity | Similar to data vendor strategy |
| **Factory** | `src/analysis/strategies/factory.py` - strategy creation | `llm_clients/factory.py` |
| **Provider Abstraction** | `src/data_sources/` - AkShare/TuShare/yFinance | `dataflows/interface.py` |
| **Router Separation** | `app/routers/` - one file per domain | Clean API boundary |
| **Application Factory** | `app/main.py` - `create_app()` | Standard FastAPI pattern |
| **Config-Driven** | `.env` + `app/core/config.py` | `default_config.py` |

### Patterns to Adopt from TradingAgents

1. **Multi-Agent Debate**: Bull/bear research debate → risk committee for fund screening decisions
2. **Scoring Framework**: Weighted multi-dimensional scoring (macro, index, quality, risk)
3. **Pool Guard**: Candidate pool validation with audit trail
4. **Memory & Reflection**: Agent memory for learning from past decisions
5. **Workflow DSL**: JSON-based configurable workflow definitions

---

## Coding Standards

### Python (Backend)

**File size**: 200-400 lines per file. Split when exceeding 400 lines.

**Imports** (order):
```python
# 1. Standard library
import os
from pathlib import Path

# 2. Third-party
import pandas as pd
from fastapi import APIRouter, Depends

# 3. Local
from src.data_sources import DataSourceManager
from app.core.config import settings
```

**Naming**:
- Classes: `PascalCase` (e.g., `FundDiagnosis`, `DataSourceManager`)
- Functions/variables: `snake_case` (e.g., `get_fund_data`, `cache_ttl`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRY`, `DEFAULT_LLM`)
- Private: `_prefix` (e.g., `_internal_calc`)

**Type hints**: Required on all function signatures.

**Config**: Use `@dataclass(frozen=True)` for immutable config objects. No hardcoded hyperparameters.

**Error handling**: Catch specific exceptions, use `logging` (not `print`).

```python
import logging
logger = logging.getLogger(__name__)

try:
    data = provider.get_fund_data(code)
except ConnectionError as e:
    logger.error(f"Data provider failed for {code}: {e}")
    raise
```

**Prohibited**:
- `print()` for logging (use `logger`)
- Bare `except:`
- Mutable default arguments
- Hardcoded API keys or secrets
- Files exceeding 800 lines
- Nesting deeper than 4 levels

### TypeScript (Frontend)

**Naming**:
- Components: `PascalCase` (e.g., `FundCard`, `PortfolioTable`)
- Hooks: `camelCase` with `use` prefix (e.g., `useFundData`)
- Files: Component files `PascalCase.tsx`, utility files `camelCase.ts`
- Constants: `UPPER_SNAKE_CASE`

**Component structure**:
```tsx
// 1. Imports
// 2. Types/interfaces
// 3. Component definition (prefer function components)
// 4. Export
```

**State management**: Zustand for global state, React state for local UI state.

**API calls**: All through `web/src/api.ts`, never direct axios calls in components.

**i18n**: All user-facing strings through `useTranslation()`. No hardcoded Chinese/English text in components.

---

## API Conventions

- Prefix: `/api/` for all endpoints
- RESTful: `GET` (list/read), `POST` (create/action), `PUT` (update), `DELETE` (remove)
- Response model: Always use Pydantic models for request/response typing
- Error format: `{"detail": "error message"}` with appropriate HTTP status codes
- Router files: One per domain in `app/routers/`, registered in `app/main.py`

---

## Git Workflow

**Commit convention**: Conventional Commits
```
Type: feat, fix, docs, style, refactor, perf, test, chore
Scope: fund, stock, portfolio, llm, data, ui, api, config
```

**Branch strategy**:
- `main` - stable release
- `feat/*` - feature branches
- `fix/*` - bug fixes

**Merge**: Rebase for feature sync, merge --no-ff for integration.

---

## Environment & Security

- Secrets in `.env` only (gitignored). Never commit API keys.
- Use `os.environ` or `dotenv` to load secrets.
- `settings.json` contains sensitive tokens — excluded from Git.
- Sensitive file patterns: `.env*`, `*.pem`, `*.key`, `credentials.json`, `settings.json`

---

## Development Commands

```bash
# Backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend
cd web && npm run dev      # Dev server (port 5173)
cd web && npm run build    # Production build
cd web && npm run lint     # ESLint check

# Docker
docker-compose up -d --build   # Full deployment (port 9000)
```

---

## Task Completion Summary

After each task, provide:
```
Operation Review
1. [Main operation]
2. [Modified files]

Current Status
- [Git/filesystem/runtime status]

Next Steps
1. [Targeted suggestions]
```
