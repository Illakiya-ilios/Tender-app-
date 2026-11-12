"""Requirement collection: turn officer chat into a structured TenderBrief,
then draft the narrative sections with Gemini.
"""
from __future__ import annotations

import json

from . import llm
from .models import TenderBrief, ArchitectureItem

EXTRACT_SYSTEM = (
    "You are a government tender requirement assistant for Tamil Nadu / GeM style "
    "e-tenders. Extract structured fields from the officer's message. "
    "Return ONLY a JSON object, no prose. Use empty strings for unknown fields. "
    "Do not invent reference numbers, amounts, dates, phone numbers, or emails. "
    "Separate contact details into 'contact_name', 'contact_phone', and "
    "'contact_email'. Capture the pre-bid meeting date/time in 'pre_bid_datetime' "
    "and its location in 'pre_bid_venue'. "
    "For 'scope_notes' capture any description of WHAT is being procured/the need. "
    "For 'technical_inputs' capture any mention of servers, compute, storage, RAM, "
    "operating systems, bandwidth, software, technologies, or quantities, verbatim."
)

# Free-form fields that accumulate across messages instead of being overwritten.
APPEND_FIELDS = {"scope_notes", "technical_inputs"}

EXTRACT_FIELDS = [
    "tender_inviting_authority", "authority_address", "authority_contact",
    "name_of_work", "tender_reference_no", "emd_amount", "bid_type",
    "pre_bid_datetime", "pre_bid_venue",
    "contact_name", "contact_phone", "contact_email",
    "submission_due_datetime", "bid_opening_datetime",
    "bid_validity_days", "estimated_value", "contract_period",
    "portal_url", "governing_law", "jurisdiction",
    "scope_notes", "technical_inputs",
]


def extract_fields(message: str, current: TenderBrief) -> TenderBrief:
    """Merge new field values parsed from `message` into `current`."""
    prompt = (
        f"Current known values (JSON):\n{current.model_dump_json(indent=2)}\n\n"
        f"Officer message:\n\"\"\"{message}\"\"\"\n\n"
        f"Extract/update these fields: {EXTRACT_FIELDS}. "
        "Return a JSON object with only the fields you can fill from the message. "
        "Keep existing values if the message does not mention them."
    )
    raw = llm.generate(prompt, system=EXTRACT_SYSTEM, temperature=0.1)
    data = _parse_json(raw)
    if data:
        merged = current.model_dump()
        for k, v in data.items():
            if k not in EXTRACT_FIELDS or not isinstance(v, str) or not v.strip():
                continue
            v = v.strip()
            if k in APPEND_FIELDS and merged.get(k):
                # Accumulate detail across turns, avoiding duplicates.
                if v.lower() not in merged[k].lower():
                    merged[k] = f"{merged[k]}\n{v}"
            else:
                merged[k] = v
        return TenderBrief(**merged)
    return current


def next_question(brief: TenderBrief) -> str:
    """Guide the officer: core fields -> use case -> (architecture) -> generate."""
    missing = brief.missing_core_fields()
    if missing:
        labels = {
            "tender_inviting_authority": "the tender inviting authority (name, designation, office)",
            "name_of_work": "the name/title of the work being procured",
            "tender_reference_no": "the tender reference number",
            "emd_amount": "the Earnest Money Deposit (EMD) amount",
            "submission_due_datetime": "the last date & time for bid submission",
            "pre_bid_datetime": "the pre-bid meeting date & time",
            "pre_bid_venue": "the pre-bid meeting venue",
            "contact_name": "the contact person's name",
            "contact_phone": "the contact phone number",
            "contact_email": "the contact email address",
        }
        return f"Could you tell me {labels.get(missing[0], missing[0])}?"

    if not brief.scope_notes:
        return (
            "Core details captured. Now describe the use case in plain language - "
            "what should the solution do and who will use it? "
            "(e.g. 'a hostel management app for ~500 students at our college'). "
            "You don't need any technical knowledge; I'll propose the architecture."
        )

    if not brief.architecture:
        return (
            "Thanks. Click 'Suggest Architecture' and I'll propose a suitable "
            "technical setup (servers, storage, OS, security, etc.) for this use "
            "case. If you already know specific resources you want, tell me and "
            "I'll use those instead."
        )

    return (
        "The architecture is ready and the brief is complete. Review the suggested "
        "components, tell me any changes, then click 'Generate Tender + BOQ'. "
        "The document and the BOQ are built from the same component list, so they "
        "will always match."
    )


