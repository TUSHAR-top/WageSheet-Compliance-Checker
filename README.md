# Wagesheet vs. ECR Compliance Verification

Automatically checks, employee by employee, whether the PF and ESIC amounts a vendor claims to have deducted in their monthly wagesheet were actually deposited with the government — and produces a downloadable spreadsheet of the result.

## Table of Contents

1. [The Problem (What & Why)](#the-problem-what--why)
2. [Solution at a Glance](#solution-at-a-glance)
3. [Architecture (How)](#architecture-how)
4. [Tech Stack](#tech-stack)
5. [Getting Started (run locally in under 15 minutes)](#getting-started-run-locally-in-under-15-minutes)
6. [How to Use (for non-technical users)](#how-to-use-for-non-technical-users)
7. [Output Format](#output-format)
8. [Matching Rules & Edge Cases](#matching-rules--edge-cases)
9. [Assumptions & Design Trade-offs](#assumptions--design-trade-offs)
10. [Known Limitations](#known-limitations)
11. [What I'd Improve With More Time](#what-id-improve-with-more-time)
12. [Testing](#testing)
13. [Project Structure](#project-structure)
14. [Demo](#demo)

## The Problem (What & Why)

Every month, vendor agencies that supply contract manpower to Prozo's fulfilment centres submit a wagesheet showing what they deducted from each worker's pay for PF and ESIC — India's retirement and health-insurance schemes. Separately, they're supposed to actually deposit that money with the government and file proof of it: a PF ECR and an ESIC ECR. The compliance team's job is to confirm the two line up — that the amount the vendor says they deducted from an employee is the amount that actually reached the authorities, for that same employee.

Today that check is manual: someone opens the wagesheet and both filing PDFs side by side and cross-references rows by hand, for every employee, every month. For a filing running to hundreds of employees, that's slow, error-prone, and easy to game — a mismatched name or a slightly short deposit is easy to miss when you're scanning hundreds of rows by eye.

This tool automates that cross-check. For every employee in the wagesheet, it independently verifies three things against each ECR: is the right person there (identifier found), is it genuinely the same person (name matches), and did the right amount arrive (amount matches). It turns a manual, hours-long reconciliation into a single verdict per employee per scheme, so the compliance team can spend their time on the handful of rows that actually need a human look, not on the hundreds that don't.

## Solution at a Glance

Three files go in — a wagesheet (Excel) and two ECR filings (PDF) — and a verdict spreadsheet comes out. In between, a matching engine looks up each employee's UAN and IP Number in the two ECRs, compares names with tolerance for spelling/order variation, and compares amounts with a small rounding allowance, arriving at one of four verdicts per scheme: **Matched**, **Name mismatch**, **Amount mismatch**, or **Missing**.

What this covers, mapped to what's required:

- Upload wagesheet + PF ECR + ESIC ECR through a web page, run verification, download results — no manual row-matching.
- Every wagesheet employee gets an independent PF verdict and an independent ESIC verdict (one can be Matched while the other is Missing).
- Every mismatch shows *why*: both values and the difference for amounts, both names and the similarity score for names.
- A downloadable `.xlsx` report with per-employee detail and summary counts for both schemes.
- Large filings (hundreds of pages) process in a background thread; the browser polls for progress and the job survives a page refresh.

## Architecture (How)

<!-- ============================================= -->
<!-- ARCHITECTURE DIAGRAM — paste image below      -->
<!-- Replace the line under this comment with:     -->
<!-- ![Architecture Diagram](docs/images/architecture.png) -->
<!-- ============================================= -->
<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/180f72a3-987e-4e91-bc2c-7ba52fa4329f" />

<img width="1560" height="960" alt="image" src="https://github.com/user-attachments/assets/25c4f8c8-eeab-423b-88c2-d8b5f5fc405f" />


**Pipeline walkthrough:**

1. **Upload & validation** — [app.py](app.py)'s `/api/verify` route checks all three files are present, checks each has the expected extension (`.xlsx`/`.xls` for the wagesheet, `.pdf` for both ECRs), saves them to a per-job folder under `uploads/`, then rejects any that saved as 0 bytes. A background job is queued and a `job_id` returned immediately.
2. **Wagesheet parsing** — [processing/jobs.py](processing/jobs.py) calls [processing/excel_reader.py](processing/excel_reader.py)'s `parse_wagesheet`, which reads the first worksheet, matches header cells to `Name`/`UAN`/`IP Number`/`ESIC amount`/`PF amount` by keyword, and emits one employee record per non-blank row.
3. **PF ECR parsing** — [processing/pf_ecr_parser.py](processing/pf_ecr_parser.py) extracts word positions page-by-page via [processing/pdf_backend.py](processing/pdf_backend.py) (PyMuPDF), locates member rows with the shared row-detection logic in [processing/pdf_rows.py](processing/pdf_rows.py), and builds a dict of PF members keyed by UAN.
4. **ESIC ECR parsing** — [processing/esic_ecr_parser.py](processing/esic_ecr_parser.py) does the same for the ESIC contribution-history PDF, keyed by IP Number.
5. **Identifier indexing** — both parsers return plain Python dicts keyed by identifier, so per-employee lookup in the next step is an O(1) dict lookup regardless of filing size.
6. **Per-employee verification** — [processing/verify.py](processing/verify.py)'s `verify_employees` runs each wagesheet row through `_check_one` twice (once for PF, once for ESIC), in a fixed order: **identifier lookup → name comparison ([processing/name_match.py](processing/name_match.py)) → amount comparison**. The first check that fails decides the verdict; the two schemes are fully independent of each other.
7. **Verdict assembly** — results and running summary counts (per scheme, per verdict) are accumulated into a single structure returned to the job.
8. **Spreadsheet export** — [processing/report.py](processing/report.py) builds a single-sheet `.xlsx` workbook: a summary block followed by the full per-employee detail table, with status colour-coding, autofilter, and frozen header rows.

### Design decisions & why

**PDF parsing: position-based pattern matching, not a table-extraction library or an LLM.** EPFO/ESIC ECR exports are portal-generated PDFs with no real grid lines for a table-detection library to lock onto, and their layout can shift slightly between portal versions. Instead, [pdf_rows.py](processing/pdf_rows.py) exploits one invariant that holds regardless of layout noise: every genuine member row starts with a strictly-increasing serial number followed by a numeric identifier. That's enough to find data rows reliably whether the header repeats on every page or not, without needing the row count or column pixel-positions from the sample file baked in. Two adjacent name columns with no delimiter (the PF ECR's "Name as per ECR" / "Name as per UAN Repository") are split at the widest horizontal gap between words, since a column gutter is reliably wider than the spacing inside one name. An LLM-based row extractor was considered and rejected: it would be slower and non-deterministic on a compliance artifact where a verdict must be reproducible, and — since the brief requires a path with no paid API keys — would need a locally-run model to stay free, which is unnecessary complexity when a structural invariant already solves the problem deterministically. **Every step in this pipeline — parsing, matching, and verdicts — is plain deterministic code; there is no LLM or ML model anywhere in the flow.**

**Name matching: RapidFuzz `token_sort_ratio`, threshold 85, over exact match or phonetic algorithms.** Exact string matching fails on the routine spelling/spacing variance in payroll records (it would flag far too many genuine matches as mismatches). Phonetic algorithms like Soundex are tuned for English phonetics and don't generalise well to transliterated Indian names. `token_sort_ratio` was chosen specifically because it tokenises and sorts words before comparing, so word-order differences ("Kumar Ravi" vs. "Ravi Kumar") score identically to a reordered match — a plain Levenshtein ratio would penalise that. The threshold of 85 was picked empirically (see the calibration cases in [name_match.py](processing/name_match.py) and the [Name-matching tolerance](#name-matching-tolerance) section below) to sit above common abbreviation noise and below same-length different-name confusions. There is currently no middle "needs review" band — it's a hard cutoff — though the similarity score is always retained in the output so a reviewer can judge a close call themselves.

**What was considered and rejected:** embedding/cosine-similarity name matching and an LLM-as-judge for names were both considered and rejected for the same reason as the PDF parser — they trade determinism and a free-to-run path for marginal gains this rule-based approach already covers, on a document where every verdict needs to be explainable and reproducible.

## Tech Stack

| Layer | Technology | Why chosen |
|---|---|---|
| Web framework | Flask 3.1.3 | Minimal, sufficient for a small stateless JSON API plus one HTML page — no need for a heavier framework at this scale. |
| Excel parsing | openpyxl 3.1.5 | Pure-Python `.xlsx` reader/writer, no external binary dependency, used both to read the wagesheet and to write the output report. |
| PDF text extraction | PyMuPDF (`fitz`) 1.28.0 | Compiled (MuPDF) backend rather than a pure-Python one — extracts word positions from a several-hundred-page PDF in well under a second, keeping background jobs fast. |
| Fuzzy name matching | RapidFuzz 3.14.5 | C++-backed Levenshtein-family ratios; `token_sort_ratio` specifically gives word-order-independent comparison at negligible cost per row. |
| Background jobs | `concurrent.futures.ThreadPoolExecutor` (stdlib) | Verification of a large filing can take a few seconds; a simple in-process worker pool is enough to keep the upload request non-blocking without adding infrastructure like Celery/Redis. |
| Frontend | Vanilla HTML/CSS/JS ([static/](static/)) | No build step; served directly by Flask's static file handler. |
| Job state | In-process `dict` + `threading.Lock` ([processing/jobs.py](processing/jobs.py)) | Simple and sufficient for a single-process deployment; traded off against durability (see [Known Limitations](#known-limitations)). |

No paid or external API of any kind is used anywhere in this stack.

## Getting Started (run locally in under 15 minutes)

**Prerequisites:** Python 3.9 or later, and `pip`. No database, no Docker, no external account.

### Windows — one click

Double-click [start_app.bat](start_app.bat). It installs dependencies with `pip install --user` and starts the server, printing the local URL to open.

### Manual — any OS

```bash
git clone <this-repo-url>
cd WageSheet-Compliance-Checker
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in a browser. That's the whole install — expect 1–2 minutes for `pip install` (PyMuPDF is the largest wheel) and a few seconds to start.

### Environment variables

None are required. The only variable the app reads is optional:

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5000` | Port the Flask server listens on. |

There are no API keys, secrets, or `.env` file anywhere in this project — nothing to configure before running.

### Free path

This project has no paid path to begin with: wagesheet parsing, PDF parsing, name matching, and amount matching are all local, deterministic code (openpyxl / PyMuPDF / RapidFuzz). There is no call to any LLM or third-party API at any point, so running it "for free" and running it at all are the same thing.

### Verify it works

This repository does not currently ship a sample wagesheet or sample ECR PDFs (see [Testing](#testing) for why). To do a smoke test:

1. Build or obtain a small wagesheet with columns `Name, UAN, IP Number, Agency, State, ESIC @ 0.75%, PF @ 12%` and a handful of rows.
2. Build or obtain matching PF ECR and ESIC ECR PDF exports covering those same UANs/IP Numbers (see [Assumptions & Design Trade-offs](#assumptions--design-trade-offs) for the exact layout each parser expects).
3. Upload all three on the running app's home page and click **Run verification**.
4. Confirm the progress bar completes, a verdict table appears, and **Download spreadsheet** produces a `.xlsx` matching the schema in [Output Format](#output-format).

## How to Use (for non-technical users)

1. **Upload.** Open the app in a browser. Attach the vendor wagesheet and both ECR PDFs in their three slots and click **Run verification**.

<!-- ============================================= -->
<!-- SCREENSHOT: Upload screen                     -->
<!-- Replace the line below with:                  -->
<!-- ![Upload screen](docs/images/upload-screen.png) -->
<!-- ============================================= -->

<img width="1452" height="760" alt="image" src="https://github.com/user-attachments/assets/0e748751-a5f1-4aa3-be97-b3d0d4ea33ec" />


2. **Wait.** A progress bar shows what stage the check is at (reading the wagesheet, parsing each ECR, matching employees, building the report). For a large filing this can take a little while — you can close the tab and come back; reopening the app resumes watching the same job.

<!-- ============================================= -->
<!-- SCREENSHOT: Processing / progress view        -->
<!-- Replace the line below with:                  -->
<!-- ![Processing view](docs/images/processing-view.png) -->
<!-- ============================================= -->
<img width="1121" height="891" alt="image" src="https://github.com/user-attachments/assets/e0299061-73e4-40e8-be23-43110efd4651" />


3. **If something's wrong with a file**, a clear message explains what and why — no blank page, no crash.

<!-- ============================================= -->
<!-- SCREENSHOT: Error message view                -->
<!-- Replace the line below with:                  -->
<!-- ![Error message view](docs/images/error-view.png) -->
<!-- ============================================= -->

<img width="1171" height="745" alt="image" src="https://github.com/user-attachments/assets/b086466a-bb3c-4105-b68d-1b7ed25248e1" />


4. **Review the verdicts.** Every employee gets a row with a PF status and an ESIC status, each colour-coded (green = Matched, yellow = name issue, orange = amount issue, red = missing). Search by name/UAN/IP Number, or filter to only the rows that need attention.

<!-- ============================================= -->
<!-- SCREENSHOT: Verdict results table             -->
<!-- Replace the line below with:                  -->
<!-- ![Verdict results table](docs/images/results-table.png) -->
<!-- ============================================= -->

<img width="972" height="760" alt="image" src="https://github.com/user-attachments/assets/baf85b67-40f4-4bdb-9aec-c443618170c8" />


5. **Check the summary counts** at the top — how many employees are Matched / Name mismatch / Amount mismatch / Missing, for PF and for ESIC separately, at a glance.

<!-- ============================================= -->
<!-- SCREENSHOT: Summary counts view               -->
<!-- Replace the line below with:                  -->
<!-- ![Summary counts view](docs/images/summary-counts.png) -->
<!-- ============================================= -->

<img width="972" height="325" alt="image" src="https://github.com/user-attachments/assets/fbbe8416-0f9d-453d-83b7-c5bb7b17b233" />


6. **Download the spreadsheet.** One click produces the full `.xlsx` report for record-keeping or sharing with the vendor.

<!-- ============================================= -->
<!-- SCREENSHOT: Spreadsheet download              -->
<!-- Replace the line below with:                  -->
<!-- ![Spreadsheet download](docs/images/spreadsheet-download.png) -->
<!-- ============================================= -->

<img width="1867" height="532" alt="image" src="https://github.com/user-attachments/assets/d56135a5-8623-4d8d-9020-3ac6eb128aa6" />


## Output Format

The downloaded `.xlsx` is a single worksheet ("Verification Report") — deliberately not split across tabs, since some preview panes (Explorer, Outlook) only render the active sheet and would silently hide a second tab. It has two parts, generated by [processing/report.py](processing/report.py):

**Summary block** (top of sheet): total employees in the wagesheet, then a count of `Matched / Name mismatch / Amount mismatch / Missing` for PF and the same four counts for ESIC, plus a list of any PDF rows that could not be parsed (see [Matching Rules & Edge Cases](#matching-rules--edge-cases)).

**Per-employee detail table** (below the summary), one row per wagesheet employee, frozen header and auto-filter enabled:

| Column | Meaning |
|---|---|
| Row | Row number in the original wagesheet |
| Name (Wagesheet) | Employee name as entered by the vendor |
| UAN | PF identifier from the wagesheet |
| IP Number | ESIC identifier from the wagesheet |
| Agency | Vendor agency name |
| State | State the employee is based in |
| PF Status | `Matched` / `Name mismatch` / `Amount mismatch` / `Missing` |
| PF Wagesheet Amt | PF amount claimed in the wagesheet |
| PF ECR Amt | EE contribution found in the PF ECR |
| PF Diff | Wagesheet amount minus ECR amount |
| PF ECR Name | Name found against that UAN in the PF ECR |
| PF Reason | Human-readable explanation of the verdict |
| ESIC Status | `Matched` / `Name mismatch` / `Amount mismatch` / `Missing` |
| ESIC Wagesheet Amt | ESIC amount claimed in the wagesheet |
| ESIC ECR Amt | IP contribution found in the ESIC ECR |
| ESIC Diff | Wagesheet amount minus ECR amount |
| ESIC ECR Name | Name found against that IP Number in the ESIC ECR |
| ESIC Reason | Human-readable explanation of the verdict |

**Sample rows** (from an actual run, identifiers masked):

| Name | UAN | IP Number | PF Status | PF Reason | ESIC Status | ESIC Reason |
|---|---|---|---|---|---|---|
| ANIL KUMAR | 9999XXXX0001 | 99XXXX0001 | Matched | Matched | Matched | Matched |
| DINESH PRASAD | 9999XXXX0007 | 99XXXX0007 | Name mismatch | Wagesheet name 'DINESH PRASAD' vs ECR name 'DEVENDRA PRASAD' (similarity 64.3) | Matched | Matched |
| REKHA SHARMA | 9999XXXX0008 | 99XXXX0008 | Matched | Matched | Name mismatch | Wagesheet name 'REKHA SHARMA' vs ECR name 'RENU SHARMA' (similarity 78.3) |
| SANJAY PASWAN | 9999XXXX0009 | 99XXXX0009 | Missing | UAN 9999XXXX0009 not found in ECR | Missing | IP Number 99XXXX0009 not found in ECR |
| VIKRAM THAKUR | 9999XXXX0011 | 99XXXX0011 | Amount mismatch | Wagesheet PF 1654.0 vs ECR 1354.0 (diff 300.0) | Matched | Matched |

The report lands in the job's temporary folder on the server and is served for download via `GET /api/download/<job_id>` — the "Download spreadsheet" button in the UI simply follows that link.

## Matching Rules & Edge Cases

### Verdict logic

Each wagesheet employee is checked against the PF ECR and the ESIC ECR **independently** — one employee can be `Matched` on PF and `Missing` on ESIC in the same row. For each scheme, the checks run in this fixed order, and the first one that fails decides the verdict:

**Table A — Verdicts**

| Verdict | Condition | Example |
|---|---|---|
| Missing | Wagesheet identifier (UAN/IP Number) is blank | Wagesheet row has no IP Number → ESIC: Missing |
| Missing | Identifier is present but not found as a key in the parsed ECR | UAN `9999XXXX0009` not found in PF ECR → PF: Missing |
| Name mismatch | Identifier found, but similarity score of wagesheet name vs. ECR name is below 85 | "DINESH PRASAD" vs. "DEVENDRA PRASAD" scores 64.3 → Name mismatch |
| Amount mismatch | Identifier and name both match, but `|wagesheet amount − ECR amount|` exceeds ₹1 | Wagesheet PF ₹1654 vs. ECR EE share ₹1354 (diff ₹300) → Amount mismatch |
| Matched | Identifier found, name similarity ≥ 85, amount difference ≤ ₹1 | Wagesheet PF ₹1622 vs. ECR EE share ₹1622 → Matched |

### Name-matching tolerance

This is the centrepiece of the matching engine, implemented in [processing/name_match.py](processing/name_match.py).

**Normalisation**, applied to both the wagesheet name and the ECR name before comparison:
1. Uppercase the string.
2. Strip punctuation (`.`, `,`, `'`, `-`, `/`), replacing with a space.
3. Collapse repeated whitespace.
4. Drop a fixed set of honorifics if present as standalone words: `MR, MRS, MS, SHRI, SMT, DR, KUM`.

**Comparison algorithm:** RapidFuzz's `token_sort_ratio` — it splits both normalised names into words, sorts each set alphabetically, and computes a Levenshtein-based similarity ratio (0–100) between the sorted, rejoined strings. Sorting tokens before comparing is what makes it word-order-independent.

**Threshold:** a name similarity score of **85 or above** is treated as a match.

**Where 85 comes from — the cost trade-off:** a false positive here (calling two different people "the same name") lets a genuine compliance gap slip through silently — that's the expensive failure mode for Prozo. A false negative (flagging a real employee's own name as a mismatch because of a spelling quirk) just costs the compliance team a few seconds of manual double-checking, since the report shows both names and the score side by side. Given that asymmetry, the threshold is set on the stricter side rather than the lenient one — tolerant enough to absorb routine variation, but not so loose that a different person could pass as a match.

**Calibration examples** (from the code's own test cases and an actual run):

| Wagesheet name | ECR name | Score | Verdict |
|---|---|---|---|
| MOHD RAFIQUE | MOHAMMAD RAFIQUE | 85.7 | Accepted — common abbreviation |
| RAKESH VERMA | VERMA RAKESH | 100 | Accepted — word order only |
| SUNIL KUMAR SINGH | SUNIL K SINGH | 86.7 | Accepted — initialised middle name |
| DINESH PRASAD | DEVENDRA PRASAD | 64.3 | Caught — genuinely different first name |
| REKHA SHARMA | RENU SHARMA | 78.3 | Caught — genuinely different first name |
| ANJALI | ANJANI | 83.3 | Caught — one letter apart, still below threshold |

There is currently no separate "borderline / needs review" band — the cutoff is a strict boolean at 85. The similarity score is always included in the report's Reason column, so a human reviewer can still judge a close call (e.g. an 83) themselves; see [What I'd Improve](#what-id-improve-with-more-time).

### Amount matching

PF: the wagesheet's `PF @ 12%` column value is compared directly to the PF ECR's **EE contribution** for that UAN. ESIC: the wagesheet's `ESIC @ 0.75%` column value is compared directly to the ESIC ECR's **IP contribution** for that IP Number. In both cases the comparison is `wagesheet_amount − ecr_amount`; a difference within **±₹1** is treated as a match (to absorb standard paise-level rounding between the two documents), and anything beyond that is an **Amount mismatch**, with both values and the signed difference shown in the report.

Note: the app does not itself recompute 12%/0.75% of a gross wage figure — it trusts the wagesheet's stated PF/ESIC column as already being that calculated contribution, since the wagesheet does not carry a separate gross-wage column for the app to derive it from. See [Assumptions & Design Trade-offs](#assumptions--design-trade-offs).

### PDF parsing at scale

Both ECR PDFs are parsed by extracting word positions per page with PyMuPDF ([processing/pdf_backend.py](processing/pdf_backend.py)) — a compiled backend, not a pure-Python one, so a several-hundred-page filing parses in well under a second. [processing/pdf_rows.py](processing/pdf_rows.py) groups words into visual rows, then identifies genuine member rows using one structural invariant: the row's first token is an integer strictly greater than the last serial number seen, and one of the next couple of tokens is a numeric identifier. This works regardless of whether the header repeats on every page, and doesn't depend on the sample's specific row count or column pixel positions, so it generalises to a much larger, unseen filing. Pages are processed one at a time and their word lists discarded once consumed, rather than holding the whole document's words in memory at once.

**What happens when a row or page fails to parse:** a row that doesn't even look like a member row (headers, footers, subtotal rows) is skipped silently — that's expected, not a failure. A row that *does* look like a member row (right serial number pattern) but then fails a downstream step — e.g. one of the trailing numeric columns isn't a parseable number — is skipped and recorded as a warning string (e.g. `"PF ECR: could not parse row with Sl.No 47, skipped"`). These warnings are surfaced in the UI ("N row(s) in the ECR PDFs could not be parsed and were skipped") and listed in full in the downloaded report's summary block. If a PDF yields zero parseable member rows at all, the whole job fails with a clear error rather than silently producing an empty report.

**Layout assumption, stated truthfully:** this is built and tested against the standard EPFO ECR portal template and one ESIC contribution-history template, both with one member per single visual line. A name or field that wraps across two lines in the PDF is not currently reassembled into one row.

### Table B — Bad input & data-level edge cases

| Scenario | System behaviour today |
|---|---|
| Corrupt/unreadable Excel file uploaded as the wagesheet | `openpyxl` raises on load; caught and surfaced as a clear job error ("Could not read wagesheet Excel file: ..."), not a crash. |
| Corrupt/unreadable PDF uploaded as either ECR | PyMuPDF's open fails; caught and surfaced as a clear job error ("Could not read PF/ESIC ECR PDF: ..."), not a crash. |
| Wrong file type placed in a slot but with a matching extension (e.g. a renamed PDF saved as `.xlsx`) | Passes the upfront extension check, then fails at parse time with the same clear error as a corrupt file above. |
| Wrong file type with a mismatched extension (e.g. a `.docx` in the wagesheet slot) | Rejected immediately with a 400 response before any processing starts (e.g. "Wagesheet must be an Excel file (.xlsx or .xls)."). |
| One of the three files missing from the form | Rejected immediately with a specific message naming which file is missing. |
| Empty (0-byte) file in any slot | Rejected immediately after upload with "The uploaded {file} file is empty." |
| Legacy binary `.xls` file | Accepted by the extension check, but `openpyxl` cannot read the legacy binary format — fails at parse time with a generic read error rather than being rejected upfront with an accurate message (see [Known Limitations](#known-limitations)). |
| Duplicate UAN/IP Number rows within the wagesheet | Each row is verified independently against the same ECR record; not flagged as a duplicate. |
| Duplicate UAN/IP Number rows within an ECR PDF | The later row silently overwrites the earlier one in the in-memory lookup; no warning is raised for this specific case. |
| Blank/malformed identifier cell in the wagesheet | Treated as no identifier present → verdict is `Missing` with reason "Wagesheet row has no UAN/IP Number". |
| Zero-value PF/ESIC amount in the wagesheet | Compared numerically like any other value — a genuine zero vs. zero is `Matched`; zero vs. a non-zero ECR amount is `Amount mismatch`. |
| Employee present in an ECR but with no corresponding wagesheet row | Never surfaced — the verification loop walks wagesheet rows only, so an "extra" ECR member is not reported in either direction. |
| Blank row in the middle of the wagesheet | Skipped silently (rows where every cell is blank are not counted as employees). |

## Assumptions & Design Trade-offs

- **Wagesheet:** single header row, one data row per employee, on the first worksheet. Columns are located by a case-insensitive keyword match on the header text (e.g. any header containing "uan"), not by exact text or fixed position — so column order is flexible but the keyword must be present. Name, UAN, IP Number, ESIC amount, and PF amount columns are all required; the file is rejected outright if any is missing.
- **PF/ESIC amount columns are trusted at face value.** The wagesheet's `PF @ 12%` / `ESIC @ 0.75%` cells are compared directly to the ECR as already-computed contributions — the app does not independently recompute 12%/0.75% of a gross wage, because the wagesheet parser doesn't read a gross-wage column at all.
- **Identifiers are opaque digit strings, matched by exact string equality.** A wagesheet cell stored as a float (e.g. `999912340001.0`) is coerced to an integer-then-string to drop the trailing `.0`, but no further normalisation (zero-padding, whitespace beyond a simple strip) is applied. No digit-count validation is enforced against the real-world UAN (12 digits) or IP Number (10 digits) formats — the PDF row detector accepts any run of 5 or more digits as a candidate identifier, deliberately permissive so it isn't tied to one specific authority's format.
- **PF ECR PDF layout:** `Sl.No, UAN`, two adjacent free-text name columns with no delimiter (ECR name, then UAN-repository name), followed by exactly 8 trailing numeric columns in this fixed order — Gross Wages, EPF Wages, EPS Wages, EDLI Wages, EE, EPS, ER, NCP Days. The EE column is taken as the PF contribution.
- **ESIC ECR PDF layout:** `SNo`, an optional "Is Disable" flag, `IP Number`, a free-text IP name, `No. of Days`, `Total Wages`, `IP Contribution`, and an optional trailing `Reason`. Wages/contribution are located as the last adjacent pair of two-decimal-place tokens in the row, so a layout with extra decimal-formatted values after that pair could confuse detection.
- **One member row = one visual PDF line.** Words within roughly 2.5pt of vertical position are grouped into the same row; a field wrapping across two lines is not reassembled.
- **Currency:** plain decimal rupee figures with comma thousands-separators (e.g. `13,520.00`); no currency symbol parsing, no multi-currency support.
- **Rounding tolerance:** a flat ±₹1 applies uniformly to both PF and ESIC amount comparisons.
- **Upload size cap:** 100 MB per request (all three files combined), enforced by Flask's `MAX_CONTENT_LENGTH`.
- **Job durability:** job status/results live only in an in-process dict for the life of the server (6-hour TTL); nothing is persisted to disk except the generated `.xlsx` report itself, and the uploaded source files are deleted immediately after processing.

## Known Limitations

- No sample wagesheet or ECR PDFs are committed to this repository — `uploads/` (where they'd naturally sit during development) is git-ignored because real files contain personal salary data. A fresh clone has nothing to test against out of the box; see [Testing](#testing).
- No automated test suite exists yet.
- `.xls` (legacy binary Excel) is accepted by the upload form and the server's extension whitelist, but the underlying reader (`openpyxl`) only actually supports `.xlsx`/`.xlsm` — a real `.xls` upload fails at parse time with a generic error instead of being rejected upfront with an accurate "only .xlsx" message.
- A name or identifier that wraps across two visual lines in a PDF is not reassembled into one row; that row is either mis-parsed or skipped with a warning.
- Duplicate UAN/IP Number rows within a single ECR PDF are resolved by last-one-wins with no warning raised (in contrast to genuinely unparsable rows, which do raise a warning).
- The tool only checks in one direction: every wagesheet row is verified against the ECRs, but an ECR member with no matching wagesheet row is never flagged.
- Identifier matching has no fuzzy tolerance at all (unlike names) — any formatting drift between the two documents (e.g. inconsistent leading zeros) that isn't already normalised away would read as `Missing` rather than a near-match.
- The name-match threshold is a hard cutoff with no borderline "needs review" band; a score of 84 and a score of 40 are both reported identically as `Name mismatch` (though the score itself is retained for a human to judge).
- Only verified against the standard EPFO ECR portal template and one ESIC contribution-history template; other portal versions or regional formatting variants haven't been tested and may fail to parse.
- Job state lives in memory only — restarting the Flask process loses all in-flight and completed job history; only a report the user already downloaded survives.
- Runs on Flask's built-in development server with a 2-worker thread pool — adequate for internal, small-team use, but not hardened for public/production deployment (no authentication, no rate limiting, no WSGI server in front of it).

## What I'd Improve With More Time

1. **A "needs review" band for borderline name scores** (e.g. 75–84), reported as a distinct verdict rather than being forced into `Matched`/`Name mismatch`, so the compliance team's attention is directed exactly where the matcher itself is least confident.
2. **Ship small, fully synthetic sample files** (a sample wagesheet plus matching PF/ESIC ECR PDFs, with a script to regenerate them) so a fresh clone can be smoke-tested in under a minute without needing a real vendor file — this is the most immediate gap against the brief's "runs in under 15 minutes" bar.
3. **Reverse-direction check:** flag ECR members with no corresponding wagesheet row as their own summary count, to catch potential ghost beneficiaries or vendor under-reporting, not just under-deposits.
4. **A committed, labeled name-pair evaluation set** (accept/reject pairs) with a small script reporting the current threshold's precision/recall, so future threshold tuning is validated against data instead of ad hoc judgment.
5. **Warn on duplicate UAN/IP Number** within a single ECR PDF and within the wagesheet, instead of silently resolving or ignoring them.
6. **Reject `.xls` uploads upfront** with an accurate message (or add real legacy-format support), instead of accepting the extension and failing later with a generic parse error.
7. **Persist job state** (e.g. SQLite) so results survive a server restart, and add basic auth/rate-limiting if this is ever exposed beyond one internal team's network.

## Testing

There is no automated test suite in this repository today, and no sample input files are committed — the `uploads/` directory used during local development is intentionally listed in [.gitignore](.gitignore), since real wagesheets and ECR filings carry personal salary data that shouldn't end up in source control.

Each verification run writes its generated report to `uploads/<job-id>/report.xlsx`, created fresh per run and cleaned up along with the rest of that job's temporary folder — there is no persistent "sample output" file shipped in the repo either.

To exercise the pipeline locally, supply your own wagesheet and ECR PDFs (see [Assumptions & Design Trade-offs](#assumptions--design-trade-offs) for the exact expected layouts), or build a small synthetic set — a handful of rows covering all four verdicts is enough to confirm the pipeline end to end.

## Project Structure

```
.
├── app.py                    Flask entry point: routes, upload validation, job orchestration
├── processing/
│   ├── excel_reader.py       Wagesheet (.xlsx) parsing -> employee records
│   ├── pdf_backend.py        PyMuPDF word-extraction wrapper
│   ├── pdf_rows.py           Shared row-detection / column-splitting helpers for both ECR parsers
│   ├── pf_ecr_parser.py      EPFO PF ECR PDF -> per-UAN member records
│   ├── esic_ecr_parser.py    ESIC ECR PDF -> per-IP-Number member records
│   ├── name_match.py         Name normalisation + RapidFuzz comparison (the tolerance logic)
│   ├── verify.py             Per-employee PF/ESIC verdict logic -- the matching engine
│   ├── report.py             Builds the downloadable .xlsx verification report
│   └── jobs.py               In-memory background job manager (thread pool, progress polling)
├── static/
│   ├── index.html            Upload / progress / results page markup
│   ├── app.js                Upload, polling, results rendering/filtering, download link
│   └── style.css              Styling, including dark mode
├── requirements.txt           Pinned dependencies
├── start_app.bat              Windows one-click installer + launcher
└── uploads/                   Runtime scratch dir for uploads + generated reports (git-ignored)
```

## Demo

<!-- DEMO: paste video link or deployed URL below -->
📽️ The demo video highlights position-based PDF parsing, RapidFuzz name matching, and colour-coded Excel report exports. You can view it here: https://youtu.be/rmkLd5jptc0
