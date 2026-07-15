"""Read the vendor wagesheet (.xlsx) into a list of employee records."""
import openpyxl

REQUIRED = ["name", "uan", "ip_number", "esic_amount", "pf_amount"]


class WagesheetParseError(Exception):
    pass


def _classify_header(text):
    t = str(text or "").strip().lower()
    if not t:
        return None
    if t.startswith("name"):
        return "name"
    if "uan" in t:
        return "uan"
    if "ip" in t and "number" in t:
        return "ip_number"
    if "ip" in t and t.replace(" ", "") in ("ipno", "ip#"):
        return "ip_number"
    if "esic" in t:
        return "esic_amount"
    if "pf" in t:
        return "pf_amount"
    if "agency" in t:
        return "agency"
    if "state" in t:
        return "state"
    return None


def _clean_id(value):
    """Normalise an identifier cell (UAN / IP Number) to a plain digit string."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_wagesheet(xlsx_path):
    """Returns list of dicts: name, uan, ip_number, esic_amount, pf_amount, agency, state, row_no."""
    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    except Exception as exc:
        raise WagesheetParseError(f"Could not read wagesheet Excel file: {exc}") from exc

    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration:
        raise WagesheetParseError("Wagesheet is empty.")

    column_map = {}
    for idx, cell in enumerate(header):
        kind = _classify_header(cell)
        if kind and kind not in column_map:
            column_map[kind] = idx

    missing = [c for c in REQUIRED if c not in column_map]
    if missing:
        raise WagesheetParseError(
            "Wagesheet is missing required column(s): " + ", ".join(missing) +
            ". Expected columns for Name, UAN, IP Number, ESIC amount and PF amount."
        )

    employees = []
    for row_no, row in enumerate(rows, start=2):
        if row is None or all(v is None or str(v).strip() == "" for v in row):
            continue

        def get(kind):
            idx = column_map.get(kind)
            return row[idx] if idx is not None and idx < len(row) else None

        name = str(get("name") or "").strip()
        uan = _clean_id(get("uan"))
        ip_number = _clean_id(get("ip_number"))
        esic_raw = get("esic_amount")
        pf_raw = get("pf_amount")

        if not name and not uan and not ip_number:
            continue

        try:
            esic_amount = float(esic_raw) if esic_raw not in (None, "") else None
        except (TypeError, ValueError):
            esic_amount = None
        try:
            pf_amount = float(pf_raw) if pf_raw not in (None, "") else None
        except (TypeError, ValueError):
            pf_amount = None

        employees.append({
            "row_no": row_no,
            "name": name,
            "uan": uan,
            "ip_number": ip_number,
            "esic_amount": esic_amount,
            "pf_amount": pf_amount,
            "agency": str(get("agency") or "").strip(),
            "state": str(get("state") or "").strip(),
        })

    if not employees:
        raise WagesheetParseError("Wagesheet has a header row but no employee data rows.")

    return employees
