"""FastAPI server: chat-driven requirement capture + tender/BOQ generation.

This is a single-session demo (one officer, one brief held in memory).
Multi-user sessions and persistence come later.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat, config, store
from .models import TenderBrief, ArchitectureItem
from .generator.pdf_generator import generate_pdf
from .generator.boq_generator import generate_boq
from .evaluation import audit, pipeline
from .evaluation.models import (
    CoverageStatus,
    FinalSelection,
    OfficerOverride,
)

APP_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Tender Builder")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Prevent the browser from serving stale JS/CSS during development."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response

# Single in-memory brief for the demo session, plus a staging slot for an
# architecture proposal that has not yet been approved by the officer.
#
# Stage 3 adds:
#   "eval_run"     - the live EvaluationRun | None for the current evaluation.
#   "eval_uploads" - staged bid uploads keyed by bid_id, each holding the
#                    bidder name and the saved zip archive paths, used as the
#                    bid_inputs for pipeline.run_evaluation.
#   "run_id"       - the persisted run id (set on release/persist) for audit.
STATE: dict = {
    "brief": TenderBrief(),
    "proposal": [],
    "eval_run": None,
    "eval_uploads": {},
    "run_id": None,
    "checks_run": 0,
}

try:
    store.init_db()
except Exception as exc:  # noqa: BLE001
    logging.getLogger(__name__).warning("Dashboard store init failed: %s", exc)


def _safe_name(value: str) -> str:
    """Turn a tender reference into a filename-safe slug."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip()).strip("_")


class ChatIn(BaseModel):
    message: str


class GenerateIn(BaseModel):
    notes: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (APP_DIR / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    """Serve the persistent overview Dashboard shell.

    templates/dashboard.html is created in a later task; until then return a
    small placeholder so this route never crashes (mirrors evaluation_page()).
    """
    template = APP_DIR / "templates" / "dashboard.html"
    if template.is_file():
        return template.read_text(encoding="utf-8")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Dashboard</title></head><body>"
        "<h1>Dashboard</h1>"
        "<p>The dashboard UI is being built. The read-only API is available at "
        "<code>/api/dashboard</code>.</p>"
        "</body></html>"
    )


@app.get("/api/dashboard")
def api_dashboard() -> JSONResponse:
    try:
        tiles = store.counts()
        tenders = store.list_tenders()
        evaluations = store.list_evaluations()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("dashboard read failed: %s", exc)
        tiles = {"total_tenders": 0, "total_evaluations": 0, "awarded": 0, "scored": 0}
        tenders, evaluations = [], []
    return JSONResponse({
        "tiles": tiles,
        "tenders": tenders,
        "evaluations": evaluations,
        "empty": not tenders and not evaluations,
    })


@app.post("/api/chat")
def api_chat(payload: ChatIn) -> JSONResponse:
    brief = STATE["brief"]
    before = (brief.scope_notes, brief.technical_inputs)
    brief = chat.extract_fields(payload.message, brief)
    # If the use case or technical inputs changed, any approved architecture is
    # now stale: clear approval so the officer re-suggests and re-approves.
    if (brief.scope_notes, brief.technical_inputs) != before and brief.architecture_approved:
        brief.architecture_approved = False
        STATE["proposal"] = []
    STATE["brief"] = brief

    from .models import ArchitectureItem

    # The architecture we can edit: a staged proposal takes priority, else the
    # already-approved architecture on the brief.
    existing = STATE.get("proposal") or [a.model_dump() for a in brief.architecture]

    # CASE 1: there is an existing architecture and the officer asks to CHANGE it.
    if existing and chat.looks_like_change_request(payload.message) \
            and not chat.looks_like_architecture(payload.message):
        current_items = [ArchitectureItem(**a) for a in existing]
        updated = chat.apply_architecture_changes(current_items, payload.message)
        STATE["proposal"] = [a.model_dump() for a in updated]
        # Editing invalidates any prior approval; officer must re-approve.
        brief.architecture_approved = False
        STATE["brief"] = brief
        return JSONResponse({
            "reply": "I've updated the architecture with your change. Review it "
                     "below and click Approve, or tell me more changes.",
            "proposal": STATE["proposal"],
            "brief": brief.model_dump(),
            "completeness": brief.completeness(),
        })

    # CASE 2: the officer PASTED a full architecture - parse and stage it.
    if chat.looks_like_architecture(payload.message):
        items = chat.parse_architecture_from_text(payload.message, brief)
        if items:
            STATE["proposal"] = [a.model_dump() for a in items]
            return JSONResponse({
                "reply": "I've captured the architecture you provided and added it "
                         "below. Review it and click Approve to add it to the "
                         "Requirement Brief, or tell me any changes you'd like.",
                "proposal": STATE["proposal"],
                "brief": brief.model_dump(),
                "completeness": brief.completeness(),
            })

    reply = chat.next_question(brief)
    return JSONResponse({
        "reply": reply,
        "brief": brief.model_dump(),
        "completeness": brief.completeness(),
    })


