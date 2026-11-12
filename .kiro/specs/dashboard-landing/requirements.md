# Requirements Document

## Introduction

This feature adds a **persistent overview Dashboard** to the existing AI-Powered Tender Document Builder (Python + FastAPI + server-rendered HTML + vanilla JS). Unlike the live workflow pages, the Dashboard is a data/overview page: it lists **all tenders that have been generated** and **all bid evaluations that have been scored or awarded**, as durable records read from a small local database.

The application currently holds a single session in an in-memory `STATE` dict that resets on restart, so nothing survives across sessions. This feature introduces lightweight persistence using the Python standard library `sqlite3` module writing to a single local database file. Records are written at the two natural completion points in the existing flows:

- A **Tender record** is written when `POST /api/generate` successfully produces the PDF and/or BOQ.
- An **Evaluation record** is written when `POST /api/eval/release` scores a run, and is updated when `POST /api/eval/select` records a final selection.

Drafts and in-progress work are **not** persisted; the Dashboard shows completed records only. Reading the Dashboard never mutates records. Writing a record must never break tender generation or evaluation: database failures are logged and the surrounding flow continues (graceful degradation).

The Dashboard is served at `GET /dashboard` (routing Option A: `GET /` remains the tender builder, `GET /evaluation` is unchanged, and the sidebar "Dashboard" link is repointed to `/dashboard`). It reuses the existing shared left sidebar and visual style (navy `#1F3864`, orange `#e07b00`, green `#1a7a46`, white cards, `.card` / `.tile` / `.pill` / badge classes) and introduces no frontend framework. The existing evaluation audit JSON written to `config.EVAL_DIR` by `audit.persist_run` is retained; the new database row is a lightweight summary/index that links back to that audit record, not a replacement for it.

## Glossary

- **Dashboard**: The persistent overview page served at `GET /dashboard`. The system scope of most requirements below.
- **Overview_Store**: The persistence layer backed by a single local SQLite database file, accessed via the Python standard library `sqlite3` module. Holds the `tenders` and `evaluations` tables.
- **DB_Path**: The configured filesystem path to the SQLite database file, defined in `tender_app/config.py` as `DB_PATH`.
- **Tender_Record**: A persisted row summarizing one successfully generated tender. Fields: id, name_of_work, tender_reference_no, inviting_authority, emd_amount, completeness, generated_at timestamp, pdf filename/url, boq filename/url.
- **Evaluation_Record**: A persisted row summarizing one scored or awarded bid evaluation. Fields: id, run_id, tender_reference_no, bidders_count, complete_bids_count, best_match bidder name/id, none_eligible flag, final_selection bidder, released_at timestamp, status.
- **Generate_Route**: The existing `POST /api/generate` handler (`api_generate`) that produces the PDF/BOQ. The Tender_Record write point.
- **Release_Route**: The existing `POST /api/eval/release` handler (`api_eval_release`) that scores a run and calls `audit.persist_run`. The Evaluation_Record create/update point for scoring.
- **Select_Route**: The existing `POST /api/eval/select` handler (`api_eval_select`) that records a final selection. The Evaluation_Record update point for awarding.
- **Tender_Brief**: The `TenderBrief` object (`tender_app/models.py`) exposing `name_of_work`, `tender_reference_no`, `tender_inviting_authority`, `emd_amount`, and `completeness()`.
- **Evaluation_Run**: The `EvaluationRun` object (`tender_app/evaluation/models.py`) exposing `run_id`, `created_at`, `tender`, `evaluations`, `shortlist` (`best_match_bid_id`, `none_eligible`, `entries`), and `final_selection`.
- **Audit_Record**: The existing per-run JSON file written to `config.EVAL_DIR` by `audit.persist_run`, reachable via `GET /api/eval/audit/{run_id}`.
- **Dashboard_API**: The JSON endpoint `GET /api/dashboard` that assembles tiles, the tender list, and the evaluation list by reading the Overview_Store.
- **Summary_Tile**: A compact card at the top of the Dashboard showing one cumulative count from the Overview_Store.
- **Awarded**: The Evaluation_Record status indicating a final selection has been recorded (`status = "awarded"`).
- **Scored**: The Evaluation_Record status indicating scoring has been released but no final selection has been recorded (`status = "scored"`).
- **Empty_State**: The Dashboard presentation shown when the Overview_Store contains no Tender_Record and no Evaluation_Record.
- **Officer**: The single user of the application.
- **Tender_Builder_Page**: The existing page served at `GET /`.
- **Evaluation_Page**: The existing page served at `GET /evaluation`.

