# Implementation Plan: Persistent Overview Dashboard

## Overview

Convert the design for the persistent overview Dashboard into incremental coding steps. Each step builds on the previous one and keeps the app runnable/testable as it grows: first the config value, then the `store.py` persistence layer, then the three write-point integrations, then the dashboard routes, then the template/JS/CSS, and finally the sidebar repoint. Implementation language is **Python** (matching the existing FastAPI app and `sqlite3` stdlib design). Test subtasks are marked optional with `*`; non-test implementation tasks are never optional.

## Tasks

- [x] 1. Add `DB_PATH` configuration
  - In `tender_app/config.py`, add `DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"` after `EVAL_DIR`, matching the existing `Path` + `mkdir` style
  - Add `DB_PATH.parent.mkdir(parents=True, exist_ok=True)` so the `data/` parent directory is created before any connection
  - _Requirements: 2.1, 2.2, 2.3, 1.4_

- [x] 2. Implement the Overview_Store (`tender_app/store.py`)
  - [x] 2.1 Create module scaffold, connection helper, and timestamp helper
    - Create `tender_app/store.py` importing `sqlite3`, `logging`, `datetime`, and `from . import config`
    - Implement `_connect() -> sqlite3.Connection` opening `sqlite3.connect(config.DB_PATH)` with `row_factory = sqlite3.Row` (reads `config.DB_PATH` at call time so it is monkeypatch-friendly)
    - Implement `_now_iso()` returning `datetime.now().isoformat(timespec="seconds")`
    - Store functions raise on error; swallowing is the caller's responsibility
    - _Requirements: 1.1, 1.2, 6.3_

  - [x] 2.2 Implement `init_db()`
    - Call `config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)` defensively
    - Create `tenders` table if absent with columns: id PK AUTOINCREMENT, name_of_work, tender_reference_no, inviting_authority, emd_amount, completeness INTEGER, generated_at, pdf_filename, pdf_url, boq_filename, boq_url
    - Create `evaluations` table if absent with columns: id PK AUTOINCREMENT, run_id TEXT UNIQUE, tender_reference_no, bidders_count INTEGER, complete_bids_count INTEGER, best_match_bidder_id, best_match_bidder_name, none_eligible INTEGER, final_selection_bidder, released_at, status
    - _Requirements: 1.3, 1.4, 1.5, 1.6_

  - [ ]* 2.3 Write example test for init creating tables
    - Fixture monkeypatches `config.DB_PATH` to `tmp_path / "test.db"` then calls `store.init_db()`
    - Assert `sqlite_master` shows both `tenders` and `evaluations`; verify columns match the schema
    - _Requirements: 1.3, 1.5, 1.6_

  - [x] 2.4 Implement `save_tender(record: dict) -> int`
    - Insert exactly one row per call from `record.get(key, "")` (empty/missing stored as empty, never rejected); coerce `completeness` via `int(record.get("completeness", 0) or 0)`
    - Return `int(cur.lastrowid)`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.4_

  - [x] 2.5 Implement read functions `list_tenders()`, `list_evaluations()`, `counts()`
    - `list_tenders()` → `SELECT * FROM tenders ORDER BY generated_at DESC, id DESC` as list of dicts
    - `list_evaluations()` → `SELECT * FROM evaluations ORDER BY released_at DESC, id DESC` as list of dicts
    - `counts()` → dict with `total_tenders`, `total_evaluations`, `awarded`, `scored`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.5, 10.5, 11.3_

  - [ ]* 2.6 Write example test for `save_tender` + `list_tenders` newest-first
    - Insert three records with increasing `generated_at`; assert 3 rows returned newest-first echoing stored fields; a record with empty fields stores empty strings
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.4, 9.5, 11.3_

  - [x] 2.7 Implement `upsert_evaluation_scored(run) -> None`
    - Derive `bidders_count = len(run.bids)`, `complete_bids_count` = count of `run.evaluations` where `completeness.complete`
    - Resolve best-match id/name from `run.shortlist` (entry matching `best_match_bid_id`; name `""` if no match); `released_at = run.created_at or _now_iso()`
    - `INSERT ... ON CONFLICT(run_id) DO UPDATE` setting status `'scored'` and preserving `final_selection_bidder`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.3_

  - [x] 2.8 Implement `update_evaluation_awarded(run_id: str, bidder: str) -> None`
    - `INSERT (run_id, final_selection_bidder, status='awarded') ON CONFLICT(run_id) DO UPDATE` setting `final_selection_bidder` and status `'awarded'`
    - _Requirements: 4.7, 4.8, 5.2, 5.3_

  - [ ]* 2.9 Write example test for `upsert_evaluation_scored` field mapping + status 'scored'
    - Build a minimal hand-built `EvaluationRun` stand-in (two bids, some evaluations with `completeness.complete`, a shortlist with a `best_match_bid_id` + matching entry); assert `bidders_count`, `complete_bids_count`, `best_match_bidder_name`, `none_eligible`, `released_at`, and `status == 'scored'`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 2.10 Write example test for scored→awarded update in place (no duplicate)
    - `upsert_evaluation_scored(run)` then `update_evaluation_awarded(run.run_id, "ACME")`; assert exactly one row for the `run_id`, `status == 'awarded'`, `final_selection_bidder == "ACME"`, and scored summary fields preserved
    - _Requirements: 4.7, 5.1, 5.2, 5.3_

  - [ ]* 2.11 Write example test for award-with-no-prior-row inserts awarded
    - `update_evaluation_awarded("run-x", "ACME")` on an empty table → one row, `status == 'awarded'`
    - _Requirements: 4.8_

  - [ ]* 2.12 Write example test for `counts()` aggregation
    - Seed known tenders + a mix of scored/awarded evaluations; assert correct `total_tenders`, `total_evaluations`, `awarded`, `scored`; empty DB → all zero
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 2.13 Write property test for evaluation upsert idempotence
    - **Property 1: Evaluation upsert keyed by run_id never duplicates**
    - Use Hypothesis, 100+ iterations, generating a non-empty list of operation tags from `{"scored", "awarded"}` for a fixed `run_id`; apply each against a fresh temp DB using a lightweight hand-built `EvaluationRun` stand-in; assert exactly one row for the `run_id` and status is `'awarded'` if any awarded op occurred else `'scored'`
    - Test must include the exact tag line `# Feature: dashboard-landing, Property 1: Evaluation upsert keyed by run_id never duplicates`
    - Test must include the line `# Validates: Requirements 5.1, 5.2, 5.3`
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [ ] 3. Checkpoint - Ensure all store tests pass
  - Run `.venv\Scripts\python.exe -m pytest` and ensure all tests pass, ask the user if questions arise.

