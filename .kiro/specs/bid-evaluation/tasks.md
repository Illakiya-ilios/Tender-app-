# Implementation Plan: Bid Evaluation and Best-Match Recommendation (Stage 3)

## Overview

This plan implements Stage 3 as a new `tender_app/evaluation/` package plus targeted extensions to existing files, built in dependency order so the FastAPI app stays runnable and testable as it grows. Build order: dependencies + config + models → `requirements_source` → pipeline stages in flow order (intake → extract → classify → completeness → coverage → capacity → pricing → ranking → audit → orchestrator) → routes → UI.

Deterministic/invariant logic is covered by Hypothesis property-based tests (min 100 iterations each, tagged `# Feature: bid-evaluation, Property {n}: {property text}`). LLM-driven stages (OCR, classification, coverage, capacity, pricing) are covered by example/integration tests with mocked LLM calls. A synthetic second bidder fixture exercises ranking because both real samples (`extracted_1/`, `extracted_2/`) are the same bidder.

Platform: Windows, Python 3.14, venv at `.venv`. Run Python/tests via `.venv\Scripts\python.exe` (e.g. `.venv\Scripts\python.exe -m pytest`).

## Tasks

- [x] 1. Add dependencies and runtime configuration
  - Add `pdfplumber`, `pypdfium2`, `pytest`, and `hypothesis` to `requirements.txt`
  - Install into the venv with `.venv\Scripts\python.exe -m pip install -r requirements.txt`
  - Add `EVAL_DIR` to `tender_app/config.py` (working dir for extracted bids + audit JSON) and ensure the directory is created on import
  - Verify the app still imports/starts after the config change
  - _Requirements: 1.6, 2.1, 2.3, 10.1_

- [x] 2. Create the evaluation package and data models
  - [x] 2.1 Create `tender_app/evaluation/__init__.py` and `tender_app/evaluation/models.py`
    - Implement all pydantic models and `str, Enum` enums from the design Data Models section: `CoverageStatus`, `DocPresence`, `ExtractionSource`, `RequirementClass`, `EvidenceCitation`, `RequiredDocumentType`, `RequirementItem`, `ExtractedPage`, `ExtractedDocument`, `SubDocument`, `CoverageFinding`, `DocCheckCell`, `CompletenessResult`, `CapacityItemResult`, `CapacityResult`, `BidPrice`, `BidDocument`, `Bid`, `BidEvaluation`, `ShortlistEntry`, `Shortlist`, `OfficerOverride`, `FinalSelection`, `AuditRecord`, `EvaluationRun`
    - Match the existing `models.py` pydantic `BaseModel` style
    - _Requirements: 2.4, 3.4, 3.5, 4.4, 5.3, 5.4, 6.3, 6.4, 7.2, 7.3, 8.1, 8.3, 8.6, 10.1_

  - [ ]* 2.2 Write unit tests for model serialization
    - Assert enums serialize to their string values and models JSON round-trip cleanly (needed later by the audit record)
    - _Requirements: 10.1, 10.3_

- [ ] 3. Implement the Source_Tender derivation module (`requirements_source.py`)
  - [x] 3.1 Implement `required_document_types(tender)` and `requirement_items(tender)`
    - Derive the `RequiredDocumentType` set from `eligibility.ELIGIBILITY_ROWS` documentary-proof column plus tender-specific required documents (deterministic, no LLM)
    - Derive `RequirementItem`s across the four classes: eligibility from `eligibility.ELIGIBILITY_ROWS`, technical/qualification/capability from `tender.architecture` + `TenderBrief`
    - _Requirements: 3.3, 5.1_

  - [ ]* 3.2 Write unit tests for requirement derivation
    - Assert every eligibility row produces a required-document type and a requirement item; assert determinism (same tender → same output)
    - _Requirements: 3.3, 5.1_

- [ ] 4. Implement bid intake with safe zip extraction (`intake.py`)
  - [x] 4.1 Implement `safe_extract_member` and `extract_bid`
    - `safe_extract_member` resolves each entry under the bid directory and returns `None` (reject, no write) for any entry escaping it
    - `extract_bid` extracts all archives for one bid into `run_dir/bid_id/`, treats multiple archives as one bid, discovers PDFs by content (never by folder/filename meaning), and sets `evaluable = False` when no readable PDF is found
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_

  - [ ]* 4.2 Write property test for zip-slip containment
    - **Property 1: Zip extraction confines files to the bid directory** — generate archives with hostile entry names (`../`, absolute, nested); assert every written file resolves inside the bid dir and escaping entries are rejected
    - **Validates: Requirements 1.6**

  - [ ]* 4.3 Write example tests for intake grouping and no-PDF handling
    - Assert multiple archives map to one bid and that an archive with no readable PDF yields `evaluable = False`
    - _Requirements: 1.2, 1.4_