@app.post("/api/architect")
def api_architect() -> JSONResponse:
    """Propose a technical architecture. The proposal is STAGED (shown in chat)
    and does not enter the brief until the officer approves it."""
    brief = STATE["brief"]
    if not brief.scope_notes:
        return JSONResponse({
            "error": "Please describe the use case in chat first, then I can "
                     "suggest an architecture.",
            "brief": brief.model_dump(),
            "completeness": brief.completeness(),
        })
    # Propose into a throwaway copy so the live brief is untouched until approval.
    staged = chat.propose_architecture(brief.model_copy(deep=True))
    STATE["proposal"] = [a.model_dump() for a in staged.architecture]
    return JSONResponse({
        "reply": "Here's a suggested architecture for your use case. Review it and "
                 "click Approve to add it to the Requirement Brief, or tell me "
                 "changes in chat and I'll re-suggest.",
        "proposal": STATE["proposal"],
        "brief": brief.model_dump(),
        "completeness": brief.completeness(),
    })


@app.post("/api/approve-architecture")
def api_approve_architecture() -> JSONResponse:
    """Move the staged proposal into the brief and mark it approved."""
    brief = STATE["brief"]
    proposal = STATE.get("proposal") or []
    if not proposal:
        return JSONResponse({
            "error": "There is no suggested architecture to approve yet. "
                     "Click 'Suggest Architecture' first.",
            "brief": brief.model_dump(),
            "completeness": brief.completeness(),
        })
    brief.architecture = [ArchitectureItem(**a) for a in proposal]
    brief.architecture_approved = True
    STATE["brief"] = brief
    STATE["proposal"] = []
    return JSONResponse({
        "reply": "Architecture approved and added to the Requirement Brief. "
                 "You can now generate the tender document and BOQ.",
        "brief": brief.model_dump(),
        "completeness": brief.completeness(),
    })


