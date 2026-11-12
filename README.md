# AI-Powered Tender Document Builder

A chat-driven tool that helps a government officer, **even with zero technical
knowledge**, produce a complete, professional e-tender document (PDF) and a
matching Bill of Quantities (BOQ Excel) for cloud/IT procurement.

The officer describes a use case in plain language. The system acts as a
solution architect: it proposes a suitable technical architecture, the officer
reviews and approves it, and the tender PDF + BOQ are generated from that single
approved architecture, so the two documents can never conflict.

Built with **Python + FastAPI** and **Google Gemini** (`gemini-2.5-flash`).

---

## Table of Contents
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [File-by-file reference](#file-by-file-reference)
- [Setup](#setup)
- [Running the app](#running-the-app)
- [API endpoints](#api-endpoints)
- [Key design decisions](#key-design-decisions)
- [Known limitations / next steps](#known-limitations--next-steps)

---

## How it works

The workflow has three stages, all driven from a single chat screen:

1. **Requirement capture (chat).** The officer types details; Gemini extracts
   them into a structured *Requirement Brief* (inviting authority, reference no.,
   EMD, dates, contact details, pre-bid meeting, etc.). The agent asks for any
   missing mandatory field.
2. **Solution architecture.** The officer describes the use case. They can either
   click **Suggest Architecture** (Gemini proposes right-sized components) or
   **paste their own architecture** into chat (it is parsed into components).
   Either way the proposal appears as a card and must be **Approved** before it
   enters the brief.
3. **Generation.** Once core fields are filled and an architecture is approved,
   **Generate** produces:
   - a multi-section **Tender PDF** (with cover, Table of Contents, data sheet,
     scope, fixed eligibility criteria, technical summary, instructions, payment,
     delivery, SLA, general T&C, BOQ summary), and
   - a **BOQ Excel** price schedule in the government `BoQ_Ver4.0` layout.

Both outputs are derived from the same approved architecture (single source of
truth), guaranteeing zero conflict between the tender and the BOQ.

---

## Architecture

```
                         Browser (chat UI)
                static/index.html + app.js + style.css
                                 |
                                 v
                        FastAPI app (app.py)
         /api/chat  /api/architect  /api/approve-architecture
                     /api/generate  /download/{file}
                                 |
            +--------------------+--------------------+
            v                    v                    v
       chat.py               models.py           generator/
   (Gemini calls:         TenderBrief,         pdf_generator.py
    extract fields,       ArchitectureItem,    boq_generator.py
    propose/parse         BOQItem (derived)
    architecture,                 |
    draft sections)               | single source of truth
            |                     v
            v            architecture list ---> PDF Technical Summary
         llm.py                              \-> BOQ line items
   (google-genai                                 (always consistent)
    client wrapper)
            |
            v
      Google Gemini API  (key + model from .env via config.py)

   eligibility.py  --> fixed Bidder Eligibility Criteria, printed in every PDF
```

**Single-source-of-truth principle:** `TenderBrief.architecture` is the only
place technical components live. The PDF's *Technical Requirements (Summary)*
table and the BOQ Excel are both rendered from `TenderBrief.boq_items()`, which
is derived from that same list. Change the architecture and both outputs change
together.

---

## Project structure

```
gov tender analysis/
|-- .env                      # GOOGLE_API_KEY + model names (gitignored)
|-- .gitignore
|-- requirements.txt
|-- README.md
|
|-- tender_app/               # the application package
|   |-- __init__.py
|   |-- config.py             # loads .env, defines OUTPUT_DIR
|   |-- llm.py                # Google GenAI (Gemini) client wrapper
|   |-- models.py             # TenderBrief, ArchitectureItem, BOQItem
|   |-- chat.py               # field extraction, architect, drafting (Gemini)
|   |-- eligibility.py        # fixed Bidder Eligibility Criteria (from ELCOT)
|   |-- app.py                # FastAPI server + routes
|   |
|   |-- generator/
|   |   |-- __init__.py
|   |   |-- pdf_generator.py  # builds the tender PDF (fpdf2)
|   |   |-- boq_generator.py  # builds the BOQ Excel (openpyxl)
|   |
|   |-- templates/
|   |   |-- index.html        # chat UI page
|   |   |-- tender_doc.html   # (legacy, unused - see notes)
|   |
|   |-- static/
|   |   |-- app.js            # front-end chat + architecture + generate logic
|   |   |-- style.css         # UI styling
|   |
|   |-- output/               # generated PDFs and Excel files (gitignored)
|
|-- tools/                    # developer utilities (not part of the app)
|   |-- extract_tenders.py    # dump text from sample tender PDFs/Excel
|   |-- extract_pages.py      # dump specific PDF pages
|   |-- smoke_test.py         # end-to-end generation + consistency check
|
|-- tender1/ tender2/ tender3/   # the three real sample tenders used for analysis
```

---

## File-by-file reference

### Application (`tender_app/`)

| File | Responsibility |
|------|----------------|
| `config.py` | Loads `.env` (via python-dotenv), exposes `GOOGLE_API_KEY`, `LLM_MODEL`, and the `OUTPUT_DIR`. `require_api_key()` raises a clear error if the key is missing. |
| `llm.py` | Thin wrapper over the `google-genai` SDK. `generate(prompt, system, temperature)` does a single-shot Gemini call. Lazily creates one shared client. |
| `models.py` | Pydantic models. **`TenderBrief`** holds all header fields, officer inputs, the approved `architecture` list, and the drafted narrative sections. **`ArchitectureItem`** is one technical component (the source of truth). **`BOQItem`** is a rendered price-schedule line. `boq_items()` derives BOQ lines from the architecture. `missing_core_fields()` and `completeness()` drive the UI. |
| `chat.py` | All Gemini-backed logic: `extract_fields()` (chat -> structured brief), `next_question()` (what to ask next), `propose_architecture()` (AI suggests components), `looks_like_architecture()` + `parse_architecture_from_text()` (parse an architecture the officer pastes), and `draft_sections()` (writes the long narrative sections in depth). |
| `eligibility.py` | The fixed **Bidder Eligibility Criteria** (intro, 7-row criteria/proof table, and the note clauses), taken verbatim from the ELCOT sample tender. Printed in every generated PDF. |
| `app.py` | FastAPI server. Holds a single in-memory session (`STATE`) with the current brief and a staged architecture proposal. Exposes the API endpoints, serves the UI, and handles file generation with unique timestamped filenames + graceful error handling. |

### Generators (`tender_app/generator/`)

| File | Responsibility |
|------|----------------|
| `pdf_generator.py` | Builds the full tender PDF with **fpdf2** (pure Python, no native deps). Includes: cover page, auto-generated **Table of Contents** (fpdf2 two-pass outline), bordered **Tender Data Sheet** (with grouped Pre-Bid and Contact rows), the fixed eligibility table, a **Technical Requirements summary table**, all narrative sections, and a BOQ summary table. Converts light markdown (`**bold**`) to real formatting and strips stray markdown. |
| `boq_generator.py` | Writes the BOQ price schedule as `.xlsx` with **openpyxl**, mirroring the government `BoQ_Ver4.0` header layout. Line items come from `TenderBrief.boq_items()`. |

### Front end (`tender_app/static/`, `templates/`)

| File | Responsibility |
|------|----------------|
| `templates/index.html` | Single-page chat UI: chat panel, Requirement Brief panel, Approved Architecture section, notes box, and the Generate button. |
| `static/app.js` | Talks to the API: sends chat messages, renders agent replies, renders architecture **proposal cards** (with Approve), shows the approved architecture + completeness, enables/disables Generate, and shows download links. |
| `static/style.css` | Styling for the two-panel layout, chat bubbles, proposal cards, and badges. |
| `templates/tender_doc.html` | **Legacy / unused.** An early HTML template from when PDF rendering used WeasyPrint. The app now renders PDFs directly in `pdf_generator.py`; this file can be removed. |

### Developer tools (`tools/`)

These are **not** part of the running app; they were used to analyse the sample
tenders and to test generation.

| File | Purpose |
|------|---------|
| `extract_tenders.py` | Dumps text from a tender PDF and tabular data from a BOQ Excel. |
| `extract_pages.py` | Dumps a specific page range from a PDF. |
| `smoke_test.py` | End-to-end check: proposes an architecture, drafts sections, asserts the PDF technical items match the BOQ items, and generates both files. |

### Sample tenders (`tender1/`, `tender2/`, `tender3/`)

The three real tenders the field model and templates were derived from:
- **tender1** – ELCOT (Tamil Nadu) cloud MSP empanelment: 106-page narrative
  tender + multi-sheet BOQ. Source of the fixed eligibility criteria.
- **tender2** – GeM marketplace bid document (bilingual) + Azure DR SOW.
- **tender3** – ACGCET college RFP (simple format) + single-item BOQ. The
  "simple format" the generator was first built around.

---

## Setup

Requires **Python 3.14** (the project was built and tested on it).

```cmd
:: 1. Create and populate the virtual environment
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt

:: 2. Create a .env file at the project root
```

`.env` contents:

```
GOOGLE_API_KEY=your_google_ai_studio_key_here
LLM_MODEL=gemini-2.5-flash
```

> Get an API key from Google AI Studio: https://aistudio.google.com/apikey
> The `.env` file is gitignored. Do not commit real keys.

### Dependencies (`requirements.txt`)
`fastapi`, `uvicorn[standard]`, `jinja2`, `python-dotenv`, `google-genai`,
`openpyxl`, `fpdf2`, `python-multipart`, `pydantic`.

---

## Running the app

```cmd
.venv\Scripts\python.exe -m uvicorn tender_app.app:app --reload --port 8000
```

Then open **http://127.0.0.1:8000**.

> On Windows **CMD**, use backslashes in the path (`.venv\Scripts\...`).
> In **PowerShell**, prefix with `.\` (`.\.venv\Scripts\...`).

### Typical flow
1. Give the core details (authority, name of work, reference no., EMD,
   submission date, pre-bid meeting + venue, contact name/phone/email).
2. Describe the use case in plain language.
3. Click **Suggest Architecture** (or paste your own architecture in chat).
4. Review the proposal card and click **Approve**.
5. Click **Generate Tender + BOQ** and download the PDF and Excel.

### Quick self-test (optional)
```cmd
set PYTHONPATH=.
.venv\Scripts\python.exe tools\smoke_test.py
```

---

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/` | Serves the chat UI. |
| POST | `/api/chat` | Sends an officer message; extracts fields, and if an architecture is pasted, stages it as a proposal. |
| POST | `/api/architect` | Asks Gemini to propose an architecture (staged, not yet in the brief). |
| POST | `/api/approve-architecture` | Moves the staged proposal into the brief and marks it approved. |
| POST | `/api/generate` | Blocks unless core fields are filled **and** an architecture is approved; drafts sections and writes the PDF + BOQ. |
| GET  | `/download/{name}` | Serves a generated file (path-traversal guarded). |
| POST | `/api/reset` | Clears the session brief and proposal. |

---

## Key design decisions

- **Single source of truth.** Technical components live only in
  `TenderBrief.architecture`. The PDF technical summary and the BOQ are both
  derived from it, so they are always consistent.
- **Human-in-the-loop.** No architecture is used until the officer explicitly
  **approves** it. Generation is blocked without an approved architecture.
- **Grounded drafting.** Gemini is instructed to use only provided facts and not
  fabricate figures, SLAs, or certifications. Officer-pasted architecture is
  marked `source="officer"` and takes precedence.
- **fpdf2 for PDF.** Chosen over WeasyPrint because WeasyPrint needs native GTK
  libraries that do not install cleanly on Windows. fpdf2 is pure Python.
- **Unique output filenames.** Each generation writes a timestamped file so a
  document left open in Excel/a viewer never blocks the next run (Windows locks
  open files).

---

## Known limitations / next steps

- **Single session.** The app holds one brief in memory; no multi-user sessions
  or persistence yet.
- **Fixed eligibility criteria.** The eligibility table is the ELCOT (cloud)
  version and is printed in every PDF. It should become tender-type aware.
- **No BOQ pricing.** The BOQ lists items/quantities but not estimated rates.
- **No PDF/Excel ingestion.** Scanned annexures in the samples have no text
  layer; OCR is out of scope since tenders are built from chat input.
- **Legacy file.** `tender_app/templates/tender_doc.html` is unused and can be
  deleted.
- **Secret hygiene.** The `.env` key was shared during development and should be
  rotated.
```
