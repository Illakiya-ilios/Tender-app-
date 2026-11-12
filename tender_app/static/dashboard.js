// Dashboard view — read-only overview of tenders and evaluations.
// Fetches GET /api/dashboard and renders tiles + two tables. Posts nothing back.

// Escape helper: produce a safe text node value (textContent-based escaping).
function esc(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

// Date portion of an ISO timestamp ("2024-01-02T10:30:00" -> "2024-01-02").
function datePart(s) {
  if (!s) return "";
  return String(s).split("T")[0];
}

function showError(message) {
  const el = document.getElementById("dash-error");
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
}

function renderTiles(tiles) {
  tiles = tiles || {};
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val == null ? 0 : val;
  };
  set("val-total-tenders", tiles.total_tenders);
  set("val-total-evaluations", tiles.total_evaluations);
  set("val-awarded", tiles.awarded);
  set("val-scored", tiles.scored);
}

function renderTenders(tenders) {
  const body = document.getElementById("tenders-body");
  if (!body) return;
  body.innerHTML = "";
  (tenders || []).forEach((t) => {
    const tr = document.createElement("tr");

    // Files cell: PDF/BOQ links when stored urls are non-empty.
    const links = [];
    if (t.pdf_url) {
      links.push('<a href="' + esc(t.pdf_url) + '" target="_blank">PDF</a>');
    }
    if (t.boq_url) {
      links.push('<a href="' + esc(t.boq_url) + '" target="_blank">BOQ</a>');
    }
    const filesCell = links.length ? links.join(" ") : "&mdash;";

    tr.innerHTML =
      "<td>" + esc(t.name_of_work) + "</td>" +
      "<td>" + esc(t.tender_reference_no) + "</td>" +
      "<td>" + esc(t.inviting_authority) + "</td>" +
      "<td>" + esc(datePart(t.generated_at)) + "</td>" +
      '<td><span class="pill">' + esc(t.completeness == null ? 0 : t.completeness) + "%</span></td>" +
      "<td>" + filesCell + "</td>";
    body.appendChild(tr);
  });
}

function renderEvaluations(evals) {
  const body = document.getElementById("evaluations-body");
  if (!body) return;
  body.innerHTML = "";
  (evals || []).forEach((e) => {
    const tr = document.createElement("tr");

    // Best match cell.
    let bestMatch;
    if (e.none_eligible) {
      bestMatch = "No eligible bid";
    } else {
      bestMatch = e.best_match_bidder_name ? esc(e.best_match_bidder_name) : "&mdash;";
    }

    // Status badge: awarded -> green .yes, scored -> amber .partly.
    let statusCell;
    if (e.status === "awarded") {
      statusCell = '<span class="badge yes">awarded</span>';
    } else {
      statusCell = '<span class="badge partly">scored</span>';
    }

    const finalSel = e.final_selection_bidder ? esc(e.final_selection_bidder) : "&mdash;";

    const details = e.run_id
      ? '<a href="/api/eval/audit/' + esc(e.run_id) + '" target="_blank">Details</a>'
      : "&mdash;";

    tr.innerHTML =
      "<td>" + esc(e.tender_reference_no) + "</td>" +
      "<td>" + esc(datePart(e.released_at)) + "</td>" +
      "<td>" + esc(e.bidders_count == null ? 0 : e.bidders_count) + "</td>" +
      "<td>" + esc(e.complete_bids_count == null ? 0 : e.complete_bids_count) + "</td>" +
      "<td>" + bestMatch + "</td>" +
      "<td>" + statusCell + "</td>" +
      "<td>" + finalSel + "</td>" +
      "<td>" + details + "</td>";
    body.appendChild(tr);
  });
}

function toggleEmpty(empty) {
  const emptyState = document.getElementById("empty-state");
  const content = document.getElementById("content");
  if (empty) {
    if (emptyState) emptyState.hidden = false;
    if (content) content.hidden = true;
  } else {
    if (emptyState) emptyState.hidden = true;
    if (content) content.hidden = false;
  }
}

document.addEventListener("DOMContentLoaded", function () {
  fetch("/api/dashboard")
    .then((resp) => {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return resp.json();
    })
    .then((summary) => {
      summary = summary || {};
      renderTiles(summary.tiles);
      renderTenders(summary.tenders);
      renderEvaluations(summary.evaluations);
      toggleEmpty(summary.empty);
    })
    .catch(() => {
      showError("Could not load the dashboard. Please try again.");
    });
});