@app.post("/api/generate")
def api_generate(payload: GenerateIn) -> JSONResponse:
    brief = STATE["brief"]
    missing = brief.missing_core_fields()
    if missing:
        return JSONResponse({
            "error": f"Still missing core fields: {', '.join(missing)}. "
                     "Please provide them in chat before generating.",
            "brief": brief.model_dump(),
            "completeness": brief.completeness(),
        })

    # Architecture must be approved before any document is generated.
    if not (brief.architecture and brief.architecture_approved):
        return JSONResponse({
            "error": "No approved architecture. Click 'Suggest Architecture', then "
                     "'Approve' before generating. The tender and BOQ are built from "
                     "the approved architecture.",
            "brief": brief.model_dump(),
            "completeness": brief.completeness(),
        })

    # Draft Scope and Terms. Technical Requirements render from architecture.
    brief = chat.draft_sections(brief, extra_notes=payload.notes)
    STATE["brief"] = brief

    # Unique, timestamped filenames so a file left open in Excel/a PDF viewer
    # never blocks the next generation (Windows locks open files).
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ref = _safe_name(brief.tender_reference_no) or "tender"
    boq_name = f"BOQ_{ref}_{stamp}.xlsx"
    pdf_name = f"Tender_{ref}_{stamp}.pdf"

    result = {
        "brief": brief.model_dump(),
        "completeness": brief.completeness(),
    }

    try:
        generate_boq(brief, boq_name)
        result["boq_url"] = f"/download/{boq_name}"
    except PermissionError:
        result["boq_error"] = (
            "Could not write the BOQ file - a previously generated BOQ may be open "
            "in Excel. Close it and try again."
        )
    except Exception as e:  # noqa: BLE001
        result["boq_error"] = f"BOQ generation failed: {e}"

    try:
        generate_pdf(brief, pdf_name)
        result["pdf_url"] = f"/download/{pdf_name}"
    except PermissionError:
        result["pdf_error"] = (
            "Could not write the PDF - a previously generated PDF may be open in a "
            "viewer. Close it and try again."
        )
    except Exception as e:  # noqa: BLE001
        result["pdf_error"] = f"PDF generation failed: {e}"

    if "pdf_url" in result or "boq_url" in result:
        try:
            store.save_tender({
                "name_of_work": brief.name_of_work,
                "tender_reference_no": brief.tender_reference_no,
                "inviting_authority": brief.tender_inviting_authority,
                "emd_amount": brief.emd_amount,
                "completeness": brief.completeness(),
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "pdf_filename": pdf_name if "pdf_url" in result else "",
                "pdf_url": result.get("pdf_url", ""),
                "boq_filename": boq_name if "boq_url" in result else "",
                "boq_url": result.get("boq_url", ""),
            })
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("save_tender failed: %s", exc)

    return JSONResponse(result)


@app.get("/download/{name}")
def download(name: str):
    # Resolve within OUTPUT_DIR only, to prevent path traversal.
    target = (config.OUTPUT_DIR / name).resolve()
    if config.OUTPUT_DIR.resolve() not in target.parents or not target.is_file():
        return JSONResponse({"error": "File not found."}, status_code=404)
    return FileResponse(str(target), filename=target.name)


@app.post("/api/reset")
def reset() -> JSONResponse:
    STATE["brief"] = TenderBrief()
    STATE["proposal"] = []
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Stage 3: Evaluation and Best-Match Recommendation routes
#
# Same single-session, in-memory style as Stage 1/2: one EvaluationRun lives in
# STATE["eval_run"]. Data is returned as JSONResponse, the page as HTMLResponse,
# downloads as FileResponse. Any filesystem path derived from user input is
# resolved and confirmed to live within config.EVAL_DIR (mirrors download()).
# ---------------------------------------------------------------------------


def _eval_timestamp() -> str:
    """A sortable, filename-safe timestamp (matches the Stage 1/2 convention)."""
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _resolve_in_eval_dir(*parts: str) -> Optional[Path]:
    """Resolve a path built from user input strictly inside config.EVAL_DIR.

    Returns the resolved Path if it is contained within EVAL_DIR, else None.
    Mirrors the `.resolve()`-and-check guard used by download().
    """
    eval_dir = config.EVAL_DIR.resolve()
    target = eval_dir.joinpath(*parts).resolve()
    if target != eval_dir and eval_dir not in target.parents:
        return None
    return target


