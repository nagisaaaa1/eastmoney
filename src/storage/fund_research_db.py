"""
Persistence helpers for fund research workflow.

This module keeps research-specific tables isolated from the legacy storage
layer to avoid risky edits in large existing files.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.storage.db import get_db_connection


def _normalize_code(code: str) -> str:
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else str(code or "").strip()


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _from_json(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def ensure_fund_research_schema() -> None:
    """Create fund research tables if they do not exist."""
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_universe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            ts_code TEXT,
            name TEXT,
            fund_type TEXT,
            invest_type TEXT,
            market TEXT,
            management TEXT,
            found_date TEXT,
            m_fee REAL,
            c_fee REAL,
            is_index_fund INTEGER DEFAULT 0,
            is_etf INTEGER DEFAULT 0,
            is_linked INTEGER DEFAULT 0,
            is_dca_eligible INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            metadata_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, code)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            trade_date TEXT,
            snapshot_hash TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            source_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, fund_code, trade_date, snapshot_hash)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_scorecards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            trade_date TEXT,
            snapshot_hash TEXT,
            total_score REAL,
            quality_score REAL,
            risk_return_score REAL,
            valuation_score REAL,
            hard_filter_pass INTEGER DEFAULT 0,
            hard_filter_reasons TEXT,
            score_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendation_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            trade_date TEXT,
            snapshot_hash TEXT,
            action TEXT,
            suggested_amount REAL,
            confidence REAL,
            snapshot_id INTEGER,
            scorecard_id INTEGER,
            decision_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_review_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            trade_date TEXT,
            timing_score REAL,
            position_score REAL,
            risk_score REAL,
            discipline_score REAL,
            review_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_case_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            trade_date TEXT,
            outcome TEXT,
            market_state TEXT,
            strategy_version TEXT,
            summary TEXT,
            tags_json TEXT,
            payload_json TEXT,
            decision_id INTEGER,
            review_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_batch_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source TEXT DEFAULT 'manual',
            analysis_mode TEXT DEFAULT 'quick',
            status TEXT DEFAULT 'pending',
            total_count INTEGER DEFAULT 0,
            completed_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            cancelled_count INTEGER DEFAULT 0,
            input_json TEXT,
            context_json TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_batch_job_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            decision_id INTEGER,
            result_json TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, fund_code)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_context_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT,
            context_hash TEXT NOT NULL,
            context_json TEXT NOT NULL,
            source_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_dca_metrics_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            metric_date TEXT NOT NULL,
            avg_daily_amount_30d REAL DEFAULT 0,
            total_amount_30d REAL DEFAULT 0,
            active_days_30d INTEGER DEFAULT 0,
            tx_count_30d INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, fund_code, metric_date)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_dca_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            fund_name TEXT,
            amount_per_cycle REAL NOT NULL,
            frequency TEXT NOT NULL DEFAULT 'daily',
            execution_weekday INTEGER,
            execution_day INTEGER,
            start_date TEXT NOT NULL,
            end_date TEXT,
            next_run_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            auto_adjust INTEGER DEFAULT 1,
            max_daily_amount REAL,
            last_run_date TEXT,
            last_run_status TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fund_dca_plan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            planned_amount REAL NOT NULL,
            suggested_amount REAL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            context_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_universe_user_status ON fund_universe(user_id, status)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_universe_code ON fund_universe(code)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_snapshots_user_code ON fund_snapshots(user_id, fund_code, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_scorecards_user_code ON fund_scorecards(user_id, fund_code, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_reco_decisions_user_code ON recommendation_decisions(user_id, fund_code, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_review_user_code ON fund_review_records(user_id, fund_code, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_case_user_code ON fund_case_library(user_id, fund_code, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_case_filters ON fund_case_library(user_id, outcome, market_state, strategy_version)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_batch_jobs_user_created ON fund_batch_jobs(user_id, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_batch_items_job_status ON fund_batch_job_items(job_id, status)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_batch_items_user_code ON fund_batch_job_items(user_id, fund_code, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_context_user_code ON fund_context_snapshots(user_id, fund_code, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_dca_user_code_date ON fund_dca_metrics_daily(user_id, fund_code, metric_date DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_dca_plans_user_status ON fund_dca_plans(user_id, status, next_run_date)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_dca_plans_user_code ON fund_dca_plans(user_id, fund_code)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_dca_plan_runs_user_date ON fund_dca_plan_runs(user_id, scheduled_date DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_fund_dca_plan_runs_plan_id ON fund_dca_plan_runs(plan_id, created_at DESC)"
    )

    conn.commit()
    conn.close()


def upsert_fund_universe_items(user_id: int, items: List[Dict[str, Any]]) -> int:
    """Insert/update fund universe items for a user."""
    ensure_fund_research_schema()
    if not items:
        return 0

    conn = get_db_connection()
    c = conn.cursor()
    updated = 0

    for item in items:
        code = _normalize_code(item.get("code", ""))
        if not code:
            continue

        metadata_json = _to_json(item.get("metadata", {}))
        c.execute(
            """
            INSERT INTO fund_universe (
                user_id, code, ts_code, name, fund_type, invest_type, market,
                management, found_date, m_fee, c_fee, is_index_fund, is_etf,
                is_linked, is_dca_eligible, status, metadata_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, code) DO UPDATE SET
                ts_code=excluded.ts_code,
                name=excluded.name,
                fund_type=excluded.fund_type,
                invest_type=excluded.invest_type,
                market=excluded.market,
                management=excluded.management,
                found_date=excluded.found_date,
                m_fee=excluded.m_fee,
                c_fee=excluded.c_fee,
                is_index_fund=excluded.is_index_fund,
                is_etf=excluded.is_etf,
                is_linked=excluded.is_linked,
                is_dca_eligible=excluded.is_dca_eligible,
                status=excluded.status,
                metadata_json=excluded.metadata_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                user_id,
                code,
                item.get("ts_code"),
                item.get("name"),
                item.get("fund_type"),
                item.get("invest_type"),
                item.get("market"),
                item.get("management"),
                item.get("found_date"),
                item.get("m_fee"),
                item.get("c_fee"),
                int(bool(item.get("is_index_fund"))),
                int(bool(item.get("is_etf"))),
                int(bool(item.get("is_linked"))),
                int(bool(item.get("is_dca_eligible", True))),
                item.get("status", "active"),
                metadata_json,
            ),
        )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def mark_fund_universe_all_inactive(user_id: int) -> int:
    """Mark all universe rows as inactive for a user."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE fund_universe
        SET status = 'inactive', updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND status = 'active'
        """,
        (user_id,),
    )
    changed = int(c.rowcount or 0)
    conn.commit()
    conn.close()
    return changed