- [-] 4. Wire the Overview_Store into `tender_app/app.py` write points
  - [x] 4.1 Add store import, logging, and startup `init_db()`
    - `from . import store`; ensure `logging` is imported
    - After the `STATE` dict definition, call `store.init_db()` inside `try/except Exception` that logs a warning and continues (a DB init fault must not stop boot)
    - _Requirements: 1.3, 6.3_

  - [x] 4.2 Persist a Tender_Record in `api_generate` success path
    - Just before returning the result, when `"pdf_url" in result or "boq_url" in result`, call `store.save_tender({...})` built from `brief` (name_of_work, tender_reference_no, inviting_authority=`tender_inviting_authority`, emd_amount, completeness=`brief.completeness()`), `generated_at` as ISO now, and per-kind filename/url (empty when that kind was not produced)
    - Wrap the call in `try/except Exception` that logs a warning and continues; do not change the existing success response
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 6.1, 6.3, 6.4_

  - [x] 4.3 Upsert an Evaluation_Record in `api_eval_release`
    - After `pipeline.release_and_score(run)` + `audit.persist_run(run)`, call `store.upsert_evaluation_scored(run)` inside `try/except Exception` that logs a warning and continues; do not change the existing success response
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 6.2, 6.3, 6.4_

  - [x] 4.4 Update the Evaluation_Record to awarded in `api_eval_select`
    - After `audit.append_action(run, selection)`, resolve bidder name from the shortlist entry matching `run.final_selection.bid_id` (fall back to the bid id), then call `store.update_evaluation_awarded(run.run_id, bidder)` inside `try/except Exception` that logs a warning and continues; do not change the existing success response
    - _Requirements: 4.7, 4.8, 5.2, 6.2, 6.3, 6.4_

  - [ ]* 4.5 Write graceful-degradation test for generation
    - Monkeypatch `store.save_tender` to raise; assert `POST /api/generate` still returns a success result (no 500, `pdf_url`/`boq_url` present); apply the same idea for `upsert_evaluation_scored` on release and `update_evaluation_awarded` on select
    - _Requirements: 6.1, 6.2, 6.4_

