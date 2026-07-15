"""
Wagesheet vs. ECR Compliance Verification -- Flask app.

Endpoints:
    GET  /                          -> upload UI
    POST /api/verify                -> accept 3 files, start background job, return job_id
    GET  /api/status/<job_id>       -> {status, message, progress}
    GET  /api/result/<job_id>       -> {summary, results} once done
    GET  /api/download/<job_id>     -> the .xlsx report
"""
import os
import uuid

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from processing.jobs import get_job, purge_expired, submit_job

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")

ALLOWED_EXCEL_EXT = {".xlsx", ".xls"}
ALLOWED_PDF_EXT = {".pdf"}

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB


def _ext(filename):
    return os.path.splitext(filename or "")[1].lower()


def _bad_request(message):
    return jsonify({"error": message}), 400


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/verify", methods=["POST"])
def api_verify():
    purge_expired()

    wagesheet = request.files.get("wagesheet")
    pf_ecr = request.files.get("pf_ecr")
    esic_ecr = request.files.get("esic_ecr")

    if not wagesheet or not wagesheet.filename:
        return _bad_request("Please attach the vendor wagesheet (.xlsx).")
    if not pf_ecr or not pf_ecr.filename:
        return _bad_request("Please attach the PF ECR PDF.")
    if not esic_ecr or not esic_ecr.filename:
        return _bad_request("Please attach the ESIC ECR PDF.")

    if _ext(wagesheet.filename) not in ALLOWED_EXCEL_EXT:
        return _bad_request("Wagesheet must be an Excel file (.xlsx or .xls).")
    if _ext(pf_ecr.filename) not in ALLOWED_PDF_EXT:
        return _bad_request("PF ECR must be a PDF file.")
    if _ext(esic_ecr.filename) not in ALLOWED_PDF_EXT:
        return _bad_request("ESIC ECR must be a PDF file.")

    job_id = uuid.uuid4().hex
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    wagesheet_path = os.path.join(job_dir, "wagesheet" + _ext(wagesheet.filename))
    pf_ecr_path = os.path.join(job_dir, "pf_ecr.pdf")
    esic_ecr_path = os.path.join(job_dir, "esic_ecr.pdf")

    wagesheet.save(wagesheet_path)
    pf_ecr.save(pf_ecr_path)
    esic_ecr.save(esic_ecr_path)

    for path, label in ((wagesheet_path, "wagesheet"), (pf_ecr_path, "PF ECR"), (esic_ecr_path, "ESIC ECR")):
        if os.path.getsize(path) == 0:
            return _bad_request(f"The uploaded {label} file is empty.")

    real_job_id = submit_job(wagesheet_path, pf_ecr_path, esic_ecr_path)
    return jsonify({"job_id": real_job_id}), 202


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job id. It may have expired."}), 404
    return jsonify(job.to_status_dict())


@app.route("/api/result/<job_id>")
def api_result(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job id. It may have expired."}), 404
    if job.status == "error":
        return jsonify({"error": job.message}), 422
    if job.status != "done":
        return jsonify({"error": "Job is not finished yet."}), 409
    return jsonify({
        "summary": job.summary,
        "results": job.results,
        "warnings": job.warnings,
    })


@app.route("/api/download/<job_id>")
def api_download(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job id. It may have expired."}), 404
    if job.status != "done" or not job.report_path or not os.path.exists(job.report_path):
        return jsonify({"error": "Report is not ready yet."}), 409
    return send_file(
        job.report_path,
        as_attachment=True,
        download_name=f"Wagesheet_ECR_Verification_{job_id[:8]}.xlsx",
    )


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_exc):
    return jsonify({"error": "Upload is too large (limit 100 MB)."}), 413


@app.errorhandler(404)
def handle_not_found(_exc):
    return jsonify({"error": "Not found."}), 404


@app.errorhandler(500)
def handle_server_error(_exc):
    return jsonify({"error": "An unexpected server error occurred."}), 500


if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