def set_fund_universe_status(
    user_id: int,
    codes: List[str],
    status: str = "inactive",
) -> int:
    """Update status for specific universe codes."""
    ensure_fund_research_schema()
    normalized = sorted({_normalize_code(code) for code in (codes or []) if _normalize_code(code)})
    if not normalized:
        return 0

    placeholders = ", ".join(["?" for _ in normalized])
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        f"""
        UPDATE fund_universe
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND code IN ({placeholders})
        """,
        (status, user_id, *normalized),
    )
    changed = int(c.rowcount or 0)
    conn.commit()
    conn.close()
    return changed


def get_fund_universe(
    user_id: int,
    active_only: bool = True,
    codes: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Get fund universe rows for a user."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    where = ["user_id = ?"]
    params: List[Any] = [user_id]

    if active_only:
        where.append("status = 'active'")

    if codes:
        normalized = [_normalize_code(code) for code in codes if _normalize_code(code)]
        if normalized:
            placeholders = ", ".join(["?" for _ in normalized])
            where.append(f"code IN ({placeholders})")
            params.extend(normalized)

    sql = (
        "SELECT * FROM fund_universe "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY is_index_fund DESC, is_dca_eligible DESC, code ASC"
    )
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()

    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _from_json(item.get("metadata_json"), {})
        result.append(item)
    return result


def get_missing_universe_codes(user_id: int, codes: List[str]) -> List[str]:
    """Return codes not currently present in user's candidate pool."""
    normalized = sorted({_normalize_code(code) for code in codes if _normalize_code(code)})
    if not normalized:
        return []

    existing = get_fund_universe(user_id=user_id, active_only=False, codes=normalized)
    existing_codes = {item["code"] for item in existing}
    return [code for code in normalized if code not in existing_codes]


def get_fund_universe_count(user_id: int, active_only: bool = True) -> int:
    """Get count of universe entries for a user."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    if active_only:
        row = conn.execute(
            "SELECT COUNT(*) FROM fund_universe WHERE user_id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM fund_universe WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    conn.close()
    return int(row[0] if row else 0)


def save_fund_snapshot(
    user_id: int,
    fund_code: str,
    trade_date: str,
    snapshot_hash: str,
    snapshot: Dict[str, Any],
    source: Dict[str, Any],
) -> int:
    """Persist an input snapshot and return snapshot id."""
    ensure_fund_research_schema()
    code = _normalize_code(fund_code)
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT OR IGNORE INTO fund_snapshots (
            user_id, fund_code, trade_date, snapshot_hash, snapshot_json, source_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            code,
            trade_date,
            snapshot_hash,
            _to_json(snapshot),
            _to_json(source),
        ),
    )

    row = conn.execute(
        """
        SELECT id FROM fund_snapshots
        WHERE user_id = ? AND fund_code = ? AND trade_date = ? AND snapshot_hash = ?
        ORDER BY id DESC LIMIT 1
        """,
        (user_id, code, trade_date, snapshot_hash),
    ).fetchone()

    conn.commit()
    conn.close()
    return int(row["id"]) if row else 0


def save_fund_scorecard(
    user_id: int,
    fund_code: str,
    trade_date: str,
    snapshot_hash: str,
    scorecard: Dict[str, Any],
) -> int:
    """Persist a scorecard and return scorecard id."""
    ensure_fund_research_schema()
    code = _normalize_code(fund_code)
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO fund_scorecards (
            user_id, fund_code, trade_date, snapshot_hash,
            total_score, quality_score, risk_return_score, valuation_score,
            hard_filter_pass, hard_filter_reasons, score_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            code,
            trade_date,
            snapshot_hash,
            scorecard.get("total_score"),
            scorecard.get("quality_score"),
            scorecard.get("risk_return_score"),
            scorecard.get("valuation_position_score"),
            int(bool(scorecard.get("hard_filter_pass"))),
            _to_json(scorecard.get("hard_filter_reasons", [])),
            _to_json(scorecard),
        ),
    )
    scorecard_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return scorecard_id


def save_recommendation_decision(
    user_id: int,
    fund_code: str,
    trade_date: str,
    snapshot_hash: str,
    action: str,
    suggested_amount: float,
    confidence: float,
    decision: Dict[str, Any],
    snapshot_id: Optional[int] = None,
    scorecard_id: Optional[int] = None,
) -> int:
    """Persist recommendation decision and return id."""
    ensure_fund_research_schema()
    code = _normalize_code(fund_code)
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO recommendation_decisions (
            user_id, fund_code, trade_date, snapshot_hash, action, suggested_amount,
            confidence, snapshot_id, scorecard_id, decision_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            code,
            trade_date,
            snapshot_hash,
            action,
            suggested_amount,
            confidence,
            snapshot_id,
            scorecard_id,
            _to_json(decision),
        ),
    )

    decision_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return decision_id


def get_latest_recommendation_decision(
    user_id: int,
    fund_code: str,
) -> Optional[Dict[str, Any]]:
    """Get latest persisted decision report for a fund code."""
    ensure_fund_research_schema()
    code = _normalize_code(fund_code)
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            rd.*,
            fs.score_json AS score_json,
            fs.total_score AS total_score,
            fs.quality_score AS quality_score,
            fs.risk_return_score AS risk_return_score,
            fs.valuation_score AS valuation_score,
            fs.hard_filter_pass AS hard_filter_pass,
            fs.hard_filter_reasons AS hard_filter_reasons,
            sn.snapshot_json AS snapshot_json,
            sn.source_json AS source_json
        FROM recommendation_decisions rd
        LEFT JOIN fund_scorecards fs ON rd.scorecard_id = fs.id
        LEFT JOIN fund_snapshots sn ON rd.snapshot_id = sn.id
        WHERE rd.user_id = ? AND rd.fund_code = ?
        ORDER BY rd.created_at DESC, rd.id DESC
        LIMIT 1
        """,
        (user_id, code),
    ).fetchone()
    conn.close()

    if not row:
        return None

    data = dict(row)
    data["decision"] = _from_json(data.get("decision_json"), {})
    data["scorecard"] = _from_json(data.get("score_json"), {})
    data["snapshot"] = _from_json(data.get("snapshot_json"), {})
    data["source"] = _from_json(data.get("source_json"), {})
    data["hard_filter_reasons"] = _from_json(data.get("hard_filter_reasons"), [])
    return data


