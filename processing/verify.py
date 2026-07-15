"""Core matching logic: wagesheet rows vs. PF ECR / ESIC ECR records."""
from .name_match import compare_names

AMOUNT_TOLERANCE = 1.0  # rupee, to absorb standard EPFO/ESIC rounding

STATUS_MATCHED = "Matched"
STATUS_NAME_MISMATCH = "Name mismatch"
STATUS_AMOUNT_MISMATCH = "Amount mismatch"
STATUS_MISSING = "Missing"


def _check_one(wage_name, wage_amount, identifier, ecr_members, id_label, amount_field, amount_label):
    if not identifier:
        return {
            "status": STATUS_MISSING,
            "reason": f"Wagesheet row has no {id_label}",
            "ecr_name": None,
            "name_score": None,
            "ecr_amount": None,
            "wagesheet_amount": wage_amount,
            "diff": None,
        }

    member = ecr_members.get(identifier)
    if member is None:
        return {
            "status": STATUS_MISSING,
            "reason": f"{id_label} {identifier} not found in ECR",
            "ecr_name": None,
            "name_score": None,
            "ecr_amount": None,
            "wagesheet_amount": wage_amount,
            "diff": None,
        }

    is_match, score = compare_names(wage_name, member["name"])
    if not is_match:
        return {
            "status": STATUS_NAME_MISMATCH,
            "reason": f"Wagesheet name '{wage_name}' vs ECR name '{member['name']}' (similarity {score})",
            "ecr_name": member["name"],
            "name_score": score,
            "ecr_amount": member[amount_field],
            "wagesheet_amount": wage_amount,
            "diff": None,
        }

    ecr_amount = member[amount_field]
    if wage_amount is None or ecr_amount is None:
        return {
            "status": STATUS_AMOUNT_MISMATCH,
            "reason": f"{amount_label} amount missing on one side (wagesheet={wage_amount}, ECR={ecr_amount})",
            "ecr_name": member["name"],
            "name_score": score,
            "ecr_amount": ecr_amount,
            "wagesheet_amount": wage_amount,
            "diff": None,
        }

    diff = round(wage_amount - ecr_amount, 2)
    if abs(diff) > AMOUNT_TOLERANCE:
        return {
            "status": STATUS_AMOUNT_MISMATCH,
            "reason": f"Wagesheet {amount_label} {wage_amount} vs ECR {ecr_amount} (diff {diff})",
            "ecr_name": member["name"],
            "name_score": score,
            "ecr_amount": ecr_amount,
            "wagesheet_amount": wage_amount,
            "diff": diff,
        }

    return {
        "status": STATUS_MATCHED,
        "reason": "Matched",
        "ecr_name": member["name"],
        "name_score": score,
        "ecr_amount": ecr_amount,
        "wagesheet_amount": wage_amount,
        "diff": diff,
    }


def verify_employees(employees, pf_members, esic_members):
    results = []
    summary = {
        "total_employees": len(employees),
        "pf": {STATUS_MATCHED: 0, STATUS_NAME_MISMATCH: 0, STATUS_AMOUNT_MISMATCH: 0, STATUS_MISSING: 0},
        "esic": {STATUS_MATCHED: 0, STATUS_NAME_MISMATCH: 0, STATUS_AMOUNT_MISMATCH: 0, STATUS_MISSING: 0},
    }

    for emp in employees:
        pf_result = _check_one(
            emp["name"], emp["pf_amount"], emp["uan"], pf_members,
            "UAN", "ee_contribution", "PF",
        )
        esic_result = _check_one(
            emp["name"], emp["esic_amount"], emp["ip_number"], esic_members,
            "IP Number", "ip_contribution", "ESIC",
        )
        summary["pf"][pf_result["status"]] += 1
        summary["esic"][esic_result["status"]] += 1

        results.append({
            "row_no": emp["row_no"],
            "name": emp["name"],
            "uan": emp["uan"],
            "ip_number": emp["ip_number"],
            "agency": emp["agency"],
            "state": emp["state"],
            "pf": pf_result,
            "esic": esic_result,
        })

    return results, summary