## Requirements

### Requirement 1: SQLite Persistence Store

**User Story:** As an Officer, I want completed tenders and evaluations stored durably, so that my overview survives across sessions and process restarts.

#### Acceptance Criteria

1. THE Overview_Store SHALL persist records in a single SQLite database file located at DB_Path.
2. THE Overview_Store SHALL access the database using the Python standard library `sqlite3` module without introducing an ORM or additional runtime dependency.
3. WHEN the application starts, THE Overview_Store SHALL create the `tenders` table and the `evaluations` table if they do not already exist.
4. WHEN the application starts AND DB_Path references a directory that does not exist, THE Overview_Store SHALL create the parent directory before opening the database.
5. THE `tenders` table SHALL store the Tender_Record fields: id, name_of_work, tender_reference_no, inviting_authority, emd_amount, completeness, generated_at, pdf_filename, pdf_url, boq_filename, boq_url.
6. THE `evaluations` table SHALL store the Evaluation_Record fields: id, run_id, tender_reference_no, bidders_count, complete_bids_count, best_match_bidder_id, best_match_bidder_name, none_eligible, final_selection_bidder, released_at, status.

### Requirement 2: Configuration of the Database Path

**User Story:** As an Officer deploying the app, I want the database location configurable, so that I control where overview data is stored.

#### Acceptance Criteria

1. THE configuration module `tender_app/config.py` SHALL define DB_Path as a configurable value with a default under the application directory (for example `tender_app/data/app.db`).
2. WHERE DB_Path is provided through application configuration, THE Overview_Store SHALL use the configured DB_Path.
3. WHERE DB_Path is not provided through application configuration, THE Overview_Store SHALL use the default DB_Path.

### Requirement 3: Persist a Tender Record on Successful Generation

**User Story:** As an Officer, I want a tender recorded when I generate it, so that every generated tender appears in the overview.

#### Acceptance Criteria

1. WHEN the Generate_Route successfully produces the PDF or the BOQ, THE Generate_Route SHALL write a Tender_Record to the Overview_Store.
2. WHEN a Tender_Record is written, THE Overview_Store SHALL store name_of_work, tender_reference_no, inviting_authority, and emd_amount from the Tender_Brief.
3. WHEN a Tender_Record is written, THE Overview_Store SHALL store the completeness value obtained from `Tender_Brief.completeness()`.
4. WHEN a Tender_Record is written, THE Overview_Store SHALL store the generated_at timestamp as the time of generation.
5. WHEN the Generate_Route produces a PDF, THE Overview_Store SHALL store the PDF filename and PDF download url in the Tender_Record.
6. WHEN the Generate_Route produces a BOQ, THE Overview_Store SHALL store the BOQ filename and BOQ download url in the Tender_Record.
7. IF a Tender_Brief field required for a Tender_Record is empty, THEN THE Overview_Store SHALL store an empty value for that field without rejecting the Tender_Record.
8. THE Overview_Store SHALL insert one Tender_Record per successful generation event, ordered so that the most recent generation is retrievable first.

### Requirement 4: Persist and Update an Evaluation Record on Release and Selection

**User Story:** As an Officer, I want an evaluation recorded when it is scored and updated when awarded, so that the overview reflects the current state of each evaluation.

#### Acceptance Criteria

