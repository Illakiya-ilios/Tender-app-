"""Fixed Bidder Eligibility Criteria, taken verbatim from the ELCOT tender
(E-ANGADI-ST-SDC-2026-0034, Section V.2). Included in every generated tender.
"""

ELIGIBILITY_INTRO = (
    "The Bidder shall have the following eligibility for participating in the "
    "Tender. The Bidder shall enclose documentary evidence for fulfilling the "
    "eligibility in the Technical Bid. If a bidder fails to enclose the "
    "documentary proof for eligibility, their bid shall be summarily rejected."
)

# Each row: (criterion, documentary proof to be submitted)
ELIGIBILITY_ROWS = [
    (
        "The bidder should be either:\n"
        "I. A company registered under the Indian Companies Act, 2013 or under the "
        "previous Companies Act, 1956; OR\n"
        "II. A partnership firm registered under the Limited Liability Partnerships "
        "(LLP) Act, 2008; OR\n"
        "III. A partnership firm registered under the Indian Partnership Act, 1932.\n"
        "IV. If the bidding entity is a wholly owned subsidiary of the parent "
        "company, the parent company's qualifications pertaining to cloud business "
        "will be considered.\n"
        "V. Government institutions under MeitY will be permitted.",
        "1. Certificate of Incorporation / Certificate of Registration\n"
        "2. Memorandum and Articles of Association / Partnership deed\n"
        "3. GST Certificate\n"
        "4. Copy of PAN card",
    ),
    (
        "The bidder shall be a CSP or MSP (authorized partner of CSP). In either "
        "case, the CSP shall be empaneled with MeitY for providing cloud services.",
        "a) MeitY empanelment certificate issued in the name of CSP.\n"
        "b) Authorization certificate issued in the name of MSP/bidder by CSP.",
    ),
    (
        "If the bidder is an authorized partner of a CSP empaneled with MeitY, then "
        "the bidder should have been a partner to the CSP for at least 1 year as on "
        "the date of publishing of this tender.",
        "Authorization certificate from a MeitY empaneled CSP authorizing the bidder "
        "and mentioning years of engagement. Proof of work orders is preferred.",
    ),
    (
        "If the bidder is an authorized partner of a CSP empaneled with MeitY, then "
        "the bidder should have a minimum average annual turnover of at least "
        "Rs. 10 Crore in any two of the last five financial years (2020-21, "
        "2021-22, 2022-23, 2023-24 & 2024-25) from DC or Cloud business. If the "
        "bidder is a MeitY empaneled CSP / Government institution under MeitY, then "
        "this turnover criterion shall not apply.",
        "A certificate from the Statutory Auditor / Chartered Accountant clearly "
        "specifying the turnover during the last five financial years "
        "(2020-21, 2021-22, 2022-23, 2023-24 & 2024-25).",
    ),
    (
        "In case the bidder is an authorized partner of a CSP, then the bidder shall "
        "have ISO 9001:2015 and ISO 20000-1:2018 certification.",
        "Self-certified copy of certification which is valid on the date of bid "
        "submission.",
    ),
    (
        "The bidder shall have a full-fledged operational office in Chennai, or "
        "should provide an undertaking that a full-fledged full-time office will be "
        "set up in Chennai within 30 days of empanelment.",
        "Proof of availability of office in Chennai or declaration.",
    ),
    (
        "The bidder shall have their own website.",
        "The URL of the website and a copy of the home page printout of the bidder "
        "shall be submitted.",
    ),
]

ELIGIBILITY_NOTES = [
    "In case of an Authorised Signatory submitting bid documents, a Power of "
    "Attorney (PoA) shall be issued to the Authorized Signatory of the Bidder to "
    "sign and submit the bid and execute the Contract Agreement on behalf of the "
    "Bidder firm, to be issued by the Board of Directors / the Managing Director "
    "of the Company.",
    "The Bidder must not be under a declaration of ineligibility for corrupt, "
    "fraudulent or any other unethical business practices and shall not be debarred "
    "or blacklisted by any State / Central Government / Public Sector Undertaking "
    "for any reason in the last 3 years from the date of the response to this Tender.",
    "The Bidder shall comply with the GFR with respect to procurement from a "
    "country which shares a land border with India, as per GFR Rules.",
    "Bidders shall ensure that they have uploaded all the required proof documents "
    "signed with seal without fail. Bids received without the supporting documents "
    "to prove their eligibility are liable for rejection.",
    "The Tender Inviting Authority reserves the right to verify the authenticity "
    "and veracity of any documents submitted for the eligibility criteria.",
]


# ---------------------------------------------------------------------------
# Standard Annexures (bidder submission formats), from the ELCOT tender.
# Printed in every generated tender after the eligibility criteria.
# Each annexure is (title, body). Use "\n" for line breaks; blank line = gap.
# ---------------------------------------------------------------------------

