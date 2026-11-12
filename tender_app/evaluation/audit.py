"""Stage 3 (10): audit persistence (pure I/O — no LLM).

An :class:`EvaluationRun` is the live, in-memory state of a run. When the
officer persists it, this module serialises it into an :class:`AuditRecord`
(the stable, archival shape) and writes it as JSON to ``config.EVAL_DIR`` with a
UNIQUE timestamped filename (``audit_{run_id}_{YYYYMMDD_HHMMSS}.json``). The
unique-filename approach mirrors the Stage 1/2 output convention and avoids
Windows open-file write failures (Req 10.1, 10.3).

The persisted JSON preserves every evidence citation because citations live
inside the nested models (``CoverageFinding.citations``, ``BidPrice.citation``,
``CapacityItemResult.citations``, ``DocCheckCell.citations``); pydantic's
``model_dump_json`` serialises the whole tree, enums included.

``append_action`` records an officer override (appended to ``run.overrides``) or
a final selection (set on ``run.final_selection``) in place, each carrying the
justification + timestamp fields the models already define (Req 10.2).

``load_run`` loads a persisted record back for officer review. It resolves the
file strictly within ``config.EVAL_DIR`` (path-traversal safe, mirroring the
existing ``download()`` guard in ``app.py``) and, when several timestamped files
exist for a run id, loads the most recent (Req 10.4).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from tender_app import config
from tender_app.evaluation.models import (
    AuditRecord,
    EvaluationRun,
    FinalSelection,
    OfficerOverride,
)

_FILENAME_PREFIX = "audit_"
_FILENAME_SUFFIX = ".json"


def _audit_record_from_run(run: EvaluationRun) -> AuditRecord:
    """Project an :class:`EvaluationRun` into its archival :class:`AuditRecord`.

    Copies the fields that make up the permanent record: identity, the tender
    reference, the per-bid evaluations (with their nested citations), the
    shortlist, the officer overrides, and the final selection.
    """
    return AuditRecord(
        run_id=run.run_id,
        created_at=run.created_at,
        tender_reference_no=run.tender.tender_reference_no,
        evaluations=run.evaluations,
        shortlist=run.shortlist,
        overrides=run.overrides,
        final_selection=run.final_selection,
    )


def persist_run(run: EvaluationRun) -> Path:
    """Serialise ``run`` to a timestamped :class:`AuditRecord` JSON file.

    Writes to ``config.EVAL_DIR`` with a unique
    ``audit_{run_id}_{YYYYMMDD_HHMMSS}.json`` filename (Req 10.1, 10.3). Returns
    the :class:`~pathlib.Path` that was written. All coverage and price
    citations are preserved because they are nested inside the serialised
    models.
    """
    record = _audit_record_from_run(run)

    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{_FILENAME_PREFIX}{run.run_id}_{timestamp}{_FILENAME_SUFFIX}"
    target = config.EVAL_DIR / filename

    # pydantic serialises the full nested tree, enums as their string values.
    target.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return target


def append_action(
    run: EvaluationRun, action: OfficerOverride | FinalSelection
) -> None:
    """Record an officer action on the run in place (Req 10.2).

    - An :class:`OfficerOverride` is appended to ``run.overrides``.
    - A :class:`FinalSelection` is set as ``run.final_selection``.

    Both carry their own ``justification`` / ``timestamp`` fields, so the
    override/selection, its justification and its timestamp are recorded
    together.
    """
    if isinstance(action, OfficerOverride):
        run.overrides.append(action)
    elif isinstance(action, FinalSelection):
        run.final_selection = action
    else:  # defensive: only the two documented action types are accepted.
        raise TypeError(
            "append_action accepts an OfficerOverride or FinalSelection, "
            f"got {type(action).__name__}"
        )


def _find_run_files(run_id: str) -> list[Path]:
    """Return every persisted audit file for ``run_id``, resolved inside EVAL_DIR.

    Path-traversal safe: each candidate is resolved and confirmed to live
    directly inside ``config.EVAL_DIR`` before being returned, mirroring the
    ``download()`` guard in ``app.py``. A hostile ``run_id`` (containing ``..``
    or path separators) therefore matches nothing.
    """
    eval_dir = config.EVAL_DIR.resolve()
    pattern = f"{_FILENAME_PREFIX}{run_id}_*{_FILENAME_SUFFIX}"

    matches: list[Path] = []
    for candidate in eval_dir.glob(pattern):
        resolved = candidate.resolve()
        # Confirm the file is contained directly within EVAL_DIR.
        if eval_dir not in resolved.parents or not resolved.is_file():
            continue
        matches.append(resolved)
    return matches


def load_run(run_id: str) -> AuditRecord:
    """Load the persisted :class:`AuditRecord` for ``run_id`` (Req 10.4).

    Searches ``config.EVAL_DIR`` ONLY (path-traversal safe). When multiple
    timestamped files exist for the same run id, the most recent (highest
    timestamp, i.e. lexicographically greatest filename) is loaded. Raises
    :class:`FileNotFoundError` when no audit file exists for the run id.
    """
    matches = _find_run_files(run_id)
    if not matches:
        raise FileNotFoundError(
            f"No audit record found for run_id {run_id!r} in {config.EVAL_DIR}"
        )

    # Filenames embed a sortable _YYYYMMDD_HHMMSS timestamp, so the
    # lexicographically greatest name is the most recent run.
    latest = max(matches, key=lambda p: p.name)
    return AuditRecord.model_validate_json(latest.read_text(encoding="utf-8"))
