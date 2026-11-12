"""Field model for a tender, derived from the three sample tenders.

Key design: the technical architecture is a single list of ArchitectureItem
objects. BOTH the PDF 'Technical Requirements' section AND the BOQ price
schedule are rendered from this one list, so they can never conflict.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class ArchitectureItem(BaseModel):
    """One technical component in the solution architecture.

    This is the single source of truth. It renders into:
      - a Technical Requirements bullet (category + description + rationale)
      - a BOQ line item (description + quantity + units)
    """
    category: str                      # e.g. "Compute", "Storage", "Security"
    description: str                   # e.g. "2 vCPU, 4 GB RAM VM with Ubuntu OS"
    quantity: float = 1
    units: str = "No"                  # e.g. "No", "Count", "GB", "Monthly"
    rationale: str = ""                # why this is needed (for the officer / doc)
    mandatory: bool = True
    source: str = "suggested"          # "suggested" (AI) or "officer" (specified)


class BOQItem(BaseModel):
    """A rendered price-schedule line (derived from ArchitectureItem)."""
    sl_no: int
    item_description: str
    item_code: str = ""
    quantity: float = 1
    units: str = "No"
    estimated_rate: Optional[float] = None
    mandatory: bool = False


class TenderBrief(BaseModel):
    """Structured requirement brief collected from chat."""

    # --- Header / data sheet fields (common to all three samples) ---
    tender_inviting_authority: str = ""
    authority_address: str = ""
    authority_contact: str = ""         # legacy free-text contact (kept for compat)
    name_of_work: str = ""
    tender_reference_no: str = ""
    emd_amount: str = ""
    bid_type: str = "Two part (Technical bid and Price bid)"

    # Pre-bid meeting (mandatory): when and where.
    pre_bid_datetime: str = ""
    pre_bid_venue: str = ""

    # Contact person details (mandatory).
    contact_name: str = ""
    contact_phone: str = ""
    contact_email: str = ""

    submission_due_datetime: str = ""
    bid_opening_datetime: str = ""
    bid_validity_days: str = "180"
    estimated_value: str = ""
    contract_period: str = ""
    portal_url: str = "https://tntenders.gov.in"
    governing_law: str = "The Tamil Nadu Transparency in Tenders Act 1998"
    jurisdiction: str = ""

    # --- Officer-provided raw inputs ---
    scope_notes: str = ""              # the use case, in the officer's words
    technical_inputs: str = ""         # specific resources the officer already knows

    # --- Single source of truth for the technical solution ---
    architecture: list[ArchitectureItem] = Field(default_factory=list)
    architecture_approved: bool = False

    # --- Narrative body (drafted in depth from the above) ---
    introduction: str = ""             # preamble / about the inviting authority
    scope_of_work: str = ""
    instructions_to_bidders: str = ""  # how to prepare & submit bids
    payment_terms: str = ""
    delivery_timeline: str = ""        # delivery / implementation schedule
    sla_terms: str = ""                # service levels & penalties
    terms_and_conditions: str = ""     # general conditions / legal clauses

    def missing_core_fields(self) -> list[str]:
        core = [
            "tender_inviting_authority", "name_of_work",
            "tender_reference_no", "emd_amount", "submission_due_datetime",
            "pre_bid_datetime", "pre_bid_venue",
            "contact_name", "contact_phone", "contact_email",
        ]
        return [f for f in core if not getattr(self, f)]

    def completeness(self) -> int:
        """Progress toward a generatable tender.

        Reaches 100% exactly when the document can be generated:
          - all mandatory core fields filled  -> 80%
          - a use-case / scope described       -> +10%
          - an architecture approved           -> +10%
        Optional fields (address, estimated value, etc.) do not block 100%.
        """
        mandatory = [f for f in [
            "tender_inviting_authority", "name_of_work", "tender_reference_no",
            "emd_amount", "submission_due_datetime", "pre_bid_datetime",
            "pre_bid_venue", "contact_name", "contact_phone", "contact_email",
        ]]
        filled = sum(1 for f in mandatory if getattr(self, f))
        score = filled / len(mandatory) * 80
        if self.scope_notes:
            score += 10
        if self.architecture and self.architecture_approved:
            score += 10
        return round(score)

    def boq_items(self) -> list[BOQItem]:
        """Derive BOQ line items from the architecture (single source of truth)."""
        items: list[BOQItem] = []
        for i, a in enumerate(self.architecture, start=1):
            items.append(BOQItem(
                sl_no=i,
                item_description=f"{a.category}: {a.description}",
                item_code=f"item{i}",
                quantity=a.quantity,
                units=a.units,
                mandatory=a.mandatory,
            ))
        return items
