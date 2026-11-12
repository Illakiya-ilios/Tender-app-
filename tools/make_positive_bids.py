"""Generate two complete, positive sample bids for the evaluation demo.

Each bid is a .zip of text-based PDFs (no OCR needed) containing one clearly
titled document per required document type plus a filled price schedule. Both
bids are fully compliant; they differ only in price so the best-match ranker
picks the cheaper one.

Output:
  sample_bids/positive_bid_A.zip   (higher price)
  sample_bids/positive_bid_B.zip   (lower price  -> expected best match)

Run:  set PYTHONPATH=.  &&  .venv\\Scripts\\python.exe tools\\make_positive_bids.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from fpdf import FPDF

OUT_DIR = Path("sample_bids")
OUT_DIR.mkdir(exist_ok=True)


def _pdf(title: str, body_lines: list[str]) -> bytes:
    """Render a simple one-page text PDF and return its bytes."""
    pdf = FPDF()
    pdf.set_margins(left=15, top=15, right=15)
    pdf.add_page()
    w = pdf.epw  # effective page width (page minus left/right margins)
    pdf.set_font("Helvetica", "B", 15)
    pdf.multi_cell(w, 9, title)
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    for line in body_lines:
        pdf.multi_cell(w, 7, line)
    out = pdf.output()           # fpdf2 returns a bytearray
    return bytes(out)


def build_documents(company: str, cin: str, gstin: str, pan: str,
                    turnover: str, total_price: str) -> dict[str, bytes]:
    """Build the full set of required-document PDFs for one bidder.

    Keys are the output filenames; each document is written so its content
    clearly identifies its required-document type for the classifier.
    """
    hdr = [f"Bidder: {company}", f"CIN: {cin}", ""]

    docs: dict[str, bytes] = {}

    docs["01_Certificate_of_Incorporation.pdf"] = _pdf(
        "Certificate of Incorporation",
        hdr + [
            "Ministry of Corporate Affairs - Certificate of Incorporation.",
            f"This is to certify that {company} is incorporated under the",
            "Companies Act, 2013 as a private limited company.",
            f"Corporate Identity Number (CIN): {cin}.",
            "Date of Incorporation: 12 March 2020.",
        ],
    )

    docs["02_MOA_AOA.pdf"] = _pdf(
        "Memorandum and Articles of Association",
        hdr + [
            "Memorandum of Association (MOA) and Articles of Association (AOA)",
            f"of {company}.",
            "The main object of the company is to provide cloud computing,",
            "managed services and IT infrastructure services.",
        ],
    )

    docs["03_GST_Certificate.pdf"] = _pdf(
        "GST Registration Certificate",
        hdr + [
            "Goods and Services Tax (GST) Registration Certificate.",
            f"GSTIN: {gstin}.",
            f"Legal Name of Business: {company}.",
            "Type of Registration: Regular. Status: Active.",
        ],
    )

    docs["04_PAN_Card.pdf"] = _pdf(
        "Permanent Account Number (PAN) Card",
        hdr + [
            "Income Tax Department - PAN Card.",
            f"Permanent Account Number (PAN): {pan}.",
            f"Name: {company}.",
        ],
    )

    docs["05_MeitY_Empanelment.pdf"] = _pdf(
        "MeitY Empanelment Certificate",
        hdr + [
            "Ministry of Electronics and Information Technology (MeitY).",
            "This certifies that the Cloud Service Provider is empanelled with",
            "MeitY for providing cloud services under the GI Cloud (MeghRaj)",
            "initiative. Empanelment valid through 2027.",
        ],
    )

    docs["06_CSP_Authorization.pdf"] = _pdf(
        "CSP Authorization Certificate",
        hdr + [
            "Authorization Certificate issued by a MeitY-empanelled Cloud",
            f"Service Provider (CSP) authorizing {company} as its managed",
            "services partner (MSP).",
            "",
            "PARTNER TENURE: The CSP certifies that the bidder has been its",
            "authorized partner continuously since 01 April 2019 - a period of",
            "more than five (5) years as on the date of publishing of this",
            "tender. This clearly exceeds the minimum requirement that the bidder",
            "shall have been a partner of the CSP for at least one (1) year as on",
            "the date of publishing of the tender.",
            "",
            "Work orders dated 2019, 2021, 2022 and 2023 are enclosed as proof of",
            "continuous engagement as an authorized partner.",
        ],
    )

    docs["07_CA_Turnover_Certificate.pdf"] = _pdf(
        "Chartered Accountant Turnover Certificate",
        hdr + [
            "Statutory Auditor / Chartered Accountant Turnover Certificate.",
            f"We certify the annual turnover of {company} from cloud / data",
            "centre business for the last five financial years as follows:",
            "FY 2020-21: Rs. 11.20 Crore",
            "FY 2021-22: Rs. 13.80 Crore",
            "FY 2022-23: Rs. 16.50 Crore",
            "FY 2023-24: Rs. 19.10 Crore",
            "FY 2024-25: Rs. 22.40 Crore",
            f"Average annual turnover exceeds the required Rs. 10 Crore. "
            f"({turnover})",
        ],
    )

    docs["08_ISO_9001.pdf"] = _pdf(
        "ISO 9001:2015 Certificate",
        hdr + [
            "ISO 9001:2015 Quality Management System Certificate.",
            f"Certifies that {company} operates a quality management system",
            "compliant with ISO 9001:2015. Valid on the date of bid submission.",
        ],
    )

    docs["09_ISO_20000.pdf"] = _pdf(
        "ISO 20000-1:2018 Certificate",
        hdr + [
            "ISO/IEC 20000-1:2018 Service Management System Certificate.",
            f"Certifies that {company} operates an IT service management system",
            "compliant with ISO 20000-1:2018. Valid on the date of submission.",
        ],
    )

    docs["09b_ISO_27001_Security.pdf"] = _pdf(
        "ISO/IEC 27001:2022 Information Security Certificate",
        hdr + [
            "ISO/IEC 27001:2022 Information Security Management System (ISMS)",
            "Certificate.",
            f"Certifies that {company} operates an information security",
            "management system compliant with ISO/IEC 27001:2022. This is the",
            "bidder's security certification, valid on the date of bid submission.",
        ],
    )

    docs["10_Chennai_Office.pdf"] = _pdf(
        "Declaration of Office in Chennai",
        hdr + [
            f"{company} hereby declares that it has a full-fledged operational",
            "office in Chennai, Tamil Nadu, located at 100 Anna Salai, Chennai.",
            "A copy of the lease rental deed is enclosed as proof.",
        ],
    )

    docs["10b_Work_Orders_Past_Performance.pdf"] = _pdf(
        "Work Orders and Past Performance",
        hdr + [
            f"{company} past performance and delivered projects:",
            "1. State Data Centre cloud migration (2022) - Rs. 6.2 Crore -",
            "   completed successfully, client satisfaction certificate enclosed.",
            "2. Government department managed cloud & security services (2023) -",
            "   Rs. 8.5 Crore - ongoing, delivered on schedule.",
            "3. Disaster recovery and backup implementation (2024) - Rs. 4.1",
            "   Crore - completed.",
            "The bidder has over 5 years of relevant experience delivering",
            "comparable cloud, data centre and managed services projects.",
            "Corresponding work orders and completion certificates are enclosed.",
        ],
    )

    docs["11_Website_Proof.pdf"] = _pdf(
        "Bidder Website Proof",
        hdr + [
            f"{company} maintains its own corporate website.",
            f"Website URL: https://www.{company.lower().replace(' ', '')}.com",
            "A printout of the website home page is enclosed.",
        ],
    )

    docs["12_Price_Schedule_BOQ.pdf"] = _pdf(
        "Price Schedule - Bill of Quantities (BOQ)",
        hdr + [
            "Financial Bid - Price Schedule (Bill of Quantities).",
            "Item 1: Cloud compute (VMs), annual - Qty 50 - INR 2,00,00,000",
            "Item 2: Managed storage & backup, annual - Qty 1 - INR 1,00,00,000",
            "Item 3: Security, monitoring & support - Qty 1 - INR 50,00,000",
            "-------------------------------------------------------------",
            f"GRAND TOTAL (all inclusive): INR {total_price}",
        ],
    )

    return docs


def write_zip(name: str, docs: dict[str, bytes]) -> Path:
    path = OUT_DIR / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, data in docs.items():
            zf.writestr(fname, data)
    return path


def main() -> None:
    # Bidder A - fully compliant, higher price.
    a = build_documents(
        company="Alpha Cloud Services Pvt Ltd",
        cin="U72900TN2020PTC100001",
        gstin="33AAACA0001A1Z5",
        pan="AAACA0001A",
        turnover="average well above Rs. 10 Crore",
        total_price="3,50,00,000",      # 3.5 Crore
    )
    pa = write_zip("positive_bid_A.zip", a)

    # Bidder B - fully compliant, LOWER price -> expected best match.
    b = build_documents(
        company="Beta Cloud Solutions Pvt Ltd",
        cin="U72900TN2019PTC200002",
        gstin="33AAACB0002B1Z4",
        pan="AAACB0002B",
        turnover="average well above Rs. 10 Crore",
        total_price="2,90,00,000",      # 2.9 Crore (cheaper)
    )
    pb = write_zip("positive_bid_B.zip", b)

    print(f"created {pa}  ({pa.stat().st_size/1024:.0f} KB, {len(a)} docs)")
    print(f"created {pb}  ({pb.stat().st_size/1024:.0f} KB, {len(b)} docs)")
    print("Bidder A total: INR 3,50,00,000")
    print("Bidder B total: INR 2,90,00,000  <- expected best match (cheaper)")


if __name__ == "__main__":
    main()
