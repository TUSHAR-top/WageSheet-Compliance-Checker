(() => {
  "use strict";

  const form = document.getElementById("upload-form");
  const submitBtn = document.getElementById("submit-btn");
  const errorSection = document.getElementById("error-section");
  const errorMessage = document.getElementById("error-message");
  const progressSection = document.getElementById("progress-section");
  const progressFill = document.getElementById("progress-fill");
  const progressMessage = document.getElementById("progress-message");
  const resultsSection = document.getElementById("results-section");
  const summaryCards = document.getElementById("summary-cards");
  const resultsBody = document.getElementById("results-body");
  const downloadLink = document.getElementById("download-link");
  const searchBox = document.getElementById("search-box");
  const filterSelect = document.getElementById("filter-select");
  const warningsNote = document.getElementById("warnings-note");

  const LAST_JOB_KEY = "wagesheet_ecr_last_job_id";
  let pollTimer = null;
  let allResults = [];

  function showError(message) {
    errorMessage.textContent = message;
    errorSection.hidden = false;
  }
  function clearError() {
    errorSection.hidden = true;
    errorMessage.textContent = "";
  }

  function statusClass(status) {
    return "status-" + status.replace(/\s+/g, "-");
  }

  function setProgress(pct, message) {
    progressFill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    progressMessage.textContent = message || "";
  }

  async function pollStatus(jobId) {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();
      if (!res.ok) {
        stopPolling();
        showError(data.error || "This job could not be found. Please submit again.");
        localStorage.removeItem(LAST_JOB_KEY);
        progressSection.hidden = true;
        return;
      }
      setProgress(data.progress, data.message);
      if (data.status === "done") {
        stopPolling();
        await loadResults(jobId);
      } else if (data.status === "error") {
        stopPolling();
        progressSection.hidden = true;
        showError(data.message || "Verification failed.");
      }
    } catch (err) {
      stopPolling();
      showError("Lost connection to the server while checking job status. Please retry.");
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling(jobId) {
    stopPolling();
    pollTimer = setInterval(() => pollStatus(jobId), 1500);
    pollStatus(jobId);
  }

  async function loadResults(jobId) {
    try {
      const res = await fetch(`/api/result/${jobId}`);
      const data = await res.json();
      if (!res.ok) {
        progressSection.hidden = true;
        showError(data.error || "Could not load results.");
        return;
      }
      clearError();
      progressSection.hidden = true;
      renderResults(jobId, data);
    } catch (err) {
      showError("Lost connection to the server while loading results. Please retry.");
    }
  }

  function renderSummary(summary) {
    summaryCards.innerHTML = "";
    const groups = [
      ["PF", summary.pf],
      ["ESIC", summary.esic],
    ];
    const order = ["Matched", "Name mismatch", "Amount mismatch", "Missing"];
    for (const [label, counts] of groups) {
      for (const key of order) {
        const div = document.createElement("div");
        div.className = "summary-card";
        div.innerHTML = `<span class="count">${counts[key] ?? 0}</span><span class="label">${label} · ${key}</span>`;
        summaryCards.appendChild(div);
      }
    }
  }

  function rowMatchesFilter(row, filter) {
    switch (filter) {
      case "issue":
        return row.pf.status !== "Matched" || row.esic.status !== "Matched";
      case "pf-missing": return row.pf.status === "Missing";
      case "pf-name": return row.pf.status === "Name mismatch";
      case "pf-amount": return row.pf.status === "Amount mismatch";
      case "esic-missing": return row.esic.status === "Missing";
      case "esic-name": return row.esic.status === "Name mismatch";
      case "esic-amount": return row.esic.status === "Amount mismatch";
      default: return true;
    }
  }

  function renderTable() {
    const query = searchBox.value.trim().toLowerCase();
    const filter = filterSelect.value;
    resultsBody.innerHTML = "";
    const frag = document.createDocumentFragment();

    for (const row of allResults) {
      if (filter && !rowMatchesFilter(row, filter)) continue;
      if (query) {
        const haystack = `${row.name} ${row.uan} ${row.ip_number}`.toLowerCase();
        if (!haystack.includes(query)) continue;
      }
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(row.name)}</td>
        <td>${escapeHtml(row.uan)}</td>
        <td>${escapeHtml(row.ip_number)}</td>
        <td><span class="status-pill ${statusClass(row.pf.status)}">${row.pf.status}</span></td>
        <td class="reason-cell">${escapeHtml(row.pf.reason)}</td>
        <td><span class="status-pill ${statusClass(row.esic.status)}">${row.esic.status}</span></td>
        <td class="reason-cell">${escapeHtml(row.esic.reason)}</td>
      `;
      frag.appendChild(tr);
    }
    resultsBody.appendChild(frag);
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function renderResults(jobId, data) {
    allResults = data.results || [];
    renderSummary(data.summary);
    renderTable();
    downloadLink.href = `/api/download/${jobId}`;
    if (data.warnings && data.warnings.length) {
      warningsNote.hidden = false;
      warningsNote.textContent = `${data.warnings.length} row(s) in the ECR PDFs could not be parsed and were skipped — see the report's Summary sheet for details.`;
    } else {
      warningsNote.hidden = true;
    }
    resultsSection.hidden = false;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearError();
    resultsSection.hidden = true;

    const wagesheet = document.getElementById("wagesheet").files[0];
    const pfEcr = document.getElementById("pf_ecr").files[0];
    const esicEcr = document.getElementById("esic_ecr").files[0];
    if (!wagesheet || !pfEcr || !esicEcr) {
      showError("Please attach all three files before running verification.");
      return;
    }

    const formData = new FormData();
    formData.append("wagesheet", wagesheet);
    formData.append("pf_ecr", pfEcr);
    formData.append("esic_ecr", esicEcr);

    submitBtn.disabled = true;
    submitBtn.textContent = "Uploading...";
    try {
      const res = await fetch("/api/verify", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Upload was rejected. Please check the files and try again.");
        return;
      }
      localStorage.setItem(LAST_JOB_KEY, data.job_id);
      progressSection.hidden = false;
      setProgress(0, "Queued...");
      startPolling(data.job_id);
    } catch (err) {
      showError("Could not reach the server. Confirm it is running and try again.");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Run verification";
    }
  });

  searchBox.addEventListener("input", renderTable);
  filterSelect.addEventListener("change", renderTable);

  // Resume a job left running when the page was closed/refreshed.
  const lastJobId = localStorage.getItem(LAST_JOB_KEY);
  if (lastJobId) {
    progressSection.hidden = false;
    setProgress(0, "Checking previous job...");
    startPolling(lastJobId);
  }
})();
