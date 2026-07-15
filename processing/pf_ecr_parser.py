"""
Parse an EPFO Electronic Challan cum Return (ECR) PDF into per-member records.

Each member row in the template is:
    Sl.No  UAN  <Name as per ECR>  <Name as per UAN Repository>
           Gross-Wages  EPF-Wages  EPS-Wages  EDLI-Wages  EE  EPS  ER  NCP-Days

The two name columns have no delimiter between them, so they're split at the
widest horizontal gap (see pdf_rows.split_by_largest_gap). The trailing 8
columns are single tokens each, so they're taken as a fixed-size window from
the end of the row -- robust regardless of how many words the names contain.
"""
from .pdf_backend import extract_pages_words
from .pdf_rows import iter_data_rows, join_text, parse_number, split_by_largest_gap

TRAILING_NUMERIC_COLUMNS = 8  # gross, epf_wages, eps_wages, edli_wages, ee, eps, er, ncp_days


class PfEcrParseError(Exception):
    pass


def parse_pf_ecr(pdf_path):
    """
    Returns dict keyed by UAN (string) -> {
        'uan', 'name', 'name_uan_repository', 'ee_contribution', 'sl_no'
    }
    """
    members = {}
    warnings = []
    try:
        for serial, row in iter_data_rows(extract_pages_words(pdf_path), min_words=2 + 1 + 8):
            uan = row[1]["text"].strip()
            tail = row[-TRAILING_NUMERIC_COLUMNS:]
            middle = row[2:-TRAILING_NUMERIC_COLUMNS]

            tail_values = [parse_number(w["text"]) for w in tail]
            if any(v is None for v in tail_values) or not middle:
                warnings.append(f"PF ECR: could not parse row with Sl.No {serial}, skipped")
                continue

            name_words, uan_repo_words = split_by_largest_gap(middle)
            ee_contribution = tail_values[4]

            members[uan] = {
                "uan": uan,
                "name": join_text(name_words),
                "name_uan_repository": join_text(uan_repo_words),
                "ee_contribution": ee_contribution,
                "sl_no": serial,
            }
    except Exception as exc:
        raise PfEcrParseError(f"Could not read PF ECR PDF: {exc}") from exc

    if not members:
        raise PfEcrParseError(
            "No member rows could be found in the PF ECR PDF. "
            "Confirm this is an EPFO ECR export and not a corrupted or unrelated file."
        )

    return members, warnings
