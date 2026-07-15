"""
In-memory background job manager.

Verification of a large ECR (hundreds of pages) can take a while, so uploads
are processed on a worker thread while the browser polls /api/status/<job_id>
for progress. The user can close the tab and come back later; results stay
available (for the lifetime of the server process) via the job id.
"""
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .esic_ecr_parser import EsicEcrParseError, parse_esic_ecr
from .excel_reader import WagesheetParseError, parse_wagesheet
from .pf_ecr_parser import PfEcrParseError, parse_pf_ecr
from .report import build_report
from .verify import verify_employees

_executor = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()
_jobs = {}

JOB_TTL_SECONDS = 6 * 60 * 60  # 6 hours


class Job:
    def __init__(self, job_id):
        self.id = job_id
        self.status = "queued"
        self.message = "Queued"
        self.progress = 0
        self.created_at = time.time()
        self.summary = None
        self.results = None
        self.warnings = None
        self.report_path = None

    def to_status_dict(self):
        return {
            "job_id": self.id,
            "status": self.status,
            "message": self.message,
            "progress": self.progress,
        }


def _update(job, **kwargs):
    with _lock:
        for k, v in kwargs.items():
            setattr(job, k, v)


def get_job(job_id):
    with _lock:
        return _jobs.get(job_id)


def _run(job_id, wagesheet_path, pf_ecr_path, esic_ecr_path):
    job = get_job(job_id)
    if job is None:
        return
    try:
        _update(job, status="processing", message="Reading wagesheet...", progress=10)
        employees = parse_wagesheet(wagesheet_path)

        _update(job, message="Parsing PF ECR PDF...", progress=30)
        pf_members, pf_warnings = parse_pf_ecr(pf_ecr_path)

        _update(job, message="Parsing ESIC ECR PDF...", progress=55)
        esic_members, esic_warnings = parse_esic_ecr(esic_ecr_path)

        _update(job, message="Matching employees against ECR filings...", progress=75)
        results, summary = verify_employees(employees, pf_members, esic_members)

        _update(job, message="Building downloadable report...", progress=90)
        warnings = pf_warnings + esic_warnings
        wb = build_report(results, summary, warnings)
        report_path = os.path.join(os.path.dirname(wagesheet_path), "report.xlsx")
        wb.save(report_path)

        _update(
            job, status="done", message="Verification complete", progress=100,
            summary=summary, results=results, warnings=warnings, report_path=report_path,
        )
    except (WagesheetParseError, PfEcrParseError, EsicEcrParseError) as exc:
        _update(job, status="error", message=str(exc), progress=100)
    except Exception:
        _update(
            job, status="error", progress=100,
            message="An unexpected error occurred while processing the files. "
                    "Please confirm the files are the expected wagesheet/ECR documents and try again.",
        )
    finally:
        for path in (wagesheet_path, pf_ecr_path, esic_ecr_path):
            try:
                os.remove(path)
            except OSError:
                pass


def submit_job(wagesheet_path, pf_ecr_path, esic_ecr_path):
    job_id = uuid.uuid4().hex
    job = Job(job_id)
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run, job_id, wagesheet_path, pf_ecr_path, esic_ecr_path)
    return job_id


def purge_expired():
    now = time.time()
    with _lock:
        expired = [jid for jid, j in _jobs.items() if now - j.created_at > JOB_TTL_SECONDS]
        for jid in expired:
            job = _jobs.pop(jid)
            if job.report_path and os.path.exists(job.report_path):
                try:
                    os.remove(job.report_path)
                    os.rmdir(os.path.dirname(job.report_path))
                except OSError:
                    pass
