# Wagesheet vs. ECR Compliance Verification

Matches a vendor wagesheet (Excel) against PF and ESIC ECR filings (PDF),
employee by employee, and produces a downloadable spreadsheet verdict.

## Run

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000, upload the wagesheet + PF ECR + ESIC ECR, and
submit. Large filings process in a background thread — the status bar polls
every 1.5s and the job survives a page refresh (job id is kept in
`localStorage`), so you can leave and come back.

## How matching works

- **Identifiers**: wagesheet `UAN` is matched against the PF ECR's `UAN`
  column; wagesheet `IP Number` against the ESIC ECR's `IP Number` column.
  Not found → **Missing**.
- **Names**: compared with RapidFuzz `token_sort_ratio` (word-order
  independent) after uppercasing, stripping punctuation, and dropping a
  small set of honorifics (MR/MRS/MS/SHRI/SMT/DR/KUM). Threshold **85**,
  chosen so word reordering and common abbreviations (e.g. "MOHD" vs
  "MOHAMMAD") still match, while genuinely different names (e.g. "DEVENDRA
  PRASAD" vs "DINESH PRASAD", scoring 64) are flagged as **Name mismatch**.
  See `processing/name_match.py` for the calibration cases.
- **Amounts**: PF @ 12% compared to the ECR's EE share, ESIC @ 0.75%
  compared to the ECR's IP contribution, with a ₹1 tolerance for standard
  rounding. Beyond that → **Amount mismatch** (both values + diff shown).
- Anything not Missing/mismatched → **Matched**.

## PDF parsing approach

Both ECR PDFs are parsed by extracting word positions (PyMuPDF) and using
the fact that every member row starts with a strictly-increasing serial
number followed by a numeric identifier — this locates data rows reliably
across any number of pages without depending on the header repeating per
page. Two adjacent name columns in the PF ECR (with no delimiter between
them) are split at the widest horizontal gap between words, since column
gutters are visually wider than intra-name word spacing. This is
position-based rather than hard-coded to the sample's row count/names, so it
holds up on larger, unseen filings — verified against a synthetic 6,000-row,
~250-page PDF (parses in well under a second).

## Known limitations

- Assumes the standard EPFO/ESIC ECR portal template (single-line member
  rows). A row that wraps a name across two lines would not be parsed.
- Wagesheet columns are matched by keyword (e.g. any header containing
  "UAN"), not exact text, but the workbook is still expected to have one
  header row and one row per employee.
