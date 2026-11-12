"""Source_Tender derivation module.

This is the single module that reads the Source_Tender (the fixed Bidder
Eligibility Criteria in ``eligibility.py`` plus the issued ``TenderBrief`` and
its approved ``architecture``) and emits:

  * the :class:`RequiredDocumentType` set (Req 3.3), and
  * the :class:`RequirementItem` list across the four requirement classes (Req 5.1).

Both functions are **deterministic and contain no LLM calls**: the same tender
always yields identical output, with stable ordering and stable keys. Determinism
matters because these outputs anchor every downstream stage (classification,
completeness, coverage, capacity) and the audit record, so they must be
reproducible across runs.

The documentary-proof column of ``ELIGIBILITY_ROWS`` is free text that bundles
several discrete proofs per row (for example row 1 lists Certificate of
Incorporation, MOA/AOA, GST and PAN). Rather than parse that prose at runtime
(brittle and non-deterministic across wording tweaks), each eligibility row is
mapped to an explicit, ordered list of stable document-type definitions. The
mapping mirrors the proof text verbatim-in-intent and is the stable contract
the rest of Stage 3 relies on.
"""
from __future__ import annotations

from tender_app.eligibility import ELIGIBILITY_ROWS
from tender_app.evaluation.models import (
    RequiredDocumentType,
    RequirementClass,
    RequirementItem,
)
from tender_app.models import TenderBrief


# ---------------------------------------------------------------------------
# Stable document-type definitions, keyed to each eligibility row.
#
# The outer list index matches the index of the row in ``ELIGIBILITY_ROWS``
# whose documentary-proof column the document types are derived from. Each
# entry is ``(key, label, description)``. Keys are stable identifiers used as
# the single reference for a document type across the whole pipeline and the
# audit record; they must never change once a bid has been evaluated.
# ---------------------------------------------------------------------------
_ROW_DOCUMENT_TYPES: list[list[tuple[str, str, str]]] = [
    # Row 0 — legal registration proofs.
    [
        (
            "incorporation_cert",
            "Certificate of Incorporation / Registration",
            "Certificate of Incorporation or Certificate of Registration proving "
            "the bidder is a validly constituted company, LLP or partnership firm.",
        ),
        (
            "moa_aoa",
            "Memorandum & Articles of Association / Partnership Deed",
            "Memorandum and Articles of Association, or the Partnership Deed for a "
            "partnership firm / LLP.",
        ),
        (
            "gst",
            "GST Certificate",
            "Goods and Services Tax registration certificate of the bidder.",
        ),
        (
            "pan",
            "PAN Card",
            "Copy of the bidder's Permanent Account Number (PAN) card.",
        ),
    ],
    # Row 1 — MeitY empanelment / CSP authorization.
    [
        (
            "meity_empanelment",
            "MeitY Empanelment Certificate",
            "MeitY empanelment certificate issued in the name of the CSP for "
            "providing cloud services.",
        ),
        (
            "csp_authorization",
            "CSP Authorization Certificate",
            "Authorization certificate issued in the name of the MSP / bidder by "
            "the empaneled CSP.",
        ),
    ],
    # Row 2 — partner engagement duration (same authorization proof, with tenure).
    [
        (
            "csp_authorization",
            "CSP Authorization Certificate",
            "Authorization certificate from a MeitY empaneled CSP authorizing the "
            "bidder and mentioning the years of engagement; work orders preferred.",
        ),
    ],
    # Row 3 — turnover.
    [
        (
            "ca_turnover",
            "CA / Statutory Auditor Turnover Certificate",
            "Certificate from the Statutory Auditor / Chartered Accountant "
            "specifying turnover during the last five financial years.",
        ),
    ],
    # Row 4 — quality / service-management certifications.
    [
        (
            "iso_9001",
            "ISO 9001:2015 Certificate",
            "Self-certified copy of ISO 9001:2015 certification valid on the date "
            "of bid submission.",
        ),
        (
            "iso_20000",
            "ISO 20000-1:2018 Certificate",
            "Self-certified copy of ISO 20000-1:2018 certification valid on the "
            "date of bid submission.",
        ),
    ],
    # Row 5 — office in Chennai.
    [
        (
            "office_chennai",
            "Chennai Office Proof / Undertaking",
            "Proof of a full-fledged operational office in Chennai, or an "
            "undertaking to set one up within 30 days of empanelment.",
        ),
    ],
    # Row 6 — website.
    [
        (
            "website",
            "Bidder Website Proof",
            "The URL of the bidder's own website and a printout of its home page.",
        ),
    ],
]


def required_document_types(tender: TenderBrief) -> list[RequiredDocumentType]:
    """Derive the ``RequiredDocumentType`` set for the Source_Tender. (Req 3.3)

    The set comes from the documentary-proof column of every row in
    ``eligibility.ELIGIBILITY_ROWS`` (expanded into discrete document types via
    the stable ``_ROW_DOCUMENT_TYPES`` mapping) followed by any tender-specific
    required documents (currently the price schedule, which every bid must
    carry so it can be priced in Stage 7).

    De-duplication is by ``key`` with first-occurrence wins, so a document type
    referenced by more than one eligibility row (for example the CSP
    authorization certificate in rows 1 and 2) appears exactly once. Ordering is
    the stable row order, then within-row order, then the tender-specific tail —
    identical for identical input.
    """
    seen: set[str] = set()
    types: list[RequiredDocumentType] = []

    def _add(key: str, label: str, description: str) -> None:
        if key in seen:
            return
        seen.add(key)
        types.append(
            RequiredDocumentType(key=key, label=label, description=description)
        )

    # Eligibility-derived document types, in stable row/within-row order. The
    # mapping is validated against the actual row count so a change to
    # ELIGIBILITY_ROWS surfaces here rather than silently dropping proofs.
    for row_index in range(len(ELIGIBILITY_ROWS)):
        if row_index >= len(_ROW_DOCUMENT_TYPES):
            break
        for key, label, description in _ROW_DOCUMENT_TYPES[row_index]:
            _add(key, label, description)

    # Tender-specific required documents (not part of the eligibility rows).
    _add(
        "price_schedule",
        "Price Schedule / BOQ",
        "The bidder's filled price schedule (Bill of Quantities) stating the "
        "total quoted price for the tendered scope.",
    )

    return types