def get_recommendation_decision_by_id(
    user_id: int,
    decision_id: int,
) -> Optional[Dict[str, Any]]:
    """Get a specific recommendation decision by id."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            rd.*,
            fs.score_json AS score_json,
            sn.snapshot_json AS snapshot_json,
            sn.source_json AS source_json
        FROM recommendation_decisions rd
        LEFT JOIN fund_scorecards fs ON rd.scorecard_id = fs.id
        LEFT JOIN fund_snapshots sn ON rd.snapshot_id = sn.id
        WHERE rd.user_id = ? AND rd.id = ?
        LIMIT 1
        """,
        (user_id, int(decision_id)),
    ).fetchone()
    conn.close()
    if not row:
        return None

    data = dict(row)
    data["decision"] = _from_json(data.get("decision_json"), {})
    data["scorecard"] = _from_json(data.get("score_json"), {})
    data["snapshot"] = _from_json(data.get("snapshot_json"), {})
    data["source"] = _from_json(data.get("source_json"), {})
    return data


def get_universe_last_updated(user_id: int) -> Optional[str]:
    """Get the latest update timestamp for a user's universe table."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    row = conn.execute(
        "SELECT MAX(updated_at) AS latest FROM fund_universe WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return row["latest"]


def save_fund_review_record(
    user_id: int,
    fund_code: str,
    trade_date: str,
    *,
    timing_score: float,
    position_score: float,
    risk_score: float,
    discipline_score: float,
    review: Dict[str, Any],
) -> int:
    """Persist review scoring result and return record id."""
    ensure_fund_research_schema()
    code = _normalize_code(fund_code)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO fund_review_records (
            user_id, fund_code, trade_date, timing_score, position_score,
            risk_score, discipline_score, review_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            code,
            trade_date,
            timing_score,
            position_score,
            risk_score,
            discipline_score,
            _to_json(review),
        ),
    )
    review_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return review_id


def get_fund_review_records(
    user_id: int,
    *,
    fund_code: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Read review records for a user/fund."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    where = ["user_id = ?"]
    params: List[Any] = [user_id]
    if fund_code:
        where.append("fund_code = ?")
        params.append(_normalize_code(fund_code))
    sql = (
        "SELECT * FROM fund_review_records "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC, id DESC LIMIT ?"
    )
    params.append(max(1, min(limit, 500)))
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()

    data: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["review"] = _from_json(item.get("review_json"), {})
        data.append(item)
    return data


def save_case_library_entry(
    user_id: int,
    fund_code: str,
    trade_date: str,
    *,
    outcome: str,
    market_state: Optional[str],
    strategy_version: str,
    summary: str,
    tags: List[str],
    payload: Dict[str, Any],
    decision_id: Optional[int] = None,
    review_id: Optional[int] = None,
) -> int:
    """Persist one case-library entry and return id."""
    ensure_fund_research_schema()
    code = _normalize_code(fund_code)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO fund_case_library (
            user_id, fund_code, trade_date, outcome, market_state, strategy_version,
            summary, tags_json, payload_json, decision_id, review_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            code,
            trade_date,
            outcome,
            market_state,
            strategy_version,
            summary,
            _to_json(tags),
            _to_json(payload),
            decision_id,
            review_id,
        ),
    )
    case_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return case_id


def get_case_library_entries(
    user_id: int,
    *,
    fund_code: Optional[str] = None,
    outcome: Optional[str] = None,
    market_state: Optional[str] = None,
    strategy_version: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Search case library entries with lightweight filters."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    where = ["user_id = ?"]
    params: List[Any] = [user_id]
    if fund_code:
        where.append("fund_code = ?")
        params.append(_normalize_code(fund_code))
    if outcome:
        where.append("outcome = ?")
        params.append(str(outcome))
    if market_state:
        where.append("market_state = ?")
        params.append(str(market_state))
    if strategy_version:
        where.append("strategy_version = ?")
        params.append(str(strategy_version))

    sql = (
        "SELECT * FROM fund_case_library "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC, id DESC LIMIT ?"
    )
    params.append(max(1, min(limit, 500)))
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()

    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["tags"] = _from_json(item.get("tags_json"), [])
        item["payload"] = _from_json(item.get("payload_json"), {})
        result.append(item)
    return result


def create_batch_job(
    user_id: int,
    *,
    source: str,
    analysis_mode: str,
    codes: List[str],
    input_payload: Optional[Dict[str, Any]] = None,
    context_payload: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
) -> int:
    """Create a batch research job and its item rows."""
    ensure_fund_research_schema()
    normalized_codes = [
        _normalize_code(code) for code in codes if _normalize_code(code)
    ]
    if not normalized_codes:
        raise ValueError("codes cannot be empty")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO fund_batch_jobs (
            user_id, source, analysis_mode, status, total_count,
            input_json, context_json, message, created_at, updated_at
        ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            user_id,
            str(source or "manual"),
            str(analysis_mode or "quick"),
            len(normalized_codes),
            _to_json(input_payload or {}),
            _to_json(context_payload or {}),
            message,
        ),
    )
    job_id = int(c.lastrowid)

    for code in normalized_codes:
        c.execute(
            """
            INSERT OR IGNORE INTO fund_batch_job_items (
                user_id, job_id, fund_code, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (user_id, job_id, code),
        )

    conn.commit()
    conn.close()
    return job_id


