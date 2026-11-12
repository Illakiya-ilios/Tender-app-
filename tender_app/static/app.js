const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("user-input");
const briefBody = document.getElementById("brief-body");
const completenessEl = document.getElementById("completeness");
const generateBtn = document.getElementById("generate-btn");
const genHint = document.getElementById("gen-hint");
const architectBtn = document.getElementById("architect-btn");
const architectureEl = document.getElementById("architecture");
const notesEl = document.getElementById("notes");
const downloadsEl = document.getElementById("downloads");

const FIELD_LABELS = {
  tender_inviting_authority: "Inviting Authority",
  name_of_work: "Name of Work",
  tender_reference_no: "Reference No.",
  emd_amount: "EMD",
  estimated_value: "Estimated Value",
  contract_period: "Contract Period",
  pre_bid_datetime: "Pre-Bid Meeting",
  pre_bid_venue: "Pre-Bid Venue",
  submission_due_datetime: "Submission Due",
  bid_opening_datetime: "Bid Opening",
  contact_name: "Contact Name",
  contact_phone: "Contact Phone",
  contact_email: "Contact Email",
};

function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderBrief(brief, completeness) {
  briefBody.innerHTML = "";
  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="k">${label}</td><td>${brief[key] || "—"}</td>`;
    briefBody.appendChild(tr);
  }
  completenessEl.textContent = `${completeness}%`;

  const approved = brief.architecture_approved && (brief.architecture || []).length;
  if (approved) {
    renderArchitecture(brief.architecture);
    generateBtn.disabled = false;
    genHint.style.display = "none";
  } else {
    generateBtn.disabled = true;
    genHint.style.display = "block";
  }
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function renderArchitecture(items) {
  if (!items.length) return;
  architectureEl.innerHTML = "";
  for (const a of items) {
    const qty = Number.isInteger(a.quantity) ? a.quantity : a.quantity;
    const badge = a.source === "officer" ? "you" : "suggested";
    const div = document.createElement("div");
    div.className = "arch-item";
    div.innerHTML =
      `<div class="arch-row">
         <span class="arch-cat">${esc(a.category)}</span>
         <span class="arch-badge ${a.source}">${badge}</span>
       </div>
       <div class="arch-desc">${esc(a.description)}</div>
       <div class="arch-meta">Qty: ${esc(qty)} ${esc(a.units)}${a.mandatory ? "" : " · optional"}</div>
       ${a.rationale ? `<div class="arch-why">${esc(a.rationale)}</div>` : ""}`;
    architectureEl.appendChild(div);
  }
}

async function sendMessage(text) {
  addMessage(text, "user");
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: text }),
  });
  const data = await res.json();
  addMessage(data.reply, "agent");
  if (data.proposal && data.proposal.length) {
    renderProposalCard(data.proposal);
  }
  renderBrief(data.brief, data.completeness);
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  sendMessage(text).catch(() => addMessage("Something went wrong. Try again.", "sys"));
});

function renderProposalCard(proposal) {
  const card = document.createElement("div");
  card.className = "msg agent proposal-card";
  let rows = "";
  for (const a of proposal) {
    const badge = a.source === "officer" ? "you" : "suggested";
    rows +=
      `<div class="arch-item">
         <div class="arch-row">
           <span class="arch-cat">${esc(a.category)}</span>
           <span class="arch-badge ${a.source}">${badge}</span>
         </div>
         <div class="arch-desc">${esc(a.description)}</div>
         <div class="arch-meta">Qty: ${esc(a.quantity)} ${esc(a.units)}${a.mandatory ? "" : " · optional"}</div>
         ${a.rationale ? `<div class="arch-why">${esc(a.rationale)}</div>` : ""}
       </div>`;
  }
  const fromOfficer = proposal.every((a) => a.source === "officer");
  const title = fromOfficer ? "Your Architecture" : "Suggested Architecture";
  card.innerHTML =
    `<div class="proposal-title">${title} (${proposal.length} components)</div>
     ${rows}
     <div class="proposal-actions">
       <button class="approve-btn">Approve &amp; add to Brief</button>
     </div>`;
  messagesEl.appendChild(card);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  card.querySelector(".approve-btn").addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Approving...";
    try {
      const res = await fetch("/api/approve-architecture", { method: "POST" });
      const data = await res.json();
      if (data.error) {
        addMessage(data.error, "sys");
        e.target.disabled = false;
        e.target.textContent = "Approve & add to Brief";
      } else {
        card.classList.add("approved");
        e.target.textContent = "✓ Approved";
        addMessage(data.reply, "agent");
        renderBrief(data.brief, data.completeness);
      }
    } catch (err) {
      addMessage("Approval failed.", "sys");
      e.target.disabled = false;
      e.target.textContent = "Approve & add to Brief";
    }
  });
}

architectBtn.addEventListener("click", async () => {
  architectBtn.disabled = true;
  architectBtn.textContent = "Thinking...";
  try {
    const res = await fetch("/api/architect", { method: "POST" });
    const data = await res.json();
    if (data.error) {
      addMessage(data.error, "sys");
    } else {
      addMessage(data.reply, "agent");
      renderProposalCard(data.proposal || []);
      renderBrief(data.brief, data.completeness);
    }
  } catch (err) {
    addMessage("Could not suggest architecture.", "sys");
  } finally {
    architectBtn.disabled = false;
    architectBtn.textContent = "Suggest Architecture";
  }
});

generateBtn.addEventListener("click", async () => {
  generateBtn.disabled = true;
  generateBtn.textContent = "Generating...";
  downloadsEl.innerHTML = "";
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: notesEl.value.trim() }),
    });
    const data = await res.json();
    if (data.error) {
      addMessage(data.error, "sys");
    } else {
      renderBrief(data.brief, data.completeness);
      if (data.pdf_url)
        downloadsEl.innerHTML += `<a href="${data.pdf_url}" target="_blank">⬇ Download Tender (PDF)</a>`;
      if (data.boq_url)
        downloadsEl.innerHTML += `<a href="${data.boq_url}" target="_blank">⬇ Download BOQ (Excel)</a>`;
      if (data.pdf_error) addMessage(data.pdf_error, "sys");
      if (data.boq_error) addMessage(data.boq_error, "sys");
      if (data.pdf_url || data.boq_url) addMessage("Generation complete.", "sys");
    }
  } catch (err) {
    addMessage("Generation failed.", "sys");
  } finally {
    generateBtn.disabled = false;
    generateBtn.textContent = "Generate Tender + BOQ";
  }
});

addMessage(
  "Hello! Describe the tender you want to create. For example: " +
  "\"Cloud-based hostel management software for ACGCET Karaikudi, EMD Rs. 16,000, " +
  "submission due 20.08.2026\".",
  "agent"
);