- [ ] 5. Add multimodal LLM support and implement text/OCR extraction (`extract.py`)
  - [x] 5.1 Add `generate_multimodal(prompt, images, system, temperature)` to `tender_app/llm.py`
    - Single-shot multimodal call passing PNG page-image bytes alongside text, using the existing `gemini-2.5-flash` model; wrap SDK errors like the existing `generate(...)`
    - _Requirements: 2.2, 2.3_

  - [x] 5.2 Implement `extract_document` and `looks_unreadable`
    - Per page: extract text with `pdfplumber`; if a page yields no text or garbled/non-readable text, render it with `pypdfium2` and OCR via `generate_multimodal`
    - Record per-document extraction source (`TEXT` | `OCR` | `BOTH`); mark page/document unreadable and retain the filename when neither method yields readable text
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 5.3 Write example tests for extraction with mocked vision calls
    - Digital-PDF fixture exercises the pdfplumber path; scanned-image fixture (with mocked `generate_multimodal`) exercises the OCR path; assert recorded `ExtractionSource` and readable/unreadable flags
    - _Requirements: 2.1, 2.2, 2.4, 2.5_

- [ ] 6. Implement sub-document segmentation and semantic classification (`classify.py`)
  - [x] 6.1 Implement `classify_bid`
    - Segment each PDF into `SubDocument`s with page ranges; assign each to a `RequiredDocumentType` by content via Gemini
    - Record source filename + page range per sub-document; label unmatched as `Unclassified` and retain; associate all same-type sub-documents to that type
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6_

  - [ ]* 6.2 Write example tests for classification with stubbed LLM
    - Feed known sub-document text with a stubbed `generate_multimodal`; assert page-range recording, `Unclassified` retention, and multi-match association
    - _Requirements: 3.4, 3.5, 3.6_

- [ ] 7. Implement the completeness gate (`completeness.py`)
  - [x] 7.1 Implement `check_completeness`
    - For each `RequiredDocumentType`, determine presence of ≥1 present-and-readable sub-document; flag `MISSING` when none present/readable and `PRESENT_BUT_UNREADABLE` when present only via unreadable docs
    - Any missing/unreadable type → `complete = False` (excluded from scoring); all present+readable → `complete = True`; report each flagged type with the bidder identity
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 7.2 Write property test for the completeness gate
    - **Property 2: A bid with any missing or unreadable required document is never complete** — generate sub-document/type sets; assert `complete` iff every type has a present-and-readable sub-document
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**

- [x] 8. Checkpoint - Ensure all tests pass
  - Run `.venv\Scripts\python.exe -m pytest`; ensure all tests pass, ask the user if questions arise.

- [ ] 9. Implement requirement coverage assessment (`coverage.py`)
  - [x] 9.1 Implement `assess_coverage`
    - Assign each `RequirementItem` a `Satisfied` / `Partly Satisfied` / `Not Satisfied` status grounded in classified sub-documents
    - Enforce invariants in a post-processor: `Satisfied`/`Partly` findings carry ≥1 `EvidenceCitation` (non-empty filename, positive page); `Not Satisfied` findings carry a non-empty reason; emit exactly one finding per requirement item
    - _Requirements: 5.2, 5.3, 5.4, 5.5_

  - [ ]* 9.2 Write property test for evidence citation on Satisfied/Partly findings
    - **Property 4: Every Satisfied or Partly finding carries at least one evidence citation** — generate coverage-finding lists; assert the post-processor guarantees ≥1 citation with non-empty filename and positive page
    - **Validates: Requirements 5.3**

  - [ ]* 9.3 Write property test for reason on Not-Satisfied findings
    - **Property 5: Every Not-Satisfied finding carries a reason** — assert every `Not Satisfied` finding has a non-empty reason
    - **Validates: Requirements 5.4**

  - [ ]* 9.4 Write property test for coverage summary completeness
    - **Property 6: Coverage summary covers exactly the requirement item set** — assert exactly one finding per requirement item, none missing or duplicated
    - **Validates: Requirements 5.2, 5.5**