def _completeness_payload(run) -> dict:
    """Build the Bid Document Check matrix payload from an EvaluationRun."""
    required_types = [
        {"key": t.key, "label": t.label, "description": t.description}
        for t in run.required_types
    ]

    bids = []
    complete_count = 0
    for ev in run.evaluations:
        comp = ev.completeness
        if comp.complete:
            complete_count += 1
        cells = [
            {
                "document_key": cell.document_key,
                "presence": cell.presence.value,
                "citations": [c.model_dump() for c in cell.citations],
            }
            for cell in comp.cells
        ]
        bids.append({
            "bid_id": ev.bid.bid_id,
            "bidder_name": ev.bid.bidder_name,
            "complete": comp.complete,
            "evaluable": ev.bid.evaluable,
            "missing": list(comp.missing),
            "unreadable": list(comp.unreadable),
            "officer_overridden": comp.officer_overridden,
            "cells": cells,
        })

    n = len(run.evaluations)
    missing_docs = sum(len(ev.completeness.missing) for ev in run.evaluations)
    summary = {
        "required_documents": len(run.required_types),
        "complete_bids": f"{complete_count}/{n}",
        "complete_bids_count": complete_count,
        "bids_count": n,
        "missing_documents": missing_docs,
        "checks_run": STATE.get("checks_run", 0),
    }

    return {
        "run_id": run.run_id,
        "required_types": required_types,
        "bids": bids,
        "summary": summary,
    }


def _matrix_payload(run) -> dict:
    """Build the Evaluation Matrix payload grouped by requirement class."""
    # Map requirement key -> (req_class, text, weight) for grouping.
    items_by_key = {it.key: it for it in run.requirement_items}
    groups_order = ["eligibility", "technical", "qualification", "capability"]

    bids = []
    for ev in run.evaluations:
        findings_by_key = {f.requirement_key: f for f in ev.coverage}
        groups: dict[str, list] = {g: [] for g in groups_order}
        for it in run.requirement_items:
            finding = findings_by_key.get(it.key)
            cell = {
                "requirement_key": it.key,
                "requirement_text": it.text,
                "weight": it.weight,
                "status": finding.status.value if finding else None,
                "officer_overridden": finding.officer_overridden if finding else False,
            }
            groups.setdefault(it.req_class.value, []).append(cell)

        cap = ev.capacity
        price = ev.price
        bids.append({
            "bid_id": ev.bid.bid_id,
            "bidder_name": ev.bid.bidder_name,
            "complete": ev.completeness.complete,
            "weighted_score": ev.weighted_score,
            "groups": {g: groups.get(g, []) for g in groups.keys()},
            "capacity": {
                "capacity_qualified": cap.capacity_qualified,
                "officer_overridden": cap.officer_overridden,
                "items": [
                    {
                        "name": ci.name,
                        "met": ci.met,
                        "reason": ci.reason,
                        "citations": [c.model_dump() for c in ci.citations],
                    }
                    for ci in cap.items
                ],
            },
            "price": {
                "available": price.available,
                "amount": price.amount,
                "currency": price.currency,
                "note": price.note,
                "citation": price.citation.model_dump() if price.citation else None,
            },
        })

    return {"run_id": run.run_id, "req_classes": groups_order, "bids": bids}


class OverrideIn(BaseModel):
    target: str
    bid_id: str
    item_key: str = ""
    new_value: str = ""
    justification: str = ""


class SelectIn(BaseModel):
    bid_id: str
    justification: str = ""


@app.get("/evaluation", response_class=HTMLResponse)
def evaluation_page() -> str:
    """Serve the Stage 3 three-screen page.

    Task 17 creates templates/evaluation.html. Until then, return a small
    placeholder so this route never crashes.
    """
    template = APP_DIR / "templates" / "evaluation.html"
    if template.is_file():
        return template.read_text(encoding="utf-8")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Bid Evaluation</title></head><body>"
        "<h1>Bid Evaluation (Stage 3)</h1>"
        "<p>The evaluation UI is being built. The API routes under "
        "<code>/api/eval/</code> are available.</p>"
        "</body></html>"
    )