def _parse_batch_job_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["input"] = _from_json(item.get("input_json"), {})
    item["context"] = _from_json(item.get("context_json"), {})
    return item


def _parse_batch_item_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["result"] = _from_json(item.get("result_json"), {})
    return item


def get_batch_job(
    user_id: int,
    job_id: int,
    *,
    include_items: bool = True,
) -> Optional[Dict[str, Any]]:
    """Get one batch job and optionally all item rows."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    job_row = conn.execute(
        "SELECT * FROM fund_batch_jobs WHERE id = ? AND user_id = ? LIMIT 1",
        (int(job_id), user_id),
    ).fetchone()
    if not job_row:
        conn.close()
        return None

    job = _parse_batch_job_row(dict(job_row))
    if include_items:
        rows = conn.execute(
            """
            SELECT * FROM fund_batch_job_items
            WHERE job_id = ? AND user_id = ?
            ORDER BY id ASC
            """,
            (int(job_id), user_id),
        ).fetchall()
        job["items"] = [_parse_batch_item_row(dict(row)) for row in rows]
    conn.close()
    return job


def list_batch_jobs(
    user_id: int,
    *,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """List latest batch jobs for a user."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT * FROM fund_batch_jobs
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, max(1, min(limit, 200))),
    ).fetchall()
    conn.close()
    return [_parse_batch_job_row(dict(row)) for row in rows]


