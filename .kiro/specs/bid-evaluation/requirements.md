# Requirements Document

## Introduction

This feature adds **Stage 3: Evaluation and Best-Match Recommendation** to the existing AI-Powered Tender Document Builder (Python + FastAPI + Google Gemini). Stages 1 and 2 (agentic requirement collection and tender/BOQ generation from a single approved architecture) are complete. Stage 3 begins once a tender has been issued and bidders submit external bids in response.

Stage 3 evaluates the external bids received from bidders against the requirements the tender specified, then recommends the best match. It performs three capabilities end to end:

1. **Document completeness check** — verify every required document is present, readable, and valid in each bid; hold back incomplete bids from scoring.
2. **Requirement coverage check** — verify each bid covers the eligibility, technical, qualification, and capability requirements the tender specified, with cited evidence.
3. **Best-match selection** — among complete and compliant bids, recommend the cheapest bid that meets all requirements and demonstrates the organizational capacity to complete the project, as a ranked shortlist that the officer reviews, overrides, and finalizes.

Real external bids are messy. Observed characteristics from sample submissions that these requirements account for:

- Bids arrive as zip archives of many PDFs with inconsistent folder conventions (one grouped by document type, another by bid part), so classification cannot rely on folder names or filenames and must be content/semantic based.
- The same evidence appears under different filenames across bids, so matching a document to a required-document type must be semantic.
- Readability is mixed: declarations and CVs usually have an extractable text layer, while official certificates (CA turnover, ISO, Certificate of Incorporation) are scanned images or extract as scrambled glyphs, so OCR is required.
- A single PDF can bundle many sub-documents (for example an 87-page PQ bundle or a 29-page CV bundle), so one file cannot be assumed to equal one document.
- Multi-bidder comparison is in scope even though current sample data contains a single bidder.

Stage 3 follows the same design principles as the existing application: a single source of truth (the issued tender and its `TenderBrief`/architecture), human-in-the-loop approval, grounded and explainable outputs that cite their sources, and a pure-Python / no-native-dependency preference (OCR is performed through the existing Gemini vision model rather than a native OCR binary).

## Glossary

- **Evaluation_System**: The Stage 3 software component that ingests, analyzes, scores, and ranks external bids. The scope of all requirements below.
- **Bid**: A complete submission from one bidder in response to a tender, delivered as one or more zip archives containing PDF documents.
- **Bidder**: An external organization that submits a Bid.
- **Officer**: The authenticated tender official who reviews, overrides, and finalizes the Evaluation_System's recommendation (the human-in-the-loop).
- **Source_Tender**: The issued tender that bidders are responding to, represented by its `TenderBrief`, approved `architecture` list, and the fixed Bidder Eligibility Criteria. This is the single source of truth for what was required.
- **Required_Document_Type**: A category of document the Source_Tender requires as proof (for example "CA Turnover Certificate", "ISO 9001:2015 Certificate", "Certificate of Incorporation"), derived from `eligibility.py` (the fixed 7 criteria and their documentary proofs) and the tender's required-documents list.
- **Requirement_Item**: A single discrete requirement the Source_Tender specified that a Bid must satisfy, in one of four classes: eligibility, technical, qualification, or capability.
- **Document_Classifier**: The Evaluation_System sub-component that assigns each extracted sub-document to a Required_Document_Type using document content (semantic), not filenames or folder names.
- **Text_Extractor**: The Evaluation_System sub-component that extracts a text layer from a PDF using the existing `pdfplumber` dependency.
- **OCR_Extractor**: The Evaluation_System sub-component that extracts text from scanned or non-extractable PDF pages using a Gemini vision call.
- **Sub_Document**: A logically distinct document contained within a PDF file; a single PDF file may contain multiple Sub_Documents.
- **Coverage_Status**: The evaluation outcome of a Requirement_Item against a Bid, one of "Satisfied", "Partly Satisfied", or "Not Satisfied".
- **Evidence_Citation**: A reference to the location supporting a Coverage_Status, consisting of a source filename and a page number within that file.
- **Capacity**: A Bidder's demonstrated organizational capability to complete the project, assessed from turnover, prior experience, delivered projects, and certifications.
- **Shortlist**: The ranked list of complete and compliant Bids produced by the Evaluation_System for Officer review.
- **Audit_Record**: A persisted, timestamped record of an evaluation run capturing inputs, Evaluation_System outputs, Officer overrides, and the final selection.

## Requirements

### Requirement 1: Bid Intake and Extraction

**User Story:** As an Officer, I want to upload the external bids received from bidders as zip archives, so that the Evaluation_System can read every document regardless of how the bidder organized the archive.

#### Acceptance Criteria

