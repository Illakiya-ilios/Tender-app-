"""Overview_Store: thin sqlite3 persistence layer for the Dashboard.

Writes completed tenders and bid evaluations to a single local SQLite file so
the Dashboard overview survives process restarts. Uses only the Python standard
library ``sqlite3`` module (no ORM, no extra runtime dependency).

Connection strategy: short-lived connections opened per operation, each with
``row_factory = sqlite3.Row``. A per-call connection is confined to the calling
thread (safe under uvicorn's worker thread pool) and used inside a ``with conn:``
block that commits on success / rolls back on exception.

Error policy: these functions RAISE on real ``sqlite3`` errors. Swallowing a
failure (so generation/evaluation keep working) is the caller's responsibility.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from . import config

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    """Open a fresh connection to ``config.DB_PATH`` with Row access.

    ``config.DB_PATH`` is read at call time so tests can monkeypatch it.
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    """Return the current local time as an ISO-8601 string (second precision)."""
    return datetime.now().isoformat(timespec="seconds")


def init_db() -> None:
    """Create the ``tenders`` and ``evaluations`` tables if they do not exist."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenders (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name_of_work        TEXT,
                tender_reference_no TEXT,
                inviting_authority  TEXT,
                emd_amount          TEXT,
                completeness        INTEGER,
                generated_at        TEXT,
                pdf_filename        TEXT,
                pdf_url             TEXT,
                boq_filename        TEXT,
                boq_url             TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluations (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id                 TEXT UNIQUE,
                tender_reference_no    TEXT,
                bidders_count          INTEGER,
                complete_bids_count    INTEGER,
                best_match_bidder_id   TEXT,
                best_match_bidder_name TEXT,
                none_eligible          INTEGER,
                final_selection_bidder TEXT,
                released_at            TEXT,
                status                 TEXT
            )
            """
        )


def save_tender(record: dict) -> int:
    """Insert exactly one Tender_Record row and return its new ``id``.

    One row per call: regenerating the same reference yields a new row. Missing
    or empty keys are stored as empty strings, never rejected.
    """
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO tenders (
                name_of_work, tender_reference_no, inviting_authority, emd_amount,
                completeness, generated_at, pdf_filename, pdf_url, boq_filename, boq_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("name_of_work", ""),
                record.get("tender_reference_no", ""),
                record.get("inviting_authority", ""),
                record.get("emd_amount", ""),
                int(record.get("completeness", 0) or 0),
                record.get("generated_at", ""),
                record.get("pdf_filename", ""),
                record.get("pdf_url", ""),
                record.get("boq_filename", ""),
                record.get("boq_url", ""),
            ),
        )
        return int(cur.lastrowid)


def upsert_evaluation_scored(run) -> None:
    """Write/update the Evaluation_Record for a scored run, keyed by ``run_id``.

    On conflict, updates the summary fields and sets ``status = 'scored'`` but
    PRESERVES ``final_selection_bidder`` so a re-release after an award does not
    blank the awarded bidder.
    """
    bidders_count = len(run.bids)
    complete_bids = sum(1 for ev in run.evaluations if ev.completeness.complete)
    best_id, best_name = None, None
    sl = run.shortlist
    if sl.best_match_bid_id:
        match = next((e for e in sl.entries if e.bid_id == sl.best_match_bid_id), None)
        best_id = sl.best_match_bid_id
        best_name = match.bidder_name if match else ""
    released_at = run.created_at or _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO evaluations (
                run_id, tender_reference_no, bidders_count, complete_bids_count,
                best_match_bidder_id, best_match_bidder_name, none_eligible,
                released_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scored')
            ON CONFLICT(run_id) DO UPDATE SET
                tender_reference_no    = excluded.tender_reference_no,
                bidders_count          = excluded.bidders_count,
                complete_bids_count    = excluded.complete_bids_count,
                best_match_bidder_id   = excluded.best_match_bidder_id,
                best_match_bidder_name = excluded.best_match_bidder_name,
                none_eligible          = excluded.none_eligible,
                released_at            = excluded.released_at,
                status                 = 'scored'
            """,
            (
                run.run_id,
                run.tender.tender_reference_no,
                bidders_count,
                complete_bids,
                best_id,
                best_name,
                1 if sl.none_eligible else 0,
                released_at,
            ),
        )


def update_evaluation_awarded(run_id: str, bidder: str) -> None:
    """Record a final selection: set ``final_selection_bidder`` + ``status='awarded'``.

    If no row exists yet for ``run_id``, insert one with status ``'awarded'``.
    """
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO evaluations (run_id, final_selection_bidder, status)
            VALUES (?, ?, 'awarded')
            ON CONFLICT(run_id) DO UPDATE SET
                final_selection_bidder = excluded.final_selection_bidder,
                status                 = 'awarded'
            """,
            (run_id, bidder or ""),
        )


def list_tenders() -> list[dict]:
    """Return all Tender_Record rows, most recent ``generated_at`` first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tenders ORDER BY generated_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_evaluations() -> list[dict]:
    """Return all Evaluation_Record rows, most recent ``released_at`` first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM evaluations ORDER BY released_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def counts() -> dict:
    """Return cumulative Summary_Tile counts read from the Overview_Store."""
    with _connect() as conn:
        total_tenders = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        total_evaluations = conn.execute(
            "SELECT COUNT(*) FROM evaluations"
        ).fetchone()[0]
        awarded = conn.execute(
            "SELECT COUNT(*) FROM evaluations WHERE status = 'awarded'"
        ).fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM evaluations WHERE status = 'scored'"
        ).fetchone()[0]
    return {
        "total_tenders": total_tenders,
        "total_evaluations": total_evaluations,
        "awarded": awarded,
        "scored": scored,
    }