def update_batch_job_status(
    user_id: int,
    job_id: int,
    *,
    status: str,
    message: Optional[str] = None,
    started: bool = False,
    finished: bool = False,
    reset_timestamps: bool = False,
) -> bool:
    """Update high-level job status."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    c = conn.cursor()

    set_clauses = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    params: List[Any] = [status]
    if reset_timestamps:
        set_clauses.append("started_at = NULL")
        set_clauses.append("finished_at = NULL")
    if message is not None:
        set_clauses.append("message = ?")
        params.append(message)
    if started:
        set_clauses.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    if finished:
        set_clauses.append("finished_at = CURRENT_TIMESTAMP")

    params.extend([int(job_id), user_id])
    c.execute(
        f"""
        UPDATE fund_batch_jobs
        SET {', '.join(set_clauses)}
        WHERE id = ? AND user_id = ?
        """,
        tuple(params),
    )
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def update_batch_job_item(
    user_id: int,
    job_id: int,
    fund_code: str,
    *,
    status: str,
    decision_id: Optional[int] = None,
    result: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    started: bool = False,
    finished: bool = False,
) -> bool:
    """Update one item row in a batch job."""
    ensure_fund_research_schema()
    normalized_code = _normalize_code(fund_code)
    conn = get_db_connection()
    c = conn.cursor()

    set_clauses = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    params: List[Any] = [status]
    if decision_id is not None:
        set_clauses.append("decision_id = ?")
        params.append(int(decision_id))
    if result is not None:
        set_clauses.append("result_json = ?")
        params.append(_to_json(result))
    if error_message is not None:
        set_clauses.append("error_message = ?")
        params.append(error_message)
    if started:
        set_clauses.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    if finished:
        set_clauses.append("finished_at = CURRENT_TIMESTAMP")

    params.extend([int(job_id), user_id, normalized_code])
    c.execute(
        f"""
        UPDATE fund_batch_job_items
        SET {', '.join(set_clauses)}
        WHERE job_id = ? AND user_id = ? AND fund_code = ?
        """,
        tuple(params),
    )
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def reset_failed_batch_items(user_id: int, job_id: int) -> int:
    """Reset failed item rows to pending for retry."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE fund_batch_job_items
        SET status = 'pending',
            error_message = NULL,
            result_json = NULL,
            decision_id = NULL,
            started_at = NULL,
            finished_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND job_id = ? AND status = 'failed'
        """,
        (user_id, int(job_id)),
    )
    changed = int(c.rowcount or 0)
    conn.commit()
    conn.close()
    return changed


def cancel_batch_job_items(user_id: int, job_id: int) -> int:
    """Mark pending/running items as cancelled."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE fund_batch_job_items
        SET status = 'cancelled',
            error_message = COALESCE(error_message, 'job_cancelled'),
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND job_id = ? AND status IN ('pending', 'running')
        """,
        (user_id, int(job_id)),
    )
    changed = int(c.rowcount or 0)
    conn.commit()
    conn.close()
    return changed


def compute_batch_job_counters(user_id: int, job_id: int) -> Dict[str, int]:
    """Compute and persist latest item counters on the job row."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count
        FROM fund_batch_job_items
        WHERE user_id = ? AND job_id = ?
        """,
        (user_id, int(job_id)),
    ).fetchone()

    counters = {
        "total_count": int((row["total_count"] or 0) if row else 0),
        "completed_count": int((row["completed_count"] or 0) if row else 0),
        "failed_count": int((row["failed_count"] or 0) if row else 0),
        "cancelled_count": int((row["cancelled_count"] or 0) if row else 0),
    }

    conn.execute(
        """
        UPDATE fund_batch_jobs
        SET total_count = ?,
            completed_count = ?,
            failed_count = ?,
            cancelled_count = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (
            counters["total_count"],
            counters["completed_count"],
            counters["failed_count"],
            counters["cancelled_count"],
            int(job_id),
            user_id,
        ),
    )
    conn.commit()
    conn.close()
    return counters


