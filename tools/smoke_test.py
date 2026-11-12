"""Smoke test: architect proposal, grounded drafting, and PDF/BOQ consistency."""
from tender_app.models import TenderBrief
from tender_app.generator.boq_generator import generate_boq
from tender_app.generator.pdf_generator import generate_pdf
from tender_app import chat, llm

brief = TenderBrief(
    tender_inviting_authority="Principal, ACGCET, Karaikudi",
    name_of_work="Cloud Based Hostel Management Software",
    tender_reference_no="ACGCET-4903-B1-2026",
    emd_amount="Rs. 16,000/-",
    estimated_value="Rs. 2,50,000",
    contract_period="1 year, extendable up to 4 years",
    submission_due_datetime="20.08.2026 03:00 PM",
    scope_notes="A cloud-hosted hostel management application for about 500 students "
                "at our engineering college, with online fee payment and admin reports.",
    technical_inputs="We already know we want Ubuntu servers.",
)

print("0) Gemini reachable...")
print("   ->", llm.generate("Reply with exactly: PONG")[:20])

print("1) Propose architecture...")
brief = chat.propose_architecture(brief)
print(f"   -> {len(brief.architecture)} components")
for a in brief.architecture:
    print(f"      - {a.category}: {a.description} [{a.quantity} {a.units}] ({a.source})")

print("2) Draft scope + terms...")
brief = chat.draft_sections(brief)
print("   scope words:", len(brief.scope_of_work.split()))

print("3) Consistency check: PDF tech items == BOQ items...")
boq = brief.boq_items()
assert len(boq) == len(brief.architecture), "BOQ/architecture count mismatch!"
for a, b in zip(brief.architecture, boq):
    assert f"{a.category}: {a.description}" == b.item_description, "Description mismatch!"
    assert a.quantity == b.quantity and a.units == b.units, "Qty/units mismatch!"
print(f"   -> OK: {len(boq)} BOQ lines match {len(brief.architecture)} architecture items")

print("4) Generate files...")
print("   BOQ ->", generate_boq(brief, "boq.xlsx"))
print("   PDF ->", generate_pdf(brief, "tender.pdf"))
print("\nALL CHECKS PASSED")