# ---------------------------------------------------------------------------
# Solution architect: propose a technical architecture from a plain use case.
# ---------------------------------------------------------------------------

ARCHITECT_SYSTEM = (
    "You are a senior cloud/solution architect helping a NON-TECHNICAL government "
    "officer turn a plain-language use case into a concrete, procurement-ready "
    "technical architecture for an Indian government e-tender. "
    "Propose realistic, right-sized components (compute, storage, database, "
    "backup, networking, security, support, etc.). Prefer India-region cloud and "
    "government-appropriate security. Be specific but not excessive. "
    "If the officer already specified certain resources, HONOUR them exactly and "
    "build the rest of the architecture around them. "
    "Return ONLY a JSON array, no prose."
)

ARCHITECT_SCHEMA = (
    "Each array element must be an object with keys: "
    "\"category\" (short, e.g. 'Compute', 'Storage', 'Database', 'Backup', "
    "'Networking', 'Security', 'Support', 'Migration'), "
    "\"description\" (concrete spec, e.g. '4 vCPU, 16 GB RAM VM with Ubuntu 22.04'), "
    "\"quantity\" (number), "
    "\"units\" (e.g. 'No', 'Count', 'GB', 'Monthly', 'per VM'), "
    "\"rationale\" (one short sentence on why it is needed), "
    "\"mandatory\" (true/false), "
    "\"source\" ('officer' if the officer specified it, else 'suggested')."
)


def propose_architecture(brief: TenderBrief) -> TenderBrief:
    """Ask Gemini to propose a structured architecture for the use case.

    Officer-specified resources (technical_inputs) are honoured and marked
    source='officer'; everything else is marked 'suggested'.
    """
    prompt = (
        f"Tender title: {brief.name_of_work}\n"
        f"Contract period: {brief.contract_period or '(not specified)'}\n"
        f"Estimated value: {brief.estimated_value or '(not specified)'}\n\n"
        f"Officer's use case (plain language):\n\"\"\"{brief.scope_notes}\"\"\"\n\n"
        f"Resources the officer already specified (treat as fixed, source='officer'):\n"
        f"\"\"\"{brief.technical_inputs or '(none)'}\"\"\"\n\n"
        f"Produce a JSON array describing the full technical architecture. {ARCHITECT_SCHEMA}\n"
        "Keep it to the components genuinely needed for this use case "
        "(typically 5-12 items). Return ONLY the JSON array."
    )
    raw = llm.generate(prompt, system=ARCHITECT_SYSTEM, temperature=0.3)
    architecture = _items_from_json_array(_parse_json_array(raw), default_source="suggested")
    if architecture:
        brief.architecture = architecture
    return brief


# ---------------------------------------------------------------------------
# Parse an architecture the officer PASTED into chat (free text / table / list).
# ---------------------------------------------------------------------------

PARSE_SYSTEM = (
    "You convert an officer's PASTED technical architecture (free text, bullet "
    "list, or table) into a structured JSON array of procurement components. "
    "Do NOT invent components the officer did not mention. Preserve their "
    "quantities and specs. Return ONLY a JSON array, no prose."
)


def looks_like_architecture(text: str) -> bool:
    """Heuristic: does this pasted message describe a technical architecture?"""
    t = text.lower()
    # Needs some length and several infra/technical signals to qualify.
    if len(text) < 120:
        return False
    signals = (
        "architecture", "component", "compute", "storage", "database", "vcpu",
        "ram", "server", "vm ", "load balancer", "autoscal", "fargate", "ecs",
        "eks", "kubernetes", "s3", "rds", "aurora", "redis", "vpc", "iam",
        "backup", "cloudwatch", "monitoring", "qty:", "quantity", "managed service",
    )
    hits = sum(1 for s in signals if s in t)
    return hits >= 4