- [ ] 10. Implement capacity assessment (`capacity.py`)
  - [x] 10.1 Implement `assess_capacity`
    - Assess turnover, prior experience, delivered projects, certifications; turnover uses the CA/Statutory Auditor turnover certificate as evidence with a citation
    - Set `capacity_qualified = True` when all met; otherwise record each unmet requirement with its reason
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ]* 10.2 Write example tests for capacity with mocked LLM
    - Assert turnover citation is attached and that unmet requirements record reasons and set `capacity_qualified = False`
    - _Requirements: 6.2, 6.4_

- [ ] 11. Implement price extraction (`pricing.py`)
  - [x] 11.1 Implement `extract_price`
    - Extract total quoted price from the price schedule with an `EvidenceCitation` (filename + page); when none extractable, set `available = False` with a note that the bid cannot be ranked on price until the officer supplies it
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 11.2 Write example tests for pricing with mocked LLM
    - Assert extracted price carries a citation and that a bid with no extractable price yields `available = False` with the note
    - _Requirements: 7.2, 7.3_

- [ ] 12. Implement best-match ranking and shortlist (`ranking.py`, pure/no LLM)
  - [x] 12.1 Implement `build_shortlist`
    - Eligible = complete AND every requirement item `Satisfied` AND capacity-qualified; rank eligible priced bids ascending by price; lowest-price eligible bid is `best_match_bid_id`
    - Record per-ranked-bid reasons (price, coverage, capacity); when none eligible set `none_eligible = True`, `best_match_bid_id = None`, and per-bid blocking reasons; list eligible bids with unavailable price as unranked-on-price (no numeric rank)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 12.2 Add synthetic second-bidder fixture for ranking tests
    - Create a `BidEvaluation` fixture for a distinct, fully-compliant bidder with a different price so multi-bidder ranking can be exercised (real samples are a single bidder)
    - _Requirements: 8.2, 8.3_

  - [ ]* 12.3 Write property test excluding incomplete bids from selection
    - **Property 3: Incomplete bids are excluded from best-match selection** — assert no `complete = False` bid is eligible or the `best_match_bid_id`
    - **Validates: Requirements 4.4, 8.1**

  - [ ]* 12.4 Write property test for eligibility criteria
    - **Property 7: Eligibility for best match requires complete + all Satisfied + capacity-qualified** — assert `eligible` iff complete AND all items Satisfied AND capacity-qualified
    - **Validates: Requirements 8.1**

  - [ ]* 12.5 Write property test for ascending total-order ranking
    - **Property 8: Ranking is a correct ascending total order by price over priced eligible bids** — assert ranks are a permutation `1..k` by non-decreasing price, rank 1 is `best_match_bid_id`, and unavailable-price bids get no numeric rank
    - **Validates: Requirements 8.2, 8.3, 8.6**

  - [ ]* 12.6 Write property test for minimum-price best match
    - **Property 9: Best match is the minimum-price eligible bid** — assert `best_match_bid_id` price ≤ every other eligible priced bid
    - **Validates: Requirements 8.3**

  - [ ]* 12.7 Write property test for no-eligible-bid case
    - **Property 10: No eligible bid means no best match, with per-bid blocking reasons** — assert `none_eligible = True`, `best_match_bid_id = None`, and every bid has ≥1 non-empty blocking reason
    - **Validates: Requirements 8.5**

- [x] 13. Checkpoint - Ensure all tests pass
  - Run `.venv\Scripts\python.exe -m pytest`; ensure all tests pass, ask the user if questions arise.

- [ ] 14. Implement audit persistence (`audit.py`)
  - [x] 14.1 Implement `persist_run`, `append_action`, and `load_run`
    - `persist_run` writes a timestamped `AuditRecord` JSON to `config.EVAL_DIR` with a unique `_YYYYMMDD_HHMMSS` filename, including coverage and price citations
    - `append_action` appends an override/selection with justification + timestamp; `load_run` resolves the run file within `EVAL_DIR` only (path-traversal safe, mirrors the existing `download()` pattern)
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 14.2 Write property test for override append + justification
    - **Property 12: Every override records a justification and appends to the audit record** — assert stored override has non-empty justification + timestamp and the override list grows by exactly one
    - **Validates: Requirements 9.3, 10.2**

  - [ ]* 14.3 Write property test for audit record round-trip
    - **Property 13: Audit record round-trips through persistence** — serialize an `EvaluationRun` to `AuditRecord` JSON and load it back; assert evaluations, shortlist, overrides, final selection, and all citations are preserved
    - **Validates: Requirements 10.1, 10.3**

