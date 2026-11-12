// Stage 3: Bid Evaluation UI. Vanilla JS + fetch, matching app.js conventions.

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

const errorBanner = document.getElementById("eval-error");

function showError(msg) {
  errorBanner.textContent = msg;
  errorBanner.hidden = false;
  errorBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearError() {
  errorBanner.hidden = true;
  errorBanner.textContent = "";
}

// fetch JSON helper. Throws on API error payloads ({error: ...}) so callers can
// surface the message. `opts` are passed straight to fetch.
async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  let data = null;
  try {
    data = await res.json();
  } catch (_e) {
    data = null;
  }
  if (!res.ok || (data && data.error)) {
    const msg = (data && data.error) || `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

async function postJSON(url, body) {
  return fetchJSON(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// Map a presence/status string to a badge CSS class.
function presenceClass(presence) {
  switch (presence) {
    case "Present": return "present";
    case "Missing": return "missing";
    case "Present but unreadable": return "unreadable";
    default: return "notprovided";
  }
}

function statusClass(status) {
  switch (status) {
    case "Satisfied": return "satisfied";
    case "Partly Satisfied": return "partly";
    case "Not Satisfied": return "notsat";
    default: return "none";
  }
}

function badge(text, cls) {
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------
const tabs = Array.from(document.querySelectorAll(".eval-tab"));
const panels = {
  doccheck: document.getElementById("panel-doccheck"),
  matrix: document.getElementById("panel-matrix"),
  shortlist: document.getElementById("panel-shortlist"),
};

function switchTab(name) {
  tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  Object.entries(panels).forEach(([key, el]) =>
    el.classList.toggle("active", key === name)
  );
}

tabs.forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

// ===========================================================================
// SCREEN 1: Bid Document Check
// ===========================================================================
const uploadForm = document.getElementById("bid-upload-form");
const bidderNameEl = document.getElementById("bidder-name");
const bidIdEl = document.getElementById("bid-id");
const bidFilesEl = document.getElementById("bid-files");
const registeredEl = document.getElementById("registered-bidders");
const runCheckBtn = document.getElementById("run-check-btn");
const rerunCheckBtn = document.getElementById("rerun-check-btn");
const tilesEl = document.getElementById("doccheck-tiles");
const docMatrixEl = document.getElementById("doccheck-matrix");
const releaseBtn = document.getElementById("release-btn");
const actionNeededEl = document.getElementById("action-needed");

let lastCompleteness = null; // cached completeness payload for action-needed panel

function renderRegistered(bidders) {
  registeredEl.innerHTML = "";
  if (!bidders || !bidders.length) return;
  for (const b of bidders) {
    const div = document.createElement("div");
    div.className = "registered-item";
    div.innerHTML =
      `<span class="rb-name">${esc(b.bidder_name || b.bid_id)}</span>` +
      `<span class="rb-meta">${esc(b.bid_id)} · ${b.archive_count} archive(s)</span>`;
    registeredEl.appendChild(div);
  }
}

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();
  if (!bidFilesEl.files.length) {
    showError("Choose at least one .zip file.");
    return;
  }
  const fd = new FormData();
  fd.append("bidder_name", bidderNameEl.value.trim());
  fd.append("bid_id", bidIdEl.value.trim());
  for (const f of bidFilesEl.files) fd.append("files", f);

  try {
    const data = await fetchJSON("/api/eval/bids", { method: "POST", body: fd });
    renderRegistered(data.registered_bidders);
    bidderNameEl.value = "";
    bidIdEl.value = "";
    bidFilesEl.value = "";
  } catch (err) {
    showError(err.message);
  }
});

async function runDocCheck() {
  clearError();
  runCheckBtn.disabled = true;
  rerunCheckBtn.disabled = true;
  try {
    const data = await fetchJSON("/api/eval/run", { method: "POST" });
    renderDocCheck(data);
    rerunCheckBtn.hidden = false;
  } catch (err) {
    showError(err.message);
  } finally {
    runCheckBtn.disabled = false;
    rerunCheckBtn.disabled = false;
  }
}

runCheckBtn.addEventListener("click", runDocCheck);
rerunCheckBtn.addEventListener("click", runDocCheck);

function renderTiles(summary) {
  tilesEl.innerHTML = "";
  const tiles = [
    { val: summary.required_documents, label: "Required Documents" },
    { val: summary.complete_bids, label: "Complete Bids" },
    { val: summary.missing_documents, label: "Missing Documents" },
    { val: summary.checks_run, label: "Checks Run" },
  ];
  for (const t of tiles) {
    const div = document.createElement("div");
    div.className = "tile";
    div.innerHTML =
      `<div class="tile-val">${esc(t.val)}</div>` +
      `<div class="tile-label">${esc(t.label)}</div>`;
    tilesEl.appendChild(div);
  }
}

function renderDocCheck(payload) {
  lastCompleteness = payload;
  renderTiles(payload.summary);

  const thead = docMatrixEl.querySelector("thead");
  const tbody = docMatrixEl.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  // Header: Document | bidder columns (clickable).
  const headRow = document.createElement("tr");
  headRow.innerHTML = `<th>Required Document</th>`;
  for (const bid of payload.bids) {
    const pill = bid.complete
      ? `<span class="complete-pill yes">complete</span>`
      : `<span class="complete-pill no">incomplete</span>`;
    const th = document.createElement("th");
    th.className = "col-bidder";
    th.dataset.bidId = bid.bid_id;
    th.innerHTML =
      `<div class="bidder-head">${esc(bid.bidder_name || bid.bid_id)} ${pill}</div>` +
      `<div class="bidder-sub">${esc(bid.bid_id)}</div>`;
    th.addEventListener("click", () => showActionNeeded(bid.bid_id));
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);

  // Build a quick lookup: bid_id -> {document_key -> presence}.
  const cellMap = {};
  for (const bid of payload.bids) {
    cellMap[bid.bid_id] = {};
    for (const cell of bid.cells) {
      cellMap[bid.bid_id][cell.document_key] = cell.presence;
    }
  }

  for (const type of payload.required_types) {
    const tr = document.createElement("tr");
    const label = document.createElement("td");
    label.className = "row-label";
    label.textContent = type.label;
    tr.appendChild(label);
    for (const bid of payload.bids) {
      const presence = cellMap[bid.bid_id][type.key] || "Not provided";
      const td = document.createElement("td");
      td.innerHTML = badge(presence, presenceClass(presence));
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }

  // Release button label reflects the complete count.
  const count = payload.summary.complete_bids_count || 0;
  releaseBtn.textContent = `Release ${count} Complete Bid${count === 1 ? "" : "s"} to Scoring`;
  releaseBtn.hidden = false;
  releaseBtn.disabled = count === 0;
}

function showActionNeeded(bidId) {
  if (!lastCompleteness) return;
  const bid = lastCompleteness.bids.find((b) => b.bid_id === bidId);
  if (!bid) return;
  const labels = {};
  for (const t of lastCompleteness.required_types) labels[t.key] = t.label;

  let html = `<div class="action-bidder"><h3>${esc(bid.bidder_name || bid.bid_id)}</h3>`;
  if (!bid.missing.length && !bid.unreadable.length) {
    html += `<p class="muted">No missing or unreadable documents.</p>`;
  } else {
    if (bid.missing.length) {
      html += `<p class="muted">Missing:</p><ul class="doc-list">`;
      html += bid.missing.map((k) => `<li>${esc(labels[k] || k)}</li>`).join("");
      html += `</ul>`;
    }
    if (bid.unreadable.length) {
      html += `<p class="muted">Present but unreadable:</p><ul class="doc-list">`;
      html += bid.unreadable.map((k) => `<li>${esc(labels[k] || k)}</li>`).join("");
      html += `</ul>`;
    }
  }
  html += `</div>`;
  actionNeededEl.innerHTML = html;
}

releaseBtn.addEventListener("click", async () => {
  clearError();
  releaseBtn.disabled = true;
  try {
    await postJSON("/api/eval/release", {});
    await loadMatrix();
    switchTab("matrix");
  } catch (err) {
    showError(err.message);
  } finally {
    releaseBtn.disabled = false;
  }
});

// ===========================================================================
// SCREEN 2: Bid Evaluation matrix + evidence
// ===========================================================================
const evalMatrixEl = document.getElementById("eval-matrix");
const evidencePanelEl = document.getElementById("evidence-panel");
const gotoShortlistBtn = document.getElementById("goto-shortlist-btn");

const CLASS_LABELS = {
  eligibility: "Eligibility",
  technical: "Technical",
  qualification: "Qualification",
  capability: "Capability",
};

async function loadMatrix() {
  clearError();
  try {
    const data = await fetchJSON("/api/eval/matrix");
    renderMatrix(data);
  } catch (err) {
    showError(err.message);
  }
}

function formatPrice(price) {
  if (!price || !price.available) return "price unavailable";
  const cur = price.currency || "";
  return `${cur} ${esc(price.amount)}`.trim();
}

function renderMatrix(payload) {
  const thead = evalMatrixEl.querySelector("thead");
  const tbody = evalMatrixEl.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  const bids = payload.bids;

  // Header row: Requirement | per-bidder (name, score, price, capacity badge).
  const headRow = document.createElement("tr");
  headRow.innerHTML = `<th>Requirement</th>`;
  for (const bid of bids) {
    const cap = bid.capacity && bid.capacity.capacity_qualified;
    const capBadge = badge(
      cap ? "capacity ok" : "capacity gap",
      cap ? "yes" : "no"
    );
    const th = document.createElement("th");
    th.className = "col-bidder";
    th.innerHTML =
      `<div class="bidder-head">${esc(bid.bidder_name || bid.bid_id)}</div>` +
      `<div class="bidder-sub">score ${esc(bid.weighted_score)} · ${formatPrice(bid.price)}</div>` +
      `<div class="bidder-sub">${capBadge}</div>`;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);

  // Rows grouped by requirement class.
  for (const cls of payload.req_classes) {
    // Determine the rows for this class from the first bid that has them.
    let classCells = [];
    for (const bid of bids) {
      if (bid.groups[cls] && bid.groups[cls].length) {
        classCells = bid.groups[cls];
        break;
      }
    }
    if (!classCells.length) continue;

    const clsRow = document.createElement("tr");
    clsRow.className = "class-row";
    clsRow.innerHTML = `<td colspan="${bids.length + 1}">${esc(CLASS_LABELS[cls] || cls)}</td>`;
    tbody.appendChild(clsRow);

    classCells.forEach((cell, idx) => {
      const tr = document.createElement("tr");
      const label = document.createElement("td");
      label.className = "row-label";
      label.textContent = cell.requirement_text || cell.requirement_key;
      tr.appendChild(label);

      for (const bid of bids) {
        const bidCell = (bid.groups[cls] || [])[idx];
        const td = document.createElement("td");
        if (bidCell && bidCell.status) {
          td.className = "cell-click";
          td.innerHTML = badge(bidCell.status, statusClass(bidCell.status));
          td.addEventListener("click", () =>
            loadEvidence(bid.bid_id, bidCell.requirement_key)
          );
        } else {
          td.innerHTML = badge("—", "none");
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    });
  }
}

async function loadEvidence(bidId, requirementKey) {
  clearError();
  evidencePanelEl.innerHTML = `<p class="muted">Loading evidence…</p>`;
  try {
    const url = `/api/eval/evidence?bid_id=${encodeURIComponent(bidId)}` +
      `&requirement_key=${encodeURIComponent(requirementKey)}`;
    const data = await fetchJSON(url);
    renderEvidence(data);
  } catch (err) {
    evidencePanelEl.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

function renderEvidence(ev) {
  let html = `<div class="evidence-status">${badge(ev.status, statusClass(ev.status))}</div>`;
  if (ev.reason) {
    html += `<div class="evidence-reason">${esc(ev.reason)}</div>`;
  }
  if (ev.citations && ev.citations.length) {
    for (const c of ev.citations) {
      html += `<div class="citation">` +
        `<div class="cit-meta">${esc(c.filename)} · page ${esc(c.page)}</div>` +
        `<div class="cit-quote">“${esc(c.quote)}”</div>`;
      if (c.document_url) {
        html += `<a href="${esc(c.document_url)}" target="_blank" rel="noopener">Open Document</a>`;
      }
      html += `</div>`;
    }
  } else {
    html += `<p class="muted">No citations.</p>`;
  }
  evidencePanelEl.innerHTML = html;
}

gotoShortlistBtn.addEventListener("click", async () => {
  await loadShortlist();
  switchTab("shortlist");
});

// ===========================================================================
// SCREEN 3: Best Match Recommendation
// ===========================================================================
const noneEligibleBanner = document.getElementById("none-eligible-banner");
const bestMatchCard = document.getElementById("best-match-card");
const rankedListEl = document.getElementById("ranked-list");
const whyLowerCard = document.getElementById("why-lower-card");
const whyLowerEl = document.getElementById("why-lower");
const selectionBanner = document.getElementById("selection-banner");

const overrideForm = document.getElementById("override-form");
const ovTarget = document.getElementById("ov-target");
const ovBidId = document.getElementById("ov-bid-id");
const ovItemKey = document.getElementById("ov-item-key");
const ovNewValue = document.getElementById("ov-new-value");
const ovJustification = document.getElementById("ov-justification");
const ovSubmit = document.getElementById("ov-submit");

function fmtPriceNum(price) {
  if (price == null) return "price unavailable";
  return String(price);
}

function sortedEntries(entries) {
  // Sort by rank ascending; unranked (null) last.
  return entries.slice().sort((a, b) => {
    if (a.rank == null && b.rank == null) return 0;
    if (a.rank == null) return 1;
    if (b.rank == null) return -1;
    return a.rank - b.rank;
  });
}

async function loadShortlist() {
  clearError();
  try {
    const data = await fetchJSON("/api/eval/shortlist");
    renderShortlist(data);
  } catch (err) {
    showError(err.message);
  }
}

function renderShortlist(payload) {
  const entries = payload.entries || [];
  const best = entries.find((e) => e.bid_id === payload.best_match_bid_id);

  // None-eligible banner.
  if (payload.none_eligible) {
    let html = `<strong>No bid meets all requirements.</strong><ul>`;
    for (const e of entries) {
      const reasons = (e.blocking_reasons || []).map((r) => esc(r)).join("; ");
      html += `<li>${esc(e.bidder_name || e.bid_id)}: ${reasons || "not eligible"}</li>`;
    }
    html += `</ul>`;
    noneEligibleBanner.innerHTML = html;
    noneEligibleBanner.hidden = false;
  } else {
    noneEligibleBanner.hidden = true;
  }

  // Best-match card.
  if (best) {
    let html = `<span class="best-match-tag">Best Match</span>`;
    html += `<div class="bidder-head">${esc(best.bidder_name || best.bid_id)}</div>`;
    html += `<div class="rank-meta">rank ${best.rank != null ? esc(best.rank) : "—"} · ` +
      `score ${esc(best.weighted_score)} · ${fmtPriceNum(best.price)}</div>`;
    html += `<div class="sgr-cols">`;
    html += sgrColumn("strengths", "Strengths", best.strengths);
    html += sgrColumn("gaps", "Gaps", best.gaps);
    html += sgrColumn("risks", "Risks", best.risks);
    html += `</div>`;
    if (best.reasons && best.reasons.length) {
      html += `<ul class="reasons-list">` +
        best.reasons.map((r) => `<li>${esc(r)}</li>`).join("") + `</ul>`;
    }
    html += `<div style="margin-top:12px;">` +
      `<button class="approve-sel-btn" data-bid="${esc(best.bid_id)}">Approve Selection</button></div>`;
    bestMatchCard.innerHTML = html;
    bestMatchCard.hidden = false;
  } else {
    bestMatchCard.hidden = true;
  }

  // Ranked list.
  rankedListEl.innerHTML = "";
  for (const e of sortedEntries(entries)) {
    const div = document.createElement("div");
    div.className = "ranked-item";
    const eligibleBadge = badge(
      e.eligible ? "eligible" : "not eligible",
      e.eligible ? "yes" : "no"
    );
    let actionHtml = "";
    if (e.eligible) {
      actionHtml = `<button class="approve-sel-btn" data-bid="${esc(e.bid_id)}">Approve</button>`;
    }
    div.innerHTML =
      `<div class="rank-num">${e.rank != null ? esc(e.rank) : "—"}</div>` +
      `<div class="rank-body">` +
      `<div class="rank-name">${esc(e.bidder_name || e.bid_id)} ${eligibleBadge}</div>` +
      `<div class="rank-meta">score ${esc(e.weighted_score)} · ${fmtPriceNum(e.price)}</div>` +
      `</div>` + actionHtml;
    rankedListEl.appendChild(div);
  }

  // Why others ranked lower.
  const others = entries.filter((e) => e.bid_id !== payload.best_match_bid_id);
  if (others.length) {
    let html = "";
    for (const e of others) {
      const list = (e.blocking_reasons && e.blocking_reasons.length)
        ? e.blocking_reasons
        : e.reasons || [];
      if (!list.length) continue;
      html += `<div class="why-item"><div class="why-name">${esc(e.bidder_name || e.bid_id)}</div>`;
      html += `<ul>` + list.map((r) => `<li>${esc(r)}</li>`).join("") + `</ul></div>`;
    }
    if (html) {
      whyLowerEl.innerHTML = html;
      whyLowerCard.hidden = false;
    } else {
      whyLowerCard.hidden = true;
    }
  } else {
    whyLowerCard.hidden = true;
  }

  // Final selection banner.
  if (payload.final_selection) {
    renderSelection(payload.final_selection);
  }

  // Wire approve buttons (delegation after render).
  bestMatchCard.querySelectorAll(".approve-sel-btn").forEach((btn) =>
    btn.addEventListener("click", () => approveSelection(btn.dataset.bid))
  );
  rankedListEl.querySelectorAll(".approve-sel-btn").forEach((btn) =>
    btn.addEventListener("click", () => approveSelection(btn.dataset.bid))
  );
}

function sgrColumn(cls, title, items) {
  const list = items && items.length
    ? items.map((i) => `<li>${esc(i)}</li>`).join("")
    : `<li class="muted">none</li>`;
  return `<div class="sgr-col ${cls}"><h4>${esc(title)}</h4><ul>${list}</ul></div>`;
}

function renderSelection(sel) {
  selectionBanner.innerHTML =
    `<strong>Selection recorded:</strong> ${esc(sel.bid_id)}` +
    (sel.justification ? ` — ${esc(sel.justification)}` : "") +
    (sel.timestamp ? ` <span class="muted">(${esc(sel.timestamp)})</span>` : "");
  selectionBanner.hidden = false;
}

async function approveSelection(bidId) {
  clearError();
  const justification = prompt("Justification for selecting this bid (optional):", "") || "";
  try {
    const data = await postJSON("/api/eval/select", {
      bid_id: bidId,
      justification: justification,
    });
    if (data.final_selection) renderSelection(data.final_selection);
  } catch (err) {
    showError(err.message);
  }
}

// Override form: disable submit until justification is non-empty.
function syncOverrideSubmit() {
  ovSubmit.disabled = !ovJustification.value.trim();
}
ovJustification.addEventListener("input", syncOverrideSubmit);

overrideForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();
  if (!ovJustification.value.trim()) {
    showError("A justification is required for an override.");
    return;
  }
  ovSubmit.disabled = true;
  try {
    await postJSON("/api/eval/override", {
      target: ovTarget.value,
      bid_id: ovBidId.value.trim(),
      item_key: ovItemKey.value.trim(),
      new_value: ovNewValue.value.trim(),
      justification: ovJustification.value.trim(),
    });
    // Reload matrix + shortlist after an override.
    await loadMatrix();
    await loadShortlist();
    ovJustification.value = "";
  } catch (err) {
    showError(err.message);
  } finally {
    syncOverrideSubmit();
  }
});