@app.post("/api/eval/bids")
async def api_eval_bids(
    bidder_name: str = Form(...),
    bid_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> JSONResponse:
    """Upload one or more .zip archives for a single bidder (multipart).

    Multiple archives map to one bid (Req 1.2). Call repeatedly with distinct
    bid_id values to register multiple bidders (Req 1.1, 1.5). Rejects non-zip
    or empty uploads with a clear JSON error.
    """
    bid_id = (bid_id or "").strip()
    bidder_name = (bidder_name or "").strip()
    if not bid_id:
        return JSONResponse({"error": "bid_id is required."}, status_code=400)
    if not files:
        return JSONResponse({"error": "At least one .zip file is required."}, status_code=400)

    safe_bid = _safe_name(bid_id)
    uploads_dir = _resolve_in_eval_dir("uploads", safe_bid)
    if uploads_dir is None:
        return JSONResponse({"error": "Invalid bid_id."}, status_code=400)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    for upload in files:
        filename = upload.filename or ""
        if not filename.lower().endswith(".zip"):
            return JSONResponse(
                {"error": f"'{filename}' is not a .zip file. Only .zip archives are accepted."},
                status_code=400,
            )
        content = await upload.read()
        if not content:
            return JSONResponse(
                {"error": f"'{filename}' is empty."}, status_code=400
            )
        safe_file = _safe_name(filename) or "archive.zip"
        if not safe_file.lower().endswith(".zip"):
            safe_file += ".zip"
        dest = uploads_dir / safe_file
        dest.write_bytes(content)
        saved.append(dest)

    STATE["eval_uploads"][bid_id] = {
        "bidder_name": bidder_name,
        "archives": saved,
    }

    registered = [
        {
            "bid_id": bid,
            "bidder_name": info["bidder_name"],
            "archive_count": len(info["archives"]),
        }
        for bid, info in STATE["eval_uploads"].items()
    ]
    return JSONResponse({
        "ok": True,
        "bid_id": bid_id,
        "bidder_name": bidder_name,
        "archive_count": len(saved),
        "registered_bidders": registered,
    })


@app.post("/api/eval/run")
def api_eval_run() -> JSONResponse:
    """Phase 1: run intake -> extract -> classify -> completeness over uploads.

    Stores the resulting EvaluationRun in STATE["eval_run"] and returns the
    document-check matrix payload (Req 1-4).
    """
    uploads = STATE.get("eval_uploads") or {}
    if not uploads:
        return JSONResponse(
            {"error": "No bids uploaded. Upload at least one bidder's archives first."},
            status_code=400,
        )

    bid_inputs = [
        (bid_id, info["bidder_name"], list(info["archives"]))
        for bid_id, info in uploads.items()
    ]

    run = pipeline.run_evaluation(STATE["brief"], bid_inputs)
    STATE["eval_run"] = run
    STATE["checks_run"] = STATE.get("checks_run", 0) + 1

    return JSONResponse(_completeness_payload(run))


@app.get("/api/eval/completeness")
def api_eval_completeness() -> JSONResponse:
    """Return the Bid Document Check matrix + summary tiles (Req 4.6)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse(
            {"error": "No evaluation run yet. Run the document check first."},
            status_code=400,
        )
    return JSONResponse(_completeness_payload(run))


@app.get("/api/eval/missing-report")
def api_eval_missing_report():
    """Download a text/markdown report of missing/unreadable docs per bid (Req 4.6)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse(
            {"error": "No evaluation run yet. Run the document check first."},
            status_code=400,
        )

    labels = {t.key: t.label for t in run.required_types}
    lines = [
        f"# Missing / Unreadable Documents Report",
        f"Run: {run.run_id}",
        f"Generated: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for ev in run.evaluations:
        comp = ev.completeness
        lines.append(f"## {ev.bid.bidder_name or ev.bid.bid_id} ({ev.bid.bid_id})")
        lines.append(f"Complete: {'yes' if comp.complete else 'no'}")
        if comp.missing:
            lines.append("Missing documents:")
            lines.extend(f"  - {labels.get(k, k)}" for k in comp.missing)
        if comp.unreadable:
            lines.append("Present but unreadable:")
            lines.extend(f"  - {labels.get(k, k)}" for k in comp.unreadable)
        if not comp.missing and not comp.unreadable:
            lines.append("  (no missing or unreadable documents)")
        lines.append("")

    report = "\n".join(lines)
    name = f"missing_report_{_safe_name(run.run_id)}_{_eval_timestamp()}.md"
    target = _resolve_in_eval_dir(name)
    if target is None:
        return JSONResponse({"error": "Invalid report path."}, status_code=400)
    target.write_text(report, encoding="utf-8")
    return FileResponse(str(target), filename=target.name, media_type="text/markdown")


@app.post("/api/eval/release")
def api_eval_release() -> JSONResponse:
    """Officer release gate: score complete bids + build shortlist (Req 4.5, 5-7)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse(
            {"error": "No evaluation run yet. Run the document check first."},
            status_code=400,
        )

    run = pipeline.release_and_score(run)
    STATE["eval_run"] = run

    try:
        persisted = audit.persist_run(run)
        STATE["run_id"] = run.run_id
    except Exception as exc:  # noqa: BLE001 - persistence failure is non-fatal here.
        payload = {**_matrix_payload(run), "persist_error": f"Could not persist run: {exc}"}
        try:
            store.upsert_evaluation_scored(run)
        except Exception as store_exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("upsert_evaluation_scored failed: %s", store_exc)
        return JSONResponse(payload)

    try:
        store.upsert_evaluation_scored(run)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("upsert_evaluation_scored failed: %s", exc)

    return JSONResponse({**_matrix_payload(run), "persisted": persisted.name})


@app.get("/api/eval/matrix")
def api_eval_matrix() -> JSONResponse:
    """Return the Evaluation Matrix grouped by requirement class (Req 5.5)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse(
            {"error": "No evaluation run yet."}, status_code=400
        )
    return JSONResponse(_matrix_payload(run))


@app.get("/api/eval/evidence")
def api_eval_evidence(bid_id: str, requirement_key: str) -> JSONResponse:
    """Return the Evidence & Justification for one matrix cell (Req 5.3)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse({"error": "No evaluation run yet."}, status_code=400)

    evaluation = next((e for e in run.evaluations if e.bid.bid_id == bid_id), None)
    if evaluation is None:
        return JSONResponse({"error": "Unknown bid_id."}, status_code=404)

    finding = next(
        (f for f in evaluation.coverage if f.requirement_key == requirement_key),
        None,
    )
    if finding is None:
        return JSONResponse(
            {"error": "No finding for that requirement (bid may not be released yet)."},
            status_code=404,
        )

    citations = []
    for c in finding.citations:
        citations.append({
            "filename": c.filename,
            "page": c.page,
            "quote": c.quote,
            "document_url": (
                f"/api/eval/document?bid_id={bid_id}&filename={c.filename}"
            ),
        })

    return JSONResponse({
        "bid_id": bid_id,
        "requirement_key": requirement_key,
        "status": finding.status.value,
        "reason": finding.reason,
        "citations": citations,
    })


@app.get("/api/eval/shortlist")
def api_eval_shortlist() -> JSONResponse:
    """Return the best-match shortlist with reasons (Req 8.1-8.6)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse({"error": "No evaluation run yet."}, status_code=400)

    sl = run.shortlist
    entries = [
        {
            "bid_id": e.bid_id,
            "bidder_name": e.bidder_name,
            "rank": e.rank,
            "eligible": e.eligible,
            "price": e.price,
            "weighted_score": e.weighted_score,
            "strengths": list(e.strengths),
            "gaps": list(e.gaps),
            "risks": list(e.risks),
            "reasons": list(e.reasons),
            "blocking_reasons": list(e.blocking_reasons),
        }
        for e in sl.entries
    ]
    return JSONResponse({
        "run_id": run.run_id,
        "entries": entries,
        "best_match_bid_id": sl.best_match_bid_id,
        "none_eligible": sl.none_eligible,
        "final_selection": (
            run.final_selection.model_dump() if run.final_selection else None
        ),
    })


def _apply_override(run, override: OfficerOverride) -> None:
    """Apply an override to the relevant finding/completeness/capacity in place."""
    evaluation = next(
        (e for e in run.evaluations if e.bid.bid_id == override.bid_id), None
    )
    if evaluation is None:
        return

    target = override.target.lower()
    if target == "coverage":
        finding = next(
            (f for f in evaluation.coverage if f.requirement_key == override.item_key),
            None,
        )
        if finding is not None:
            try:
                finding.status = CoverageStatus(override.new_value)
            except ValueError:
                pass
            finding.officer_overridden = True
    elif target == "completeness":
        comp = evaluation.completeness
        comp.complete = override.new_value.strip().lower() in ("true", "complete", "1", "yes")
        comp.officer_overridden = True
    elif target == "capacity":
        cap = evaluation.capacity
        cap.capacity_qualified = override.new_value.strip().lower() in (
            "true", "qualified", "1", "yes",
        )
        cap.officer_overridden = True


@app.post("/api/eval/override")
def api_eval_override(payload: OverrideIn) -> JSONResponse:
    """Record + apply an officer override (justification required, Req 9.2, 9.3, 10.2)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse({"error": "No evaluation run yet."}, status_code=400)

    if not (payload.justification or "").strip():
        return JSONResponse(
            {"error": "A non-empty justification is required for an override."},
            status_code=400,
        )

    override = OfficerOverride(
        target=payload.target,
        bid_id=payload.bid_id,
        item_key=payload.item_key,
        new_value=payload.new_value,
        justification=payload.justification.strip(),
        timestamp=_dt.datetime.now().isoformat(timespec="seconds"),
    )

    _apply_override(run, override)
    audit.append_action(run, override)

    # An override affecting eligibility (coverage/completeness/capacity) can
    # change the shortlist, so re-rank.
    from .evaluation import ranking as _ranking
    run.shortlist = _ranking.build_shortlist(run.evaluations)
    STATE["eval_run"] = run

    try:
        persisted = audit.persist_run(run)
        STATE["run_id"] = run.run_id
        persisted_name = persisted.name
    except Exception as exc:  # noqa: BLE001
        persisted_name = None

    return JSONResponse({
        "ok": True,
        "override": override.model_dump(),
        "shortlist": {
            "best_match_bid_id": run.shortlist.best_match_bid_id,
            "none_eligible": run.shortlist.none_eligible,
        },
        "persisted": persisted_name,
    })


@app.post("/api/eval/select")
def api_eval_select(payload: SelectIn) -> JSONResponse:
    """Confirm the final selection (officer-only, Req 9.4, 9.5)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse({"error": "No evaluation run yet."}, status_code=400)

    if not run.shortlist.entries:
        return JSONResponse(
            {"error": "Cannot select before a shortlist exists. Release bids to scoring first."},
            status_code=400,
        )

    selection = FinalSelection(
        bid_id=payload.bid_id,
        justification=(payload.justification or "").strip(),
        timestamp=_dt.datetime.now().isoformat(timespec="seconds"),
    )
    audit.append_action(run, selection)
    STATE["eval_run"] = run

    sel_bid_id = run.final_selection.bid_id if run.final_selection else payload.bid_id
    match = next((e for e in run.shortlist.entries if e.bid_id == sel_bid_id), None)
    bidder = (match.bidder_name if match else "") or sel_bid_id
    try:
        store.update_evaluation_awarded(run.run_id, bidder)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("update_evaluation_awarded failed: %s", exc)

    try:
        persisted = audit.persist_run(run)
        STATE["run_id"] = run.run_id
        persisted_name = persisted.name
    except Exception:  # noqa: BLE001
        persisted_name = None

    return JSONResponse({
        "ok": True,
        "final_selection": selection.model_dump(),
        "persisted": persisted_name,
    })


@app.get("/api/eval/report")
def api_eval_report():
    """Download an evaluation report (Req 10.4)."""
    run = STATE.get("eval_run")
    if run is None:
        return JSONResponse({"error": "No evaluation run yet."}, status_code=400)

    lines = [
        "# Evaluation Report",
        f"Run: {run.run_id}",
        f"Tender: {run.tender.tender_reference_no}",
        f"Generated: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Shortlist",
    ]
    sl = run.shortlist
    lines.append(f"Best match: {sl.best_match_bid_id or '(none eligible)'}")
    for e in sl.entries:
        rank = e.rank if e.rank is not None else "-"
        lines.append(
            f"  [{rank}] {e.bidder_name or e.bid_id} "
            f"(eligible={e.eligible}, price={e.price}, score={e.weighted_score})"
        )
        for r in e.reasons:
            lines.append(f"      reason: {r}")
        for b in e.blocking_reasons:
            lines.append(f"      blocked: {b}")
    if run.final_selection:
        lines.append("")
        lines.append("## Final Selection")
        lines.append(f"  bid_id: {run.final_selection.bid_id}")
        lines.append(f"  justification: {run.final_selection.justification}")
        lines.append(f"  timestamp: {run.final_selection.timestamp}")

    report = "\n".join(lines)
    name = f"evaluation_report_{_safe_name(run.run_id)}_{_eval_timestamp()}.md"
    target = _resolve_in_eval_dir(name)
    if target is None:
        return JSONResponse({"error": "Invalid report path."}, status_code=400)
    target.write_text(report, encoding="utf-8")
    return FileResponse(str(target), filename=target.name, media_type="text/markdown")


@app.get("/api/eval/audit/{run_id}")
def api_eval_audit(run_id: str) -> JSONResponse:
    """Return the persisted AuditRecord for a run (Req 10.4).

    audit.load_run already resolves within EVAL_DIR only (path-traversal safe).
    """
    try:
        record = audit.load_run(run_id)
    except FileNotFoundError:
        return JSONResponse({"error": "No audit record for that run_id."}, status_code=404)
    return JSONResponse(record.model_dump())


@app.get("/api/eval/document")
def api_eval_document(bid_id: str, filename: str):
    """Serve a bid document for the "Open Document" link, path-safe.

    Resolves ONLY within the uploaded-bid area under EVAL_DIR (mirrors the
    download() guard). The document is located by filename within the bid's
    extracted/uploaded tree.
    """
    safe_bid = _safe_name(bid_id)
    bid_root = _resolve_in_eval_dir("uploads", safe_bid)
    run = STATE.get("eval_run")
    # Prefer the run's extracted dir if present, else the uploads area.
    candidates: list[Path] = []
    if bid_root is not None and bid_root.exists():
        candidates.append(bid_root)
    run_extract = _resolve_in_eval_dir(f"run_{run.run_id}", safe_bid) if run else None
    if run_extract is not None and run_extract.exists():
        candidates.append(run_extract)

    target_name = Path(filename).name  # strip any directory component
    for root in candidates:
        for path in root.rglob(target_name):
            resolved = path.resolve()
            # Confirm containment within EVAL_DIR.
            if _resolve_in_eval_dir() is None:
                continue
            if config.EVAL_DIR.resolve() in resolved.parents and resolved.is_file():
                return FileResponse(str(resolved), filename=resolved.name)

    return JSONResponse({"error": "Document not found."}, status_code=404)


@app.post("/api/eval/reset")
def api_eval_reset() -> JSONResponse:
    """Clear Stage 3 in-memory state (uploads + current run)."""
    STATE["eval_run"] = None
    STATE["eval_uploads"] = {}
    STATE["run_id"] = None
    STATE["checks_run"] = 0
    return JSONResponse({"ok": True})