1. WHEN the Release_Route scores an Evaluation_Run, THE Release_Route SHALL write an Evaluation_Record to the Overview_Store with status Scored.
2. WHEN an Evaluation_Record is written, THE Overview_Store SHALL store the Evaluation_Run `run_id` and the linked tender_reference_no from the Evaluation_Run tender.
3. WHEN an Evaluation_Record is written, THE Overview_Store SHALL store the bidders_count and the complete_bids_count derived from the Evaluation_Run evaluations.
4. WHEN an Evaluation_Run shortlist has a non-empty `best_match_bid_id`, THE Overview_Store SHALL store the best-match bidder id and bidder name in the Evaluation_Record.
5. WHEN an Evaluation_Run shortlist has `none_eligible` set to true, THE Overview_Store SHALL store the none_eligible flag as true in the Evaluation_Record.
6. WHEN an Evaluation_Record is written, THE Overview_Store SHALL store the released_at timestamp from the Evaluation_Run `created_at` or the time of release.
7. WHEN the Select_Route records a final selection for an Evaluation_Run, THE Overview_Store SHALL update the existing Evaluation_Record for that `run_id` with the final_selection bidder and set the status to Awarded.
8. IF no Evaluation_Record exists for the `run_id` at the time of final selection, THEN THE Overview_Store SHALL insert an Evaluation_Record for that `run_id` with the final_selection bidder and status Awarded.

### Requirement 5: Idempotent Writes Keyed by Identity

**User Story:** As an Officer, I want re-running an action to update the existing record, so that the overview does not accumulate duplicate evaluation rows.

#### Acceptance Criteria

1. WHEN the Release_Route scores an Evaluation_Run whose `run_id` already has an Evaluation_Record, THE Overview_Store SHALL update the existing Evaluation_Record rather than insert a duplicate.
2. WHEN the Select_Route records a final selection for an Evaluation_Run whose `run_id` already has an Evaluation_Record, THE Overview_Store SHALL update the existing Evaluation_Record rather than insert a duplicate.
3. THE Overview_Store SHALL treat `run_id` as the unique key identifying an Evaluation_Record.
4. THE Overview_Store SHALL insert one Tender_Record per generation event, so that regenerating a tender with the same tender_reference_no produces a new Tender_Record and the most recent generation is shown first.

### Requirement 6: Graceful Degradation on Persistence Failure

**User Story:** As an Officer, I want generation and evaluation to keep working even if the database fails, so that a storage problem never blocks my core tasks.

#### Acceptance Criteria

1. IF writing a Tender_Record fails, THEN THE Generate_Route SHALL complete the generation response without raising an error to the Officer.
2. IF writing or updating an Evaluation_Record fails, THEN THE Release_Route and THE Select_Route SHALL complete their responses without raising an error to the Officer.
3. WHEN a persistence operation fails, THE Overview_Store SHALL log the failure.
4. THE Overview_Store write operations SHALL NOT change the existing success behavior of the Generate_Route, the Release_Route, or the Select_Route when persistence succeeds.

### Requirement 7: Dashboard Route and Page

**User Story:** As an Officer, I want a dashboard page I can open from the sidebar, so that I have one overview of all completed tenders and evaluations.

#### Acceptance Criteria

1. WHEN an Officer requests `GET /dashboard`, THE Dashboard SHALL return the overview page as server-rendered HTML.
2. THE Dashboard SHALL render the existing shared left sidebar using the existing navigation structure and visual style.
3. THE Dashboard SHALL render using the existing `static/style.css` styles, including the `.card`, `.tile`, `.pill`, and badge classes, without introducing a frontend framework.
4. WHEN the sidebar "Dashboard" link is displayed on any page, THE sidebar SHALL point the "Dashboard" link at `GET /dashboard`.
5. THE application SHALL keep `GET /` serving the Tender_Builder_Page and `GET /evaluation` serving the Evaluation_Page unchanged in behavior.

### Requirement 8: Dashboard Summary Tiles

