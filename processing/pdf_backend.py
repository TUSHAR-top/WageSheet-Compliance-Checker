"""
PDF word-extraction backend, built on PyMuPDF (fitz).

PyMuPDF's text extraction is a compiled (MuPDF) implementation rather than
pdfminer's pure-Python one, which matters here: a several-hundred-page ECR
parses in well under a second instead of tens of seconds, keeping background
jobs snappy even for the largest real filings.
"""
import fitz


class PdfOpenError(Exception):
    pass


def extract_pages_words(pdf_path):
    """Yield, per page, a list of word-dicts: {'text', 'x0', 'x1', 'top', 'bottom'}."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        raise PdfOpenError("The file is not a readable PDF.") from exc

    try:
        if doc.page_count == 0:
            raise PdfOpenError("PDF has no pages.")
        for page in doc:
            words = page.get_text("words")  # x0, y0, x1, y1, text, block_no, line_no, word_no
            yield [
                {"text": w[4], "x0": w[0], "x1": w[2], "top": w[1], "bottom": w[3]}
                for w in words
            ]
    finally:
        doc.close()