def save_context_snapshot(
    user_id: int,
    *,
    context_hash: str,
    context: Dict[str, Any],
    source: Optional[Dict[str, Any]] = None,
    fund_code: Optional[str] = None,
) -> int:
    """Persist one decision-context snapshot and return row id."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO fund_context_snapshots (
            user_id, fund_code, context_hash, context_json, source_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            _normalize_code(fund_code) if fund_code else None,
            context_hash,
            _to_json(context or {}),
            _to_json(source or {}),
        ),
    )
    snapshot_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return snapshot_id


def get_latest_context_snapshot(
    user_id: int,
    *,
    fund_code: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Get latest context snapshot (fund-scoped or global)."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    if fund_code:
        row = conn.execute(
            """
            SELECT * FROM fund_context_snapshots
            WHERE user_id = ? AND fund_code = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, _normalize_code(fund_code)),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM fund_context_snapshots
            WHERE user_id = ? AND fund_code IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    result["context"] = _from_json(result.get("context_json"), {})
    result["source"] = _from_json(result.get("source_json"), {})
    return result


def upsert_dca_metric_daily(
    user_id: int,
    fund_code: str,
    metric_date: str,
    *,
    avg_daily_amount_30d: float,
    total_amount_30d: float,
    active_days_30d: int,
    tx_count_30d: int,
) -> int:
    """Upsert one 30-day DCA metric row."""
    ensure_fund_research_schema()
    code = _normalize_code(fund_code)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO fund_dca_metrics_daily (
            user_id, fund_code, metric_date, avg_daily_amount_30d,
            total_amount_30d, active_days_30d, tx_count_30d, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, fund_code, metric_date) DO UPDATE SET
            avg_daily_amount_30d = excluded.avg_daily_amount_30d,
            total_amount_30d = excluded.total_amount_30d,
            active_days_30d = excluded.active_days_30d,
            tx_count_30d = excluded.tx_count_30d,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            code,
            metric_date,
            float(avg_daily_amount_30d),
            float(total_amount_30d),
            int(active_days_30d),
            int(tx_count_30d),
        ),
    )
    conn.commit()
    conn.close()
    return 1