- [ ] 5. Add the dashboard routes in `tender_app/app.py`
  - [x] 5.1 Implement `GET /dashboard`
    - Serve `templates/dashboard.html` via `(APP_DIR / "templates" / "dashboard.html").read_text(encoding="utf-8")`, matching the existing `index()` pattern; keep `GET /` and `GET /evaluation` unchanged
    - _Requirements: 7.1, 7.5_

  - [x] 5.2 Implement read-only `GET /api/dashboard`
    - Assemble `tiles = store.counts()`, `tenders = store.list_tenders()`, `evaluations = store.list_evaluations()` inside `try/except Exception` that logs and degrades to zeroed tiles + empty lists
    - Return JSON `{tiles, tenders, evaluations, empty: not tenders and not evaluations}`; write nothing
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 12.1_

  - [ ]* 5.3 Write route test for `GET /api/dashboard` shape, ordering, and no-mutation
    - Seed rows; assert response has `tiles` + `tenders` (newest `generated_at` first) + `evaluations` (newest `released_at` first) + `empty == false`; assert row counts are identical before and after the call; empty DB → `empty == true` and zeroed tiles
    - _Requirements: 10.5, 11.1, 11.2, 11.3, 11.4, 11.5, 12.1_

  - [ ]* 5.4 Write route test for pages served + sidebar active link
    - `GET /dashboard` → 200 HTML containing the sidebar and an active Dashboard link to `/dashboard`; `GET /` and `GET /evaluation` still return their existing pages
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 6. Checkpoint - Ensure all tests pass
  - Run `.venv\Scripts\python.exe -m pytest` and ensure all tests pass, ask the user if questions arise.

- [x] 7. Build the dashboard UI
  - [x] 7.1 Create `tender_app/templates/dashboard.html`
    - Copy the `.app-shell` + `nav.sidebar` + `.app-content` wrapper from `evaluation.html`; make the Dashboard nav link `class="active"` with `href="/dashboard"`
    - Add topbar, a `.tiles` block with 4 `.tile` elements (`#tile-total-tenders`, `#tile-total-evaluations`, `#tile-awarded`, `#tile-scored`)
    - Add `#content` with a Tenders `.card` + `table.dash-table#tenders-table` (tbody `#tenders-body`) and an Evaluations `.card` + `table.dash-table#evaluations-table` (tbody `#evaluations-body`)
    - Add a hidden `#empty-state` block with guidance and a link to `/` (Create a tender); include `<script src="/static/dashboard.js">`
    - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4, 9.1, 10.1, 12.1, 12.2, 12.3_

  - [x] 7.2 Create `tender_app/static/dashboard.js`
    - On `DOMContentLoaded`, `fetch("/api/dashboard")`; render the 4 tiles from `summary.tiles` (zero when empty)
    - Render Tenders rows: name_of_work, tender_reference_no, inviting_authority, date portion of generated_at, completeness (`.pill`), and PDF/BOQ `<a>` links when the stored urls are non-empty
    - Render Evaluations rows: tender_reference_no, date portion of released_at, bidders_count, complete_bids_count, best_match_bidder_name (or `—`), status `.badge` (`awarded`→`.yes`, `scored`→`.partly`), final_selection_bidder (or `—`), and a Details link to `/api/eval/audit/{run_id}` when `run_id` present; annotate best-match as "No eligible bid" when `none_eligible` is truthy
    - Toggle `#empty-state`/`#content` from `summary.empty`; escape all stored values before insertion; post nothing back
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.2, 9.3, 9.4, 10.2, 10.3, 10.4, 11.4, 12.1_

  - [x] 7.3 Append dashboard table styles to `tender_app/static/style.css`
    - Append `.dash-table`, `.dash-table th/td`, `.dash-table th`, and `.dash-empty` rules; reuse existing `.card`, `.tiles`, `.tile`, `.pill`, `.badge` as-is (no frontend framework)
    - _Requirements: 7.3_

- [x] 8. Repoint the sidebar Dashboard link
  - In `tender_app/templates/index.html`, change `<li><a href="/">Dashboard</a></li>` → `href="/dashboard"`
  - In `tender_app/templates/evaluation.html`, make the same change; leave all other nav links unchanged
  - _Requirements: 7.4_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Run `.venv\Scripts\python.exe -m pytest` and ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (test subtasks) and can be skipped for a faster MVP; non-test implementation tasks are never optional.
- Test isolation uses a temporary DB by monkeypatching `config.DB_PATH` to a `tmp_path` file and calling `store.init_db()`; every store function reads `config.DB_PATH` at call time, so this redirects all reads/writes.
- Checkpoints run `.venv\Scripts\python.exe -m pytest` (Windows, venv at `.venv`).
- The sole property test (2.13) covers Property 1 from the design; all other criteria are deterministic mappings/counts/ordering/route/UI behaviors covered by example and integration tests.