# ---------------------------------------------------------------------------
# Short, stable keys for each eligibility row's requirement item. Index matches
# the row index in ``ELIGIBILITY_ROWS``. Keeping the keys explicit (rather than
# deriving them from the criterion prose) makes them stable across wording edits.
# ---------------------------------------------------------------------------
_ELIGIBILITY_ITEM_KEYS: list[str] = [
    "elig_legal_entity",
    "elig_csp_msp_empanelment",
    "elig_partner_tenure",
    "elig_turnover",
    "elig_iso_certifications",
    "elig_chennai_office",
    "elig_website",
]


def _slugify(value: str) -> str:
    """Deterministic lowercase ``snake_case`` slug for building stable keys.

    Keeps ASCII letters and digits, collapses every other run of characters to a
    single underscore, and trims leading/trailing underscores. Pure and
    order-independent, so equal inputs always produce equal slugs.
    """
    out: list[str] = []
    prev_underscore = False
    for ch in value.lower():
        if ch.isalnum() and ch.isascii():
            out.append(ch)
            prev_underscore = False
        elif not prev_underscore:
            out.append("_")
            prev_underscore = True
    return "".join(out).strip("_")


def requirement_items(tender: TenderBrief) -> list[RequirementItem]:
    """Derive the ``RequirementItem`` list across the four classes. (Req 5.1)

    Deterministic; no LLM. Items are produced in a fixed order:

    1. **Eligibility** — one ``RequirementClass.ELIGIBILITY`` item per row in
       ``eligibility.ELIGIBILITY_ROWS`` (the criterion column), in row order,
       with ``source_ref`` set to the row index.
    2. **Technical** — one ``RequirementClass.TECHNICAL`` item per
       ``ArchitectureItem`` in ``tender.architecture``, in list order, with a
       key made unique by position so repeated categories never collide and
       ``source_ref`` set to the architecture category.
    3. **Qualification / Capability** — fixed items derived from
       ``TenderBrief`` fields (contract period → qualification; estimated value
       / delivery timeline / SLA terms → capability), included only when the
       underlying field is populated so empty tenders stay minimal.

    For identical input the returned list is byte-for-byte identical.
    """
    items: list[RequirementItem] = []

    # 1. Eligibility items — one per eligibility row (criterion column).
    for row_index, (criterion, _proof) in enumerate(ELIGIBILITY_ROWS):
        if row_index < len(_ELIGIBILITY_ITEM_KEYS):
            key = _ELIGIBILITY_ITEM_KEYS[row_index]
        else:  # defensive: stable fallback if a row is added without a key
            key = f"elig_row_{row_index}"
        items.append(
            RequirementItem(
                key=key,
                req_class=RequirementClass.ELIGIBILITY,
                text=criterion,
                weight=1.0,
                source_ref=str(row_index),
            )
        )

    # 2. Technical items — one per architecture component (single source of truth).
    for arch_index, arch in enumerate(tender.architecture):
        slug = _slugify(arch.category) or "component"
        items.append(
            RequirementItem(
                key=f"tech_{arch_index}_{slug}",
                req_class=RequirementClass.TECHNICAL,
                text=f"{arch.category}: {arch.description}",
                weight=1.0,
                source_ref=arch.category,
            )
        )

    # 3. Qualification / capability items — from TenderBrief fields, only when
    #    the source field is populated (keeps an empty brief minimal & stable).
    qualification_fields: list[tuple[str, str, str]] = [
        (
            "qual_contract_period",
            "contract_period",
            "The bidder must be able to deliver and sustain the solution for the "
            "full contract period: {value}.",
        ),
    ]
    capability_fields: list[tuple[str, str, str]] = [
        (
            "cap_estimated_value",
            "estimated_value",
            "The bidder must demonstrate the organizational capacity to deliver a "
            "project of the tendered value: {value}.",
        ),
        (
            "cap_delivery_timeline",
            "delivery_timeline",
            "The bidder must demonstrate the capability to meet the delivery / "
            "implementation timeline: {value}.",
        ),
        (
            "cap_sla_terms",
            "sla_terms",
            "The bidder must demonstrate the capability to meet the service levels "
            "and SLA terms: {value}.",
        ),
    ]

    for key, field_name, template in qualification_fields:
        value = getattr(tender, field_name, "")
        if value:
            items.append(
                RequirementItem(
                    key=key,
                    req_class=RequirementClass.QUALIFICATION,
                    text=template.format(value=value),
                    weight=1.0,
                    source_ref=field_name,
                )
            )

    for key, field_name, template in capability_fields:
        value = getattr(tender, field_name, "")
        if value:
            items.append(
                RequirementItem(
                    key=key,
                    req_class=RequirementClass.CAPABILITY,
                    text=template.format(value=value),
                    weight=1.0,
                    source_ref=field_name,
                )
            )

    return items