def get_latest_dca_metric_daily(
    user_id: int,
    fund_code: str,
) -> Optional[Dict[str, Any]]:
    """Read latest cached 30-day DCA metric for a fund."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT * FROM fund_dca_metrics_daily
        WHERE user_id = ? AND fund_code = ?
        ORDER BY metric_date DESC, id DESC
        LIMIT 1
        """,
        (user_id, _normalize_code(fund_code)),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_dca_plan(user_id: int, plan: Dict[str, Any]) -> int:
    """Create one DCA/SIP plan row."""
    ensure_fund_research_schema()
    code = _normalize_code(plan.get("fund_code", ""))
    if not code:
        raise ValueError("invalid fund code")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO fund_dca_plans (
            user_id, fund_code, fund_name, amount_per_cycle, frequency,
            execution_weekday, execution_day, start_date, end_date, next_run_date,
            status, auto_adjust, max_daily_amount, metadata_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            user_id,
            code,
            plan.get("fund_name"),
            float(plan.get("amount_per_cycle") or 0.0),
            str(plan.get("frequency") or "daily"),
            plan.get("execution_weekday"),
            plan.get("execution_day"),
            str(plan.get("start_date")),
            plan.get("end_date"),
            str(plan.get("next_run_date")),
            str(plan.get("status") or "active"),
            int(bool(plan.get("auto_adjust", True))),
            plan.get("max_daily_amount"),
            _to_json(plan.get("metadata", {})),
        ),
    )
    plan_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return plan_id


def update_dca_plan(
    user_id: int,
    plan_id: int,
    updates: Dict[str, Any],
) -> bool:
    """Update one DCA/SIP plan row."""
    ensure_fund_research_schema()
    if not updates:
        return False

    set_clauses: List[str] = []
    params: List[Any] = []

    mapping = {
        "fund_name": "fund_name",
        "amount_per_cycle": "amount_per_cycle",
        "frequency": "frequency",
        "execution_weekday": "execution_weekday",
        "execution_day": "execution_day",
        "start_date": "start_date",
        "end_date": "end_date",
        "next_run_date": "next_run_date",
        "status": "status",
        "auto_adjust": "auto_adjust",
        "max_daily_amount": "max_daily_amount",
        "last_run_date": "last_run_date",
        "last_run_status": "last_run_status",
    }
    for key, col in mapping.items():
        if key not in updates:
            continue
        val = updates.get(key)
        if key in {"amount_per_cycle", "max_daily_amount"} and val is not None:
            val = float(val)
        if key in {"auto_adjust"} and val is not None:
            val = int(bool(val))
        set_clauses.append(f"{col} = ?")
        params.append(val)

    if "metadata" in updates:
        set_clauses.append("metadata_json = ?")
        params.append(_to_json(updates.get("metadata") or {}))

    if not set_clauses:
        return False

    set_clauses.append("updated_at = CURRENT_TIMESTAMP")

    conn = get_db_connection()
    c = conn.cursor()
    params.extend([int(plan_id), user_id])
    c.execute(
        f"""
        UPDATE fund_dca_plans
        SET {', '.join(set_clauses)}
        WHERE id = ? AND user_id = ?
        """,
        tuple(params),
    )
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def _parse_dca_plan_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["metadata"] = _from_json(item.get("metadata_json"), {})
    item["auto_adjust"] = bool(item.get("auto_adjust"))
    return item