- [ ] 15. Implement the pipeline orchestrator (`pipeline.py`)
  - [x] 15.1 Implement the linear pipeline wiring stages 1–8 into an `EvaluationRun`
    - Build `required_types` + `requirement_items` from the Source_Tender, then run intake → extract → classify → completeness per bid; release-gated bids run coverage → capacity → pricing; then ranking builds the shortlist
    - Handle graceful degradation: no-evaluable-PDF bids excluded; LLM/API failures recorded as stage errors (OCR failure → unreadable; coverage/capacity default to Not Satisfied/not-qualified with the error as reason)
    - _Requirements: 1.4, 2.5, 4.4, 4.5, 5.2, 6.1, 7.1, 8.1_

  - [ ]* 15.2 Write integration test for the pipeline with a mocked LLM
    - Run the single real bidder through intake→completeness as a smoke test and a synthetic two-bidder set through the full pipeline; assert the shortlist is produced
    - _Requirements: 4.5, 8.1_

- [ ] 16. Add FastAPI routes and in-memory state (`app.py`)
  - [x] 16.1 Add the `eval_run` slot to `STATE` and implement Stage 3 routes
    - `GET /evaluation` serves `evaluation.html`
    - `POST /api/eval/bids` (multipart, rejects non-zip/empty), `POST /api/eval/run`, `GET /api/eval/completeness`, `GET /api/eval/missing-report`
    - `POST /api/eval/release`, `GET /api/eval/matrix`, `GET /api/eval/evidence`, `GET /api/eval/shortlist`
    - `POST /api/eval/override` (justification required), `POST /api/eval/select`, `GET /api/eval/report`, `GET /api/eval/audit/{run_id}`
    - Apply the existing `.resolve()`-and-check guard on `audit/{run_id}`, `report`, and the Open Document link
    - _Requirements: 1.1, 1.2, 1.5, 4.5, 4.6, 5.3, 5.5, 8.1, 9.1, 9.2, 9.3, 9.4, 9.5, 10.2, 10.4_

  - [ ]* 16.2 Write integration test for officer-only final selection
    - **Property 11: Final selection is only set by officer confirmation** — assert `final_selection` is `None` through pipeline ops without a select action, and after `POST /api/eval/select` it references the chosen bid and no other bid is final
    - **Validates: Requirements 9.4, 9.5**

  - [ ]* 16.3 Write integration test for the route happy path
    - upload → run → release → shortlist → override → select with a mocked pipeline; assert override requires justification and state transitions are recorded
    - _Requirements: 1.1, 4.5, 9.2, 9.3, 9.4_

- [ ] 17. Build the Stage 3 UI (three-screen tabbed page)
  - [x] 17.1 Create `templates/evaluation.html` and append Stage 3 styles to `static/style.css`
    - Three tabs reusing the existing palette/card/badge/two-panel aesthetic: Bid Document Check, Bid Evaluation with evidence, Best Match Recommendation
    - _Requirements: 4.6, 5.5, 8.1, 9.1_

  - [x] 17.2 Create `static/evaluation.js` (vanilla JS, fetch) wiring screens to the routes
    - Screen 1: summary tiles, doc-check matrix (Present/Missing/Not provided badges), action-needed panel, release button, re-run, missing-report download
    - Screen 2: evaluation matrix with weighted scores and the Evidence & Justification panel (quote/filename/page + Open Document)
    - Screen 3: ranked list, best-match card, strengths/gaps/risks, "why others ranked lower", approve/override controls, report download
    - _Requirements: 4.5, 4.6, 5.3, 5.5, 8.1, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 10.4_

- [x] 18. Final checkpoint - Ensure all tests pass
  - Run `.venv\Scripts\python.exe -m pytest`; ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP; core implementation tasks are never optional.
- Property tests use Hypothesis with a minimum of 100 iterations and are tagged `# Feature: bid-evaluation, Property {n}: {property text}`.
- Properties 2, 3, 6, 7, 8, 9, 10 target `completeness.py`/`ranking.py` (pure functions); Property 1 targets zip-slip; Properties 4, 5 target coverage invariants; Properties 12, 13 target audit; Property 11 is an integration test over the route handlers.
- LLM-driven stages (OCR, classification, coverage, capacity, pricing) are validated with example/integration tests using mocked LLM calls, not property tests.
- A synthetic second bidder fixture exercises multi-bidder ranking because both real samples (`extracted_1/`, `extracted_2/`) are the same bidder.
- Run Python and tests through the venv: `.venv\Scripts\python.exe -m pytest`.
