"""
Shared helpers for pulling tabular rows out of EPFO/ESIC-style ECR PDFs.

These PDFs are generated from a fixed portal template: every member row starts
with a strictly-increasing serial number followed by a numeric identifier
(UAN or IP Number). We use that invariant to find data rows reliably across
an arbitrary number of pages, whether or not the column header repeats on
every page -- so this works the same on a 2-page sample and a 200-page filing.
"""
import re

_ID_RE = re.compile(r"^\d{5,}$")
_INT_RE = re.compile(r"^\d+$")


def group_words_into_rows(words, top_tolerance=2.5):
    """Cluster words (from pdfplumber's extract_words) into visual rows."""
    rows = []
    current = []
    current_top = None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(w["top"] - current_top) <= top_tolerance:
            current.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            rows.append(sorted(current, key=lambda w: w["x0"]))
            current = [w]
            current_top = w["top"]
    if current:
        rows.append(sorted(current, key=lambda w: w["x0"]))
    return rows


def iter_data_rows(pages_words, min_words=6):
    """
    Yield (serial_no, [word, ...]) for every row across the whole PDF that
    looks like a member row: first token is an integer strictly greater than
    the last serial number seen, and one of the next couple of tokens is a
    numeric identifier (UAN / IP Number) -- allowing for an optional flag
    column (e.g. ESIC's "Is Disable") between the serial number and the id.
    Rows failing this are header/footer/summary noise and are skipped.

    pages_words: iterable yielding, per page, a list of word-dicts
    ({'text','x0','x1','top','bottom'}) -- see pdf_backend.extract_pages_words.
    """
    last_serial = 0
    for words in pages_words:
        for row in group_words_into_rows(words):
            if len(row) < min_words:
                continue
            first = row[0]["text"]
            if not _INT_RE.match(first):
                continue
            if not (_ID_RE.match(row[1]["text"]) or _ID_RE.match(row[2]["text"])):
                continue
            serial = int(first)
            if serial <= last_serial:
                continue
            last_serial = serial
            yield serial, row


def split_by_largest_gap(words):
    """
    Split a run of words that spans two adjacent free-text columns (e.g. two
    "Name" columns with no delimiter) at the single widest horizontal gap.
    Column gutters in these templates are noticeably wider than the spacing
    between words within one name, so the widest gap is the column boundary.
    """
    if len(words) <= 1:
        return words, []
    gaps = [words[i + 1]["x0"] - words[i]["x1"] for i in range(len(words) - 1)]
    split_at = gaps.index(max(gaps)) + 1
    return words[:split_at], words[split_at:]


def join_text(words):
    return " ".join(w["text"] for w in words).strip()


def parse_number(text):
    """Parse an ECR-formatted number ('13,520' / '102.00' / '1,622') to float."""
    if text is None:
        return None
    cleaned = str(text).replace(",", "").strip()
    if cleaned in ("", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