def list_dca_plans(
    user_id: int,
    *,
    status: Optional[str] = None,
    fund_code: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """List DCA/SIP plans for one user."""
    ensure_fund_research_schema()
    where = ["user_id = ?"]
    params: List[Any] = [user_id]
    if status:
        where.append("status = ?")
        params.append(str(status))
    if fund_code:
        where.append("fund_code = ?")
        params.append(_normalize_code(fund_code))

    params.append(max(1, min(limit, 1000)))

    conn = get_db_connection()
    rows = conn.execute(
        f"""
        SELECT * FROM fund_dca_plans
        WHERE {' AND '.join(where)}
        ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, updated_at DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    conn.close()
    return [_parse_dca_plan_row(dict(row)) for row in rows]


def get_dca_plan(user_id: int, plan_id: int) -> Optional[Dict[str, Any]]:
    """Get one DCA/SIP plan by id."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT * FROM fund_dca_plans
        WHERE id = ? AND user_id = ?
        LIMIT 1
        """,
        (int(plan_id), user_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_dca_plan_row(dict(row))


def create_dca_plan_run(
    *,
    user_id: int,
    plan_id: int,
    fund_code: str,
    scheduled_date: str,
    planned_amount: float,
    suggested_amount: Optional[float],
    status: str,
    context: Optional[Dict[str, Any]] = None,
) -> int:
    """Insert one DCA/SIP run/simulation record."""
    ensure_fund_research_schema()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO fund_dca_plan_runs (
            plan_id, user_id, fund_code, scheduled_date, planned_amount,
            suggested_amount, status, context_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(plan_id),
            user_id,
            _normalize_code(fund_code),
            str(scheduled_date),
            float(planned_amount),
            float(suggested_amount) if suggested_amount is not None else None,
            str(status),
            _to_json(context or {}),
        ),
    )
    run_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return run_id


def list_dca_plan_runs(
    user_id: int,
    *,
    plan_id: Optional[int] = None,
    fund_code: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """List DCA/SIP run history."""
    ensure_fund_research_schema()
    where = ["user_id = ?"]
    params: List[Any] = [user_id]
    if plan_id is not None:
        where.append("plan_id = ?")
        params.append(int(plan_id))
    if fund_code:
        where.append("fund_code = ?")
        params.append(_normalize_code(fund_code))
    params.append(max(1, min(limit, 1000)))

    conn = get_db_connection()
    rows = conn.execute(
        f"""
        SELECT * FROM fund_dca_plan_runs
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    conn.close()

    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["context"] = _from_json(item.get("context_json"), {})
        result.append(item)
    return result


def get_planned_dca_amount(
    user_id: int,
    target_date: str,
    *,
    fund_code: Optional[str] = None,
) -> float:
    """Get sum(planned amount) of active plans scheduled on target_date."""
    ensure_fund_research_schema()
    where = [
        "user_id = ?",
        "status = 'active'",
        "date(next_run_date) = date(?)",
    ]
    params: List[Any] = [user_id, str(target_date)]
    if fund_code:
        where.append("fund_code = ?")
        params.append(_normalize_code(fund_code))

    conn = get_db_connection()
    row = conn.execute(
        f"""
        SELECT SUM(COALESCE(amount_per_cycle, 0)) AS total
        FROM fund_dca_plans
        WHERE {' AND '.join(where)}
        """,
        tuple(params),
    ).fetchone()
    conn.close()
    return float((row["total"] or 0.0) if row else 0.0)