1. WHEN an Officer uploads one or more zip archives for a Bid, THE Evaluation_System SHALL extract all contained PDF files and associate them with that Bid.
2. WHERE a Bid is supplied as multiple zip archives, THE Evaluation_System SHALL treat all archives as belonging to the same Bid.
3. THE Evaluation_System SHALL derive the document organization from document content and SHALL NOT rely on folder names or file names to determine a document's purpose.
4. IF an uploaded archive contains no readable PDF files, THEN THE Evaluation_System SHALL report that the Bid contains no evaluable documents and SHALL exclude the Bid from scoring.
5. WHEN an Officer uploads Bids, THE Evaluation_System SHALL accept Bids from two or more distinct Bidders within a single evaluation run.
6. WHILE extracting archives, THE Evaluation_System SHALL confine all extracted files to a dedicated directory for the evaluation run and SHALL reject archive entries whose resolved path falls outside that directory.

### Requirement 2: Text and OCR Extraction

**User Story:** As an Officer, I want the Evaluation_System to read both digital and scanned documents, so that official certificates that are scanned images are not missed during evaluation.

#### Acceptance Criteria

1. WHEN a PDF page contains an extractable text layer, THE Text_Extractor SHALL extract the text using the `pdfplumber` dependency.
2. IF a PDF page yields no extractable text or yields text that is not valid readable content, THEN THE OCR_Extractor SHALL extract the page text using a Gemini vision call.
3. THE Evaluation_System SHALL extract document text using only Python packages and the Gemini API, without requiring a native operating-system OCR binary.
4. WHEN text extraction for a document completes, THE Evaluation_System SHALL record, per document, whether the text came from the Text_Extractor, the OCR_Extractor, or both.
5. IF a document cannot be read by either the Text_Extractor or the OCR_Extractor, THEN THE Evaluation_System SHALL mark that document as unreadable and record the source filename.

### Requirement 3: Sub-Document Separation and Semantic Classification

**User Story:** As an Officer, I want the Evaluation_System to identify each distinct document inside bundled PDFs and match it to the document type the tender required, so that evidence is found even when one PDF contains many documents under unrelated filenames.

#### Acceptance Criteria

1. WHERE a single PDF file contains multiple Sub_Documents, THE Evaluation_System SHALL segment the file into its constituent Sub_Documents.
2. THE Document_Classifier SHALL assign each Sub_Document to a Required_Document_Type using the Sub_Document content.
3. THE Evaluation_System SHALL derive the set of Required_Document_Types from the fixed Bidder Eligibility Criteria in `eligibility.py` and the Source_Tender required-documents list.
4. WHEN the Document_Classifier assigns a Sub_Document to a Required_Document_Type, THE Evaluation_System SHALL record the source filename and the page range of the Sub_Document within that file.
5. IF a Sub_Document matches no Required_Document_Type, THEN THE Evaluation_System SHALL label the Sub_Document as "Unclassified" and retain the Sub_Document for Officer review.
6. WHEN two or more Sub_Documents across a Bid are classified as the same Required_Document_Type, THE Evaluation_System SHALL associate all of the matching Sub_Documents with that Required_Document_Type.

### Requirement 4: Document Completeness Check

**User Story:** As an Officer, I want each Bid checked for every required document being present, readable, and valid, so that incomplete bids are held back before any scoring occurs.

#### Acceptance Criteria

1. WHEN a Bid has been classified, THE Evaluation_System SHALL determine, for each Required_Document_Type, whether at least one present and readable Sub_Document of that type exists in the Bid.
2. IF a Required_Document_Type has no present and readable Sub_Document in a Bid, THEN THE Evaluation_System SHALL flag that Required_Document_Type as missing for that Bid.
3. IF a Required_Document_Type is satisfied only by an unreadable document in a Bid, THEN THE Evaluation_System SHALL flag that Required_Document_Type as present-but-unreadable for that Bid.
4. IF a Bid has one or more Required_Document_Types flagged as missing or present-but-unreadable, THEN THE Evaluation_System SHALL mark the Bid as incomplete and SHALL exclude the Bid from requirement coverage scoring and best-match selection.
5. WHEN a Bid has every Required_Document_Type present and readable, THE Evaluation_System SHALL mark the Bid as complete and eligible to proceed to requirement coverage scoring.
6. WHEN the Evaluation_System marks a Bid as incomplete, THE Evaluation_System SHALL report each missing or unreadable Required_Document_Type together with the Bidder identity.

### Requirement 5: Requirement Coverage Check

**User Story:** As an Officer, I want each complete Bid assessed against every requirement the tender specified, with cited evidence, so that I can trust and verify which requirements each bidder meets.

#### Acceptance Criteria

1. THE Evaluation_System SHALL derive the set of Requirement_Items from the Source_Tender, covering eligibility requirements from `eligibility.py`, and technical, qualification, and capability requirements from the approved `architecture` and `TenderBrief`.
2. WHEN a Bid is marked complete, THE Evaluation_System SHALL assign each Requirement_Item a Coverage_Status of "Satisfied", "Partly Satisfied", or "Not Satisfied" for that Bid.
3. WHEN the Evaluation_System assigns a Coverage_Status of "Satisfied" or "Partly Satisfied", THE Evaluation_System SHALL attach at least one Evidence_Citation consisting of a source filename and a page number.
4. IF the Evaluation_System assigns a Coverage_Status of "Not Satisfied" to a Requirement_Item, THEN THE Evaluation_System SHALL record the reason the Requirement_Item was not met.
5. THE Evaluation_System SHALL produce a per-Bid coverage summary listing every Requirement_Item with its Coverage_Status and associated Evidence_Citations.