**User Story:** As an Officer, I want headline tiles summarizing my stored records, so that I can gauge cumulative progress at a glance.

#### Acceptance Criteria

1. THE Dashboard SHALL display a Summary_Tile for the total number of Tender_Record rows in the Overview_Store.
2. THE Dashboard SHALL display a Summary_Tile for the total number of Evaluation_Record rows in the Overview_Store.
3. THE Dashboard SHALL display a Summary_Tile for the number of Evaluation_Record rows whose status is Awarded.
4. THE Dashboard SHALL display a Summary_Tile for the number of Evaluation_Record rows whose status is Scored.
5. THE Dashboard SHALL compute each Summary_Tile value as a cumulative count read from the Overview_Store.
6. WHERE the Overview_Store contains no rows for a Summary_Tile metric, THE Dashboard SHALL display zero for that Summary_Tile.

### Requirement 9: Tenders Section

**User Story:** As an Officer, I want to see all generated tenders listed, so that I can review and download any past tender.

#### Acceptance Criteria

1. THE Dashboard SHALL display a Tenders section listing every Tender_Record in the Overview_Store.
2. THE Dashboard SHALL display for each Tender_Record the name_of_work, tender_reference_no, inviting_authority, generated_at date, and completeness.
3. WHEN a Tender_Record has a stored PDF url, THE Dashboard SHALL display a link to download the PDF.
4. WHEN a Tender_Record has a stored BOQ url, THE Dashboard SHALL display a link to download the BOQ.
5. THE Dashboard SHALL order the Tenders section with the most recent generated_at first.

### Requirement 10: Evaluations Section

**User Story:** As an Officer, I want to see all evaluations listed, so that I can review scoring outcomes and awards.

#### Acceptance Criteria

1. THE Dashboard SHALL display an Evaluations section listing every Evaluation_Record in the Overview_Store.
2. THE Dashboard SHALL display for each Evaluation_Record the tender_reference_no, released_at date, bidders_count, complete_bids_count, best-match bidder, status, and final_selection bidder.
3. WHEN an Evaluation_Record has a `run_id` with a corresponding Audit_Record, THE Dashboard SHALL display a link to the evaluation details at `GET /api/eval/audit/{run_id}`.
4. WHEN an Evaluation_Record has none_eligible set to true, THE Dashboard SHALL indicate that no bid met all requirements for that Evaluation_Record.
5. THE Dashboard SHALL order the Evaluations section with the most recent released_at first.

### Requirement 11: Dashboard Data API

**User Story:** As an Officer, I want a JSON endpoint behind the dashboard, so that the page data is assembled consistently from the store.

#### Acceptance Criteria

1. WHEN an Officer requests `GET /api/dashboard`, THE Dashboard_API SHALL return JSON assembled by reading the Overview_Store.
2. THE Dashboard_API response SHALL include the Summary_Tile counts, the list of Tender_Record rows, and the list of Evaluation_Record rows.
3. THE Dashboard_API SHALL order the Tender_Record list with the most recent generated_at first and the Evaluation_Record list with the most recent released_at first.
4. WHEN the Dashboard_API reads the Overview_Store, THE Dashboard_API SHALL NOT modify any Tender_Record or Evaluation_Record.
5. THE Dashboard SHALL write records only at the Generate_Route, the Release_Route, and the Select_Route integration points, and SHALL NOT write records when serving `GET /dashboard` or `GET /api/dashboard`.

### Requirement 12: Empty State

**User Story:** As an Officer starting fresh, I want a friendly empty state, so that I know where to begin when no records exist yet.

#### Acceptance Criteria

1. IF the Overview_Store contains no Tender_Record and no Evaluation_Record, THEN THE Dashboard SHALL display the Empty_State.
2. WHEN the Empty_State is displayed, THE Dashboard SHALL present guidance directing the Officer to create a tender.
3. WHEN the Empty_State is displayed, THE Dashboard SHALL provide a link to the Tender_Builder_Page.
