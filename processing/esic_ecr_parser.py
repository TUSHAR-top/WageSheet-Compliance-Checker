"""
Parse an ESIC Contribution History PDF into per-insured-person records.

Each member row in the template is:
    SNo  Is-Disable  IP-Number  <IP Name>  No-Of-Days  Total-Wages  IP-Contribution  Reason

"Is Disable" is usually "-" but the column is optional in some exports, and
"Reason" can be blank or free text, so both ends of the row are located by
pattern rather than fixed offsets:
  - IP Number is whichever of token[1]/token[2] first matches a numeric ID.
  - Total-Wages / IP-Contribution are located as the last adjacent pair of
    two-decimal-place numbers in the row (e.g. "13520.00 102.00").
"""
import re

from .pdf_backend import extract_pages_words
from .pdf_rows import iter_data_rows, join_text, parse_number

_ID_RE = re.compile(r"^\d{5,}$")
_DECIMAL_RE = re.compile(r"^[\d,]+\.\d{2}$")
_INT_RE = re.compile(r"^\d+$")


class EsicEcrParseError(Exception):
    pass


def _find_wage_contribution_pair(row):
    """Find the index of the last adjacent pair of decimal-formatted tokens."""
    for i in range(len(row) - 2, 0, -1):
        if _DECIMAL_RE.match(row[i]["text"]) and _DECIMAL_RE.match(row[i + 1]["text"]):
            return i
    return None


def parse_esic_ecr(pdf_path):
    """
    Returns dict keyed by IP Number (string) -> {
        'ip_number', 'name', 'ip_contribution', 'sl_no'
    }
    """
    members = {}
    warnings = []
    try:
        for serial, row in iter_data_rows(extract_pages_words(pdf_path), min_words=6):
            if _ID_RE.match(row[1]["text"]):
                ip_index = 1
            elif _ID_RE.match(row[2]["text"]):
                ip_index = 2
            else:
                warnings.append(f"ESIC ECR: could not locate IP Number on row Sl.No {serial}, skipped")
                continue

            ip_number = row[ip_index]["text"].strip()

            pair_idx = _find_wage_contribution_pair(row)
            if pair_idx is None:
                warnings.append(f"ESIC ECR: could not parse contribution amount on row Sl.No {serial}, skipped")
                continue

            days_idx = pair_idx - 1
            if days_idx <= ip_index or not _INT_RE.match(row[days_idx]["text"]):
                warnings.append(f"ESIC ECR: unexpected row layout at Sl.No {serial}, skipped")
                continue

            name_words = row[ip_index + 1:days_idx]
            ip_contribution = parse_number(row[pair_idx + 1]["text"])

            if not name_words or ip_contribution is None:
                warnings.append(f"ESIC ECR: could not parse row with Sl.No {serial}, skipped")
                continue

            members[ip_number] = {
                "ip_number": ip_number,
                "name": join_text(name_words),
                "ip_contribution": ip_contribution,
                "sl_no": serial,
            }
    except Exception as exc:
        if isinstance(exc, EsicEcrParseError):
            raise
        raise EsicEcrParseError(f"Could not read ESIC ECR PDF: {exc}") from exc

    if not members:
        raise EsicEcrParseError(
            "No member rows could be found in the ESIC ECR PDF. "
            "Confirm this is an ESIC contribution history export and not a corrupted or unrelated file."
        )

    return members, warnings
