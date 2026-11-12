"""Stage 3 evaluation domain models.

Same ``pydantic.BaseModel`` style as ``tender_app/models.py`` (``from __future__
import annotations``, ``Field(default_factory=...)`` for list defaults, ``Optional``
for nullable). Enums use ``str, Enum`` so they serialize cleanly to JSON for the
audit record and the API.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from tender_app.models import TenderBrief


class CoverageStatus(str, Enum):
    SATISFIED = "Satisfied"
    PARTLY = "Partly Satisfied"
    NOT = "Not Satisfied"


class DocPresence(str, Enum):
    PRESENT = "Present"                       # present and readable
    PRESENT_UNREADABLE = "Present but unreadable"
    MISSING = "Missing"                       # "Not provided" in the UI


class ExtractionSource(str, Enum):
    TEXT = "text"          # pdfplumber
    OCR = "ocr"            # Gemini vision
    BOTH = "both"
    NONE = "none"          # unreadable


class RequirementClass(str, Enum):
    ELIGIBILITY = "eligibility"
    TECHNICAL = "technical"
    QUALIFICATION = "qualification"
    CAPABILITY = "capability"


class EvidenceCitation(BaseModel):
    """Grounds every finding in a source location. (Req 2.4/3.4/5.3/6.2/7.2)"""
    filename: str
    page: int
    quote: str = ""                            # cited text shown in Evidence panel


class RequiredDocumentType(BaseModel):
    """A category of required document derived from eligibility.py / tender."""
    key: str                                   # stable id e.g. "ca_turnover"
    label: str                                 # UI row label
    description: str = ""


class RequirementItem(BaseModel):
    """A single discrete requirement a bid must satisfy. (Req 5.1)"""
    key: str
    req_class: RequirementClass
    text: str
    weight: float = 1.0                        # for weighted score in the matrix
    source_ref: str = ""                       # e.g. eligibility row index / arch category


class ExtractedPage(BaseModel):
    page: int
    text: str = ""
    source: ExtractionSource = ExtractionSource.NONE


class ExtractedDocument(BaseModel):
    filename: str
    pages: list[ExtractedPage] = Field(default_factory=list)
    source: ExtractionSource = ExtractionSource.NONE   # per-document rollup (Req 2.4)
    readable: bool = True                              # False if unreadable (Req 2.5)


class SubDocument(BaseModel):
    """A logically distinct document inside a PDF (page range). (Req 3.1)"""
    filename: str
    page_start: int
    page_end: int
    classified_as: str = "Unclassified"        # RequiredDocumentType.key or "Unclassified" (Req 3.5)
    readable: bool = True
    text: str = ""


class CoverageFinding(BaseModel):
    requirement_key: str
    status: CoverageStatus
    citations: list[EvidenceCitation] = Field(default_factory=list)  # Req 5.3
    reason: str = ""                           # required when NOT (Req 5.4)
    officer_overridden: bool = False


class DocCheckCell(BaseModel):
    """One cell of the Bid Document Check matrix (doc type x bidder)."""
    document_key: str
    presence: DocPresence
    citations: list[EvidenceCitation] = Field(default_factory=list)


class CompletenessResult(BaseModel):
    bid_id: str
    complete: bool = False                     # Req 4.4/4.5
    cells: list[DocCheckCell] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)            # doc keys (Req 4.2)
    unreadable: list[str] = Field(default_factory=list)         # doc keys (Req 4.3)
    officer_overridden: bool = False


class CapacityItemResult(BaseModel):
    name: str                                  # "turnover" | "experience" | ...
    met: bool
    reason: str = ""                           # unmet reason (Req 6.4)
    citations: list[EvidenceCitation] = Field(default_factory=list)


class CapacityResult(BaseModel):
    bid_id: str
    capacity_qualified: bool = False           # Req 6.3
    items: list[CapacityItemResult] = Field(default_factory=list)
    officer_overridden: bool = False


class BidPrice(BaseModel):
    bid_id: str
    available: bool = False                     # Req 7.3
    amount: Optional[float] = None
    currency: str = "INR"
    citation: Optional[EvidenceCitation] = None # Req 7.2
    note: str = ""


class BidDocument(BaseModel):
    """A source PDF belonging to a bid."""
    filename: str
    sub_documents: list[SubDocument] = Field(default_factory=list)


class Bid(BaseModel):
    bid_id: str
    bidder_name: str = ""
    documents: list[BidDocument] = Field(default_factory=list)
    evaluable: bool = True                      # Req 1.4


class BidEvaluation(BaseModel):
    """All per-bid results the ranker consumes."""
    bid: Bid
    completeness: CompletenessResult
    coverage: list[CoverageFinding] = Field(default_factory=list)
    capacity: CapacityResult
    price: BidPrice
    weighted_score: float = 0.0                 # for the Evaluation Matrix


class ShortlistEntry(BaseModel):
    bid_id: str
    bidder_name: str = ""
    rank: Optional[int] = None                  # None if unranked-on-price (Req 8.6)
    eligible: bool = False                      # Req 8.1
    price: Optional[float] = None
    weighted_score: float = 0.0
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)       # Req 8.4
    blocking_reasons: list[str] = Field(default_factory=list)  # Req 8.5


class Shortlist(BaseModel):
    entries: list[ShortlistEntry] = Field(default_factory=list)
    best_match_bid_id: Optional[str] = None     # Req 8.3; None if none eligible (8.5)
    none_eligible: bool = False


class OfficerOverride(BaseModel):
    target: str                                 # "coverage" | "completeness" | "capacity"
    bid_id: str
    item_key: str = ""
    new_value: str
    justification: str                          # required (Req 9.3)
    timestamp: str


class FinalSelection(BaseModel):
    bid_id: str
    justification: str = ""
    timestamp: str


class AuditRecord(BaseModel):
    """Persisted, timestamped record of a run. (Req 10.1-10.4)"""
    run_id: str
    created_at: str
    tender_reference_no: str = ""
    evaluations: list[BidEvaluation] = Field(default_factory=list)
    shortlist: Shortlist = Field(default_factory=Shortlist)
    overrides: list[OfficerOverride] = Field(default_factory=list)
    final_selection: Optional[FinalSelection] = None


class EvaluationRun(BaseModel):
    """Live in-memory run; serialized into an AuditRecord on persist."""
    run_id: str
    created_at: str
    tender: TenderBrief
    required_types: list[RequiredDocumentType] = Field(default_factory=list)
    requirement_items: list[RequirementItem] = Field(default_factory=list)
    bids: list[Bid] = Field(default_factory=list)
    evaluations: list[BidEvaluation] = Field(default_factory=list)
    shortlist: Shortlist = Field(default_factory=Shortlist)
    overrides: list[OfficerOverride] = Field(default_factory=list)
    final_selection: Optional[FinalSelection] = None


class BidIntakeResult(BaseModel):
    """Result of safely extracting one bid's archives and discovering PDFs.

    Produced by ``intake.extract_bid``. Multiple archives are treated as one
    bid (Req 1.2); PDFs are discovered by content location in the extracted
    tree, never by folder/filename meaning (Req 1.3); ``evaluable`` is False
    when no readable PDF was found (Req 1.4).
    """
    bid_id: str
    bid_dir: str                               # extracted bid directory (as str)
    pdf_paths: list[str] = Field(default_factory=list)  # discovered PDF file paths
    evaluable: bool = True                     # Req 1.4
    archive_count: int = 0                     # number of archives extracted (Req 1.2)