### Requirement 6: Capacity Assessment

**User Story:** As an Officer, I want each compliant Bidder's capacity to complete the project assessed from their financial and experience evidence, so that I do not recommend a bidder that cannot deliver.

#### Acceptance Criteria

1. WHEN a Bid is marked complete, THE Evaluation_System SHALL assess the Bidder's Capacity from turnover, prior experience, delivered projects, and certifications evidenced in the Bid.
2. WHEN assessing turnover against the Source_Tender turnover criterion, THE Evaluation_System SHALL use the CA/Statutory Auditor turnover certificate as the evidence source and SHALL attach an Evidence_Citation.
3. WHEN the Evaluation_System determines a Bidder meets the Capacity requirements, THE Evaluation_System SHALL mark the Bidder as capacity-qualified.
4. IF a Bidder does not meet one or more Capacity requirements, THEN THE Evaluation_System SHALL mark the Bidder as not capacity-qualified and SHALL record each unmet Capacity requirement with its reason.

### Requirement 7: Bid Pricing Extraction

**User Story:** As an Officer, I want each Bid's quoted price extracted and tied to its source, so that price comparison across bidders is accurate and verifiable.

#### Acceptance Criteria

1. WHEN a Bid is marked complete, THE Evaluation_System SHALL extract the Bid's total quoted price from the Bid's price schedule.
2. WHEN the Evaluation_System extracts a Bid price, THE Evaluation_System SHALL attach an Evidence_Citation consisting of the source filename and page number.
3. IF a complete Bid contains no extractable price, THEN THE Evaluation_System SHALL mark the Bid price as unavailable and SHALL record that the Bid cannot be ranked on price until the Officer supplies the price.

### Requirement 8: Best-Match Selection and Ranked Shortlist

**User Story:** As an Officer, I want a ranked shortlist recommending the cheapest fully compliant and capable bid, with reasons, so that I can make a defensible final selection quickly.

#### Acceptance Criteria

1. THE Evaluation_System SHALL consider for best-match selection only Bids that are marked complete, have every Requirement_Item with a Coverage_Status of "Satisfied", and are marked capacity-qualified.
2. WHEN two or more Bids are eligible for best-match selection, THE Evaluation_System SHALL rank the eligible Bids by extracted Bid price in ascending order.
3. THE Evaluation_System SHALL recommend the eligible Bid with the lowest extracted price as the best match.
4. WHEN the Evaluation_System produces the Shortlist, THE Evaluation_System SHALL record, for each ranked Bid, the reasons supporting its rank including price, coverage result, and Capacity result.
5. IF no Bid is eligible for best-match selection, THEN THE Evaluation_System SHALL report that no Bid meets all requirements and SHALL list, per Bid, the blocking reasons.
6. WHERE one or more eligible Bids have an unavailable price, THE Evaluation_System SHALL list those Bids in the Shortlist as unranked-on-price pending Officer input.

### Requirement 9: Officer Review, Override, and Final Selection

**User Story:** As an Officer, I want to review the recommendation, override the Evaluation_System's findings, and record the final selection, so that a human remains accountable for the award decision.

#### Acceptance Criteria

1. WHEN the Evaluation_System produces a Shortlist, THE Evaluation_System SHALL present the recommendation and supporting findings to the Officer for review before any selection is final.
2. THE Evaluation_System SHALL allow the Officer to override a Coverage_Status, a completeness flag, or a Capacity determination for any Bid.
3. WHEN the Officer overrides a finding, THE Evaluation_System SHALL require the Officer to record a justification for the override.
4. WHEN the Officer confirms a final selection, THE Evaluation_System SHALL record the selected Bidder as the final selection for the Source_Tender.
5. THE Evaluation_System SHALL NOT mark any Bid as the final selection until the Officer confirms the selection.

### Requirement 10: Audit Record and Explainability

**User Story:** As an Officer, I want every evaluation run and decision recorded with its evidence and any overrides, so that the award can be audited and defended later.

#### Acceptance Criteria

1. WHEN an evaluation run completes, THE Evaluation_System SHALL persist an Audit_Record containing the evaluated Bids, each Bid's completeness result, coverage summary, Capacity result, extracted price, and the produced Shortlist.
2. WHEN the Officer records an override or a final selection, THE Evaluation_System SHALL append the override or selection, its justification, and a timestamp to the Audit_Record.
3. THE Evaluation_System SHALL include in the Audit_Record the Evidence_Citations supporting each Coverage_Status and each extracted price.
4. WHEN an Officer requests the Audit_Record for a completed evaluation run, THE Evaluation_System SHALL provide the full Audit_Record for that run.