def parse_architecture_from_text(text: str, brief: TenderBrief) -> list[ArchitectureItem]:
    """Turn a pasted architecture into structured components (source='officer')."""
    prompt = (
        f"Officer's pasted architecture:\n\"\"\"{text}\"\"\"\n\n"
        f"Convert it into a JSON array. {ARCHITECT_SCHEMA}\n"
        "Set source='officer' for every item (the officer supplied these). "
        "If a quantity is not stated, use 1. Return ONLY the JSON array."
    )
    raw = llm.generate(prompt, system=PARSE_SYSTEM, temperature=0.1)
    return _items_from_json_array(_parse_json_array(raw), default_source="officer")


# Verbs that signal the officer wants to CHANGE an existing architecture.
_CHANGE_VERBS = (
    "add", "remove", "delete", "drop", "replace", "change", "increase",
    "decrease", "reduce", "update", "swap", "rename", "set ", "make ",
    "instead of", "more", "less", "additional", "also include", "take out",
)


def looks_like_change_request(text: str) -> bool:
    """Heuristic: is this a short instruction to modify the current architecture?"""
    t = text.strip().lower()
    if len(t) > 600:          # long -> probably a fresh paste, not a tweak
        return False
    return any(v in t for v in _CHANGE_VERBS)


MODIFY_SYSTEM = (
    "You edit an existing procurement technical architecture based on the "
    "officer's change request. Apply ONLY the requested changes: add, remove, "
    "replace, or adjust quantities/specs of components. Keep all other components "
    "exactly as they are. Preserve each item's existing 'source'; set 'officer' "
    "for any new item the officer asks to add. Return ONLY the full updated JSON "
    "array (all components, not just the changed ones)."
)


def apply_architecture_changes(current: list[ArchitectureItem], instruction: str
                               ) -> list[ArchitectureItem]:
    """Apply a natural-language change to an existing architecture list."""
    current_json = "[\n" + ",\n".join(a.model_dump_json() for a in current) + "\n]"
    prompt = (
        f"Current architecture (JSON array):\n{current_json}\n\n"
        f"Officer's change request:\n\"\"\"{instruction}\"\"\"\n\n"
        f"Return the FULL updated architecture as a JSON array. {ARCHITECT_SCHEMA}"
    )
    raw = llm.generate(prompt, system=MODIFY_SYSTEM, temperature=0.1)
    updated = _items_from_json_array(_parse_json_array(raw), default_source="officer")
    # If the model returned nothing usable, keep the current architecture.
    return updated or current


def _items_from_json_array(items, default_source: str) -> list[ArchitectureItem]:
    architecture: list[ArchitectureItem] = []
    for obj in items or []:
        if not isinstance(obj, dict):
            continue
        try:
            architecture.append(ArchitectureItem(
                category=str(obj.get("category", "Component")).strip() or "Component",
                description=str(obj.get("description", "")).strip(),
                quantity=_to_number(obj.get("quantity", 1)),
                units=str(obj.get("units", "No")).strip() or "No",
                rationale=str(obj.get("rationale", "")).strip(),
                mandatory=bool(obj.get("mandatory", True)),
                source=str(obj.get("source", default_source)).strip() or default_source,
            ))
        except Exception:  # noqa: BLE001 - skip malformed entries
            continue
    return architecture


DRAFT_SYSTEM = (
    "You are a procurement officer drafting a formal Indian government e-tender "
    "document, in the detailed style of Tamil Nadu Public Procurement / GeM "
    "tenders. Write thorough, professional, legally-worded content suitable for a "
    "real published tender. Use numbered clauses (1., 2., 3. ...) and sub-clauses "
    "(a), (b)) where appropriate. Do NOT use markdown: no ** for bold, no # "
    "headings, no --- rules, and do not repeat the section title as a heading. "
    "Use ONLY the facts provided; where a specific figure is not given, use the "
    "value already stated in the tender data or write 'as specified in the Tender "
    "Data Sheet'. Never fabricate concrete amounts, dates, or certifications."
)


def _draft(context: str, instruction: str) -> str:
    return llm.generate(context + "\n" + instruction, system=DRAFT_SYSTEM,
                        temperature=0.45)