ANNEXURES = [
    (
        "Annexure 1 - Power of Attorney",
        "Power of Attorney (PoA) by the Authorized Signatory of the Bidder "
        "authorizing a staff member to sign and submit the Bid and execute the "
        "Contract (if selected as a successful bidder) on behalf of the Bidder.\n"
        "<To be executed on non-judicial stamp paper of Rupees One Hundred only "
        "(INR 100/-)>\n\n"
        "Know all men by these presents, We ____________________________ (name of "
        "the Bidder and address of their registered office) do hereby constitute, "
        "appoint and authorize Mr./Ms. ____________________________ (name and "
        "residential address of the Power of Attorney holder), who is presently "
        "employed with us and holding the position of ____________________________, "
        "as our Attorney, to do in our name and on our behalf all such acts, deeds "
        "and things necessary in connection with or incidental to our proposal for "
        "the said tender, including signing and submission of the bid, executing the "
        "contract (if selected as a successful bidder) and providing information / "
        "responses to the Tender Inviting Authority / End User, and representing us "
        "in all matters before them in connection with our proposal.\n\n"
        "We hereby agree to ratify all acts, deeds and things lawfully done by our "
        "said Attorney pursuant to this Power of Attorney, and all acts, deeds and "
        "things done by our aforesaid Attorney shall always be deemed to have been "
        "done by us.\n\n"
        "For ____________________________\n"
        "Name:                     Designation:\n"
        "Date:                     Seal:\n"
        "Business Address:\n\n"
        "Accepted,\n"
        "______________ (Signature)\n"
        "(Name, Title and Address of the Attorney)",
    ),
    (
        "Annexure 2 - Restrictions on Public Procurement (Instructions to Bidders)",
        "Bidders are requested to comply with the following instructions without "
        "fail.\n\n"
        "Any bidder from a country which shares a land border with India will be "
        "eligible to bid in this tender only if the bidder is registered with the "
        "Competent Authority. The Competent Authority for the purpose of "
        "registration under this tender shall be:\n"
        "a) The Registration Committee constituted by the Department for Promotion "
        "of Industry and Internal Trade (DPIIT); OR\n"
        "b) The Registration Committee constituted by the Government of Tamil Nadu.\n\n"
        "A 'Bidder from a country which shares a land border with India' means an "
        "entity incorporated, established or registered in such a country; a "
        "subsidiary of such an entity; an entity substantially controlled through "
        "such entities; an entity whose beneficial owner is situated in such a "
        "country; an Indian (or other) agent of such an entity; a natural person who "
        "is a citizen of such a country; or a consortium or joint venture where any "
        "member falls under any of the above.\n\n"
        "The successful bidder shall not be allowed to sub-contract works to any "
        "contractor from a country which shares a land border with India unless such "
        "contractor is registered with the Competent Authority. Each bidder shall "
        "submit the Undertaking as per Annexure 3. Where applicable, the bidder "
        "shall submit the Certificate of Registration from the Competent Authority.",
    ),
    (
        "Annexure 3 - Letter of Undertaking",
        "(To be submitted on the letterhead of the Bidder and signed by the "
        "Authorised Signatory.)\n\n"
        "I/We, ____________________________, having our registered office at "
        "____________________________, hereby declare that we have carefully read, "
        "fully understood and examined the entire Tender Document including the "
        "Notice Inviting Tender (NIT), Instructions to Bidders, Terms and "
        "Conditions, Scope of Work, Technical Specifications, Technical Bid and "
        "Price Bid, and we unconditionally agree to comply with and abide by the "
        "same. I/We further undertake and declare as under:\n\n"
        "A. Compliance with GFR Rule - Countries Sharing a Land Border with India:\n"
        "I/We certify that we are not from any country sharing a land border with "
        "India, or if from such a country, are duly registered with the Competent "
        "Authority as per GFR, 2017, as amended. In the event of being declared a "
        "successful bidder, I/We shall not subcontract to any contractor from such a "
        "country unless duly registered.\n\n"
        "B. Declaration Regarding Blacklisting / Debarment:\n"
        "Neither I/We nor any of our OEMs have been blacklisted, debarred or "
        "declared ineligible for corrupt, fraudulent or unethical practices by any "
        "State / Central Government, Public Sector Undertaking, Statutory Board or "
        "Local Body during the last three (3) years preceding the date of this bid.\n\n"
        "C. Declaration of No Conflict of Interest:\n"
        "I/We declare that there exists no actual, potential or perceived conflict "
        "of interest arising out of any past, present or proposed contracts, "
        "engagements or affiliations with any Department, Agency or Organization of "
        "the State Government, and undertake to disclose any such conflict "
        "immediately.\n\n"
        "D. Local Office:\n"
        "I/We confirm that we have / undertake to establish a functional local "
        "office within thirty (30) calendar days from the date of issue of the "
        "Letter of Award (LoA).\n\n"
        "E. General Compliance:\n"
        "All information, statements and documents furnished by us in this Tender "
        "are true, correct and complete. We fulfil all eligibility criteria and "
        "requirements specified in this Tender. We understand that any false or "
        "misleading declaration shall entitle the Tender Inviting Authority to "
        "reject the bid or terminate the contract and take action under the "
        "applicable Transparency in Tenders Act and Rules.\n\n"
        "Signature of Authorised Signatory: ______________________\n"
        "Name: ______________________   Designation: ______________________\n"
        "Company Name: ______________________\n"
        "Date: ______________________   Place: ______________________",
    ),
    (
        "Annexure 4 - Format for Pre-Bid Queries",
        "(To be sent as an MS Excel sheet through email only, with the email "
        "subject quoting the Tender Reference Number.)\n\n"
        "Name of the Company: ______________________\n"
        "GSTN: ______________________\n"
        "Name and designation of the Authorized Person: ______________________\n"
        "Mobile No.: ______________________   E-mail id: ______________________\n\n"
        "For each query, provide: S.No | Chapter | Page No. | Clause No. | Existing "
        "Clause | Query / Amendment requested | Reason for query / amendment.\n\n"
        "Signature of the Authorized Signatory\n"
        "Name and Designation:         Place:         Date:         Company stamp:",
    ),
]
