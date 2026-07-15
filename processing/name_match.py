"""
Name comparison with tolerance for the spelling and word-order variation that
is routine across payroll/UAN/ESIC records, while still flagging genuinely
different names.

Method: uppercase + punctuation-stripped + honorific-stripped normalisation,
then RapidFuzz's token_sort_ratio (word-order independent Levenshtein ratio)
against a threshold of 85, calibrated against real-world cases:

  matches (>=85):  "MOHD RAFIQUE" vs "MOHAMMAD RAFIQUE"      -> 85.7
                    "SUNIL KUMAR SINGH" vs "SUNIL K SINGH"    -> 86.7
                    "RAKESH VERMA" vs "VERMA RAKESH"          -> 100 (word order)
  mismatches (<85): "DEVENDRA PRASAD" vs "DINESH PRASAD"      -> 64.3
                     "REKHA SHARMA" vs "RENU SHARMA"          -> 78.3
                     "ANJALI" vs "ANJANI"                     -> 83.3

85 sits above common initials/abbreviation noise and below same-length
different-name confusions, so it catches genuine mismatches without flagging
trivial variations.
"""
import re

from rapidfuzz import fuzz

MATCH_THRESHOLD = 85

_HONORIFICS = {"MR", "MRS", "MS", "SHRI", "SMT", "DR", "KUM"}
_PUNCT_RE = re.compile(r"[.,'\-/]")
_SPACE_RE = re.compile(r"\s+")


def normalize_name(name):
    if not name:
        return ""
    name = _PUNCT_RE.sub(" ", str(name).upper())
    words = [w for w in _SPACE_RE.split(name) if w and w not in _HONORIFICS]
    return " ".join(words)


def compare_names(name_a, name_b):
    """Returns (is_match: bool, score: float 0-100)."""
    a = normalize_name(name_a)
    b = normalize_name(name_b)
    if not a or not b:
        return False, 0.0
    score = fuzz.token_sort_ratio(a, b)
    return score >= MATCH_THRESHOLD, round(score, 1)