def draft_sections(brief: TenderBrief, extra_notes: str = "") -> TenderBrief:
    """Draft all narrative sections in depth so the document reads like a full
    government tender. Technical Requirements is NOT drafted here - it renders
    directly from the approved architecture, so it can never diverge from the BOQ."""
    scope_src = " ".join(filter(None, [brief.scope_notes, extra_notes])).strip()

    # Compact architecture summary to ground delivery/SLA/payment sections.
    arch_summary = "; ".join(
        f"{a.category}: {a.description} (x{a.quantity} {a.units})"
        for a in brief.architecture
    ) or "(architecture to be specified)"

    context = (
        f"Tender title: {brief.name_of_work}\n"
        f"Inviting authority: {brief.tender_inviting_authority}\n"
        f"Address: {brief.authority_address or '(as per Tender Data Sheet)'}\n"
        f"Contract period: {brief.contract_period or 'as specified in the Tender Data Sheet'}\n"
        f"Estimated value: {brief.estimated_value or 'as specified in the Tender Data Sheet'}\n"
        f"EMD: {brief.emd_amount or 'as specified in the Tender Data Sheet'}\n"
        f"Bid validity: {brief.bid_validity_days} days\n"
        f"Last date of submission: {brief.submission_due_datetime}\n"
        f"Governing law: {brief.governing_law}\n"
        f"Jurisdiction: {brief.jurisdiction or '(as applicable)'}\n"
        f"Approved technical architecture: {arch_summary}\n"
        f"Officer's description of the need: \"\"\"{scope_src or '(none provided)'}\"\"\"\n"
    )

    brief.introduction = _draft(
        context,
        "Write the 'Introduction and Preamble' section (2-3 paragraphs) introducing "
        "the inviting authority and the purpose of this tender, and inviting sealed "
        "competitive bids from eligible bidders.",
    )
    brief.scope_of_work = _draft(
        context,
        "Write a detailed 'Scope of Work' section (250-400 words) describing the "
        "objectives, deliverables, responsibilities of the successful bidder, and "
        "expected outcomes, based ONLY on the use case and architecture above.",
    )
    brief.instructions_to_bidders = _draft(
        context,
        "Write a detailed numbered 'Instructions to Bidders' section covering bid "
        "preparation, the two-part (technical and price) bid structure, EMD "
        "submission, bid validity, mode of submission through the e-tender portal, "
        "last date and time, late bids, and clarification/pre-bid meeting process.",
    )
    brief.payment_terms = _draft(
        context,
        "Write a numbered 'Payment Terms' section covering invoicing, milestones or "
        "periodic billing appropriate to the architecture, applicable taxes/GST, TDS, "
        "and the condition that no advance payment is made.",
    )
    brief.delivery_timeline = _draft(
        context,
        "Write a numbered 'Delivery, Implementation and Commissioning Schedule' "
        "section describing provisioning/implementation timelines from the Work "
        "Order, acceptance testing, training/handover, and penalties for delay.",
    )
    brief.sla_terms = _draft(
        context,
        "Write a numbered 'Service Level Agreement (SLA) and Penalties' section "
        "covering availability/uptime expectations, support response times, "
        "escalation, and penalty deductions for breaches. Keep specific percentages "
        "generic unless provided.",
    )
    brief.terms_and_conditions = _draft(
        context,
        "Write a comprehensive numbered 'General Terms and Conditions' section "
        "(at least 12 clauses) covering: eligibility to the extent stated, "
        "confidentiality, conflict of interest, force majeure, indemnity, "
        "limitation of liability, termination (for default, insolvency, "
        "convenience), effects of termination, assignment, dispute resolution and "
        "jurisdiction, and the authority's right to reject bids.",
    )
    return brief


def _to_number(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 1.0


def _parse_json_array(raw: str) -> list | None:
    data = _parse_json(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Sometimes the model wraps the array, e.g. {"items": [...]}.
        for v in data.values():
            if isinstance(v, list):
                return v
    return None


def _parse_json(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except (ValueError, json.JSONDecodeError):
        return None


