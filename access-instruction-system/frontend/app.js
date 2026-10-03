const API_URL = "http://127.0.0.1:8000";

// --- GLOBAL STATE ---
let currentAddressId = null;
let currentNoteId = null;
let chartsInitialized = false;
let chartInstances = {};
let currentEmissionsMode = "fixed";
let multiSeedResults = null; // loaded from /evaluation/multi_seed_results.json if available

// --- UTILITY FUNCTIONS ---
function formatRelativeTime(dateString) {
    if (!dateString) return "Never confirmed";
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays <= 0) return "confirmed today";
    if (diffDays === 1) return "confirmed yesterday";
    return `confirmed ${diffDays} days ago`;
}

function showBanner(el, msg, type = "info") {
    el.textContent = msg;
    el.className = `feedback-banner ${type}`;
    el.classList.remove("hidden");
}

// --- TAB SWITCHING ---
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const targetTab = tab.getAttribute('data-tab');
        document.getElementById(targetTab).classList.add('active');
        if (targetTab === 'explorer-view') loadAddressExplorer();
        else if (targetTab === 'ops-view') {
            if (!chartsInitialized) initOpsCharts();
            loadAreaBreakdown();
            loadDriverLeaderboard();
        }
    });
});

// ==========================================
// 1. DRIVER VIEW LOGIC
// ==========================================
const dispatchBtn = document.getElementById('dispatch-btn');
const addressInput = document.getElementById('address-id');
const driverSelect = document.getElementById('driver-select');
const slotSelect = document.getElementById('slot-select');
const resultBox = document.getElementById('dispatch-result');
const driverHumanAddress = document.getElementById('driver-human-address');
const driverAddrIdBadge = document.getElementById('driver-addr-id-badge');
const driverAreaBadge = document.getElementById('driver-area-badge');
const driverSlaIndicator = document.getElementById('driver-sla-indicator');
const confIndicator = document.getElementById('confidence-indicator');
const confLabel = document.getElementById('confidence-label');
const confBadge = document.getElementById('confidence-score-badge');
const relativeTimeBadge = document.getElementById('relative-time-badge');
const instText = document.getElementById('instruction-text');
const sourceBadge = document.getElementById('source-badge');
const feedbackBanner = document.getElementById('feedback-banner');
const inlineNoteBox = document.getElementById('inline-note-container');
const newNoteInput = document.getElementById('new-note-input');
const submitInlineNoteBtn = document.getElementById('submit-inline-note-btn');
const notifyContainer = document.getElementById('notify-container');
const sendNotifyBtn = document.getElementById('send-notify-btn');
const notifyRecipientInput = document.getElementById('notify-recipient');
const btnSuccess = document.getElementById('log-success-btn');
const btnFail = document.getElementById('log-fail-btn');

async function initQuickSampleAddresses() {
    const container = document.getElementById('quick-address-chips');
    if (!container) return;
    try {
        const resp = await fetch(`${API_URL}/explorer?sort_by=most_attempts`);
        if (!resp.ok) return;
        const items = await resp.json();
        const samples = items.slice(0, 4);
        container.innerHTML = samples.map(item => {
            const shortName = item.raw_text.split(',')[0] + ' (' + item.area + ')';
            return `<button class="sample-chip" data-id="${item.address_id}" title="${item.raw_text}">${shortName}</button>`;
        }).join('');

        container.querySelectorAll('.sample-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const aid = chip.getAttribute('data-id');
                addressInput.value = aid;
                dispatchBtn.click();
            });
        });
    } catch(e) {
        console.error("Could not load sample addresses:", e);
    }
}

dispatchBtn.addEventListener('click', async () => {
    const addressId = addressInput.value.trim();
    if (!addressId) return alert("Enter an address ID");
    try {
        const response = await fetch(`${API_URL}/dispatch/${addressId}`);
        if (!response.ok) {
            const err = await response.json();
            return alert(`Error: ${err.detail}`);
        }
        const data = await response.json();
        currentAddressId = addressId;
        currentNoteId = data.note ? data.note.note_id : null;
        resultBox.classList.remove('hidden');
        feedbackBanner.classList.add('hidden');
        inlineNoteBox.classList.add('hidden');
        notifyContainer.classList.add('hidden');

        // Render human-readable address & metadata
        if (driverHumanAddress) driverHumanAddress.textContent = data.raw_text || data.address_id;
        if (driverAddrIdBadge) driverAddrIdBadge.textContent = data.address_id;
        if (driverSlaIndicator && slotSelect) driverSlaIndicator.textContent = `${slotSelect.value} (Scheduled)`;

        confLabel.textContent = data.confidence_label;
        if (data.note) {
            instText.textContent = data.note.instruction_text;
            const scorePercent = Math.round(data.confidence_score * 100);
            confBadge.textContent = `${scorePercent}%`;
            confBadge.style.display = 'block';
            relativeTimeBadge.textContent = formatRelativeTime(data.note.last_confirmed_at);
            sourceBadge.textContent = data.note.source;
            sourceBadge.className = 'source-tag ' + (data.note.source === 'CUSTOMER_CONFIRMED' ? 'customer' : 'driver');
            confIndicator.className = 'confidence-indicator';
            if (data.confidence_score >= 0.7) confIndicator.classList.add('high');
            else if (data.confidence_score >= 0.4) confIndicator.classList.add('medium');
            else confIndicator.classList.add('low');
        } else {
            instText.textContent = "No verified access note for this address. Proceed as a standard delivery.";
            confBadge.style.display = 'none';
            relativeTimeBadge.textContent = "No history on file";
            sourceBadge.textContent = "COLD_START";
            sourceBadge.className = 'source-tag driver';
            confIndicator.className = 'confidence-indicator low';
        }
    } catch (err) {
        console.error(err);
        alert("Failed to fetch dispatch data. Ensure uvicorn backend is running!");
    }
});

btnSuccess.addEventListener('click', async () => {
    if (!currentAddressId) return;
    const activeDriver = driverSelect ? driverSelect.value : 'R. Suresh';
    const activeSlot = slotSelect ? slotSelect.value : '10:00-13:00 slot';
    try {
        await fetch(`${API_URL}/attempts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address_id: currentAddressId,
                outcome: 'SUCCESS',
                failure_reason: 'NONE',
                driver_id: activeDriver,
                promised_slot: activeSlot,
                is_within_sla: true,
                used_note_id: currentNoteId
            })
        });
        if (!currentNoteId) {
            inlineNoteBox.classList.remove('hidden');
            showBanner(feedbackBanner, `✓ Success logged by ${activeDriver}! Add an access note below for the next driver.`, "success");
        } else {
            showBanner(feedbackBanner, `✓ Attempt logged as SUCCESS by ${activeDriver}. Confidence updated!`, "success");
            notifyContainer.classList.remove('hidden');
        }
    } catch (err) { console.error(err); }
});

submitInlineNoteBtn.addEventListener('click', async () => {
    const text = newNoteInput.value.trim();
    if (!text) return alert("Enter instruction text");
    if (text.length < 5) return alert("Instruction text must be at least 5 characters");
    try {
        const resp = await fetch(`${API_URL}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address_id: currentAddressId, instruction_text: text, source: "DRIVER_LOGGED" })
        });
        if (!resp.ok) {
            const err = await resp.json();
            return alert(`Validation error: ${JSON.stringify(err.detail)}`);
        }
        const note = await resp.json();
        currentNoteId = note.note_id;
        showBanner(feedbackBanner, "✓ Access note saved! Next driver will receive this note.", "success");
        inlineNoteBox.classList.add('hidden');
        notifyContainer.classList.remove('hidden');
        newNoteInput.value = '';
    } catch (err) { console.error(err); }
});

sendNotifyBtn.addEventListener('click', async () => {
    if (!currentAddressId || !currentNoteId) return;
    const recipient = notifyRecipientInput.value.trim() || null;
    try {
        const resp = await fetch(`${API_URL}/notify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address_id: currentAddressId, note_id: currentNoteId, recipient })
        });
        const data = await resp.json();
        showBanner(feedbackBanner, `📱 Notification: [${data.mode.toUpperCase()}] ${data.message}`, "info");
        notifyContainer.classList.add('hidden');
    } catch (err) { console.error(err); }
});

btnFail.addEventListener('click', async () => {
    if (!currentAddressId) return;
    const activeDriver = driverSelect ? driverSelect.value : 'R. Suresh';
    const activeSlot = slotSelect ? slotSelect.value : '10:00-13:00 slot';
    try {
        await fetch(`${API_URL}/attempts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address_id: currentAddressId,
                outcome: 'FAILED',
                failure_reason: 'NO_ACCESS',
                driver_id: activeDriver,
                promised_slot: activeSlot,
                is_within_sla: true,
                used_note_id: currentNoteId
            })
        });
        if (currentNoteId) {
            showBanner(feedbackBanner, `⚠ Failure logged by ${activeDriver} — note may be outdated. Confidence reduced.`, "warning");
        } else {
            showBanner(feedbackBanner, `Attempt logged as FAILED by ${activeDriver} (cold start).`, "warning");
        }
    } catch (err) { console.error(err); }
});

// ==========================================
// 2. CUSTOMER CONFIRMATION PORTAL LOGIC
// ==========================================
const custLoadBtn = document.getElementById('cust-load-btn');
const custAddressInput = document.getElementById('cust-address-id');
const custPortalBox = document.getElementById('cust-portal-box');
const custCurrentNote = document.getElementById('cust-current-note');
const custSourceBadge = document.getElementById('cust-source-badge');
const custConfirmBtn = document.getElementById('cust-confirm-btn');
const custCorrectToggleBtn = document.getElementById('cust-correct-toggle-btn');
const custCorrectionBox = document.getElementById('cust-correction-box');
const custCorrectionInput = document.getElementById('cust-correction-input');
const custSubmitCorrectionBtn = document.getElementById('cust-submit-correction-btn');
const custStatusBanner = document.getElementById('cust-status-banner');

let custNoteObj = null;

custLoadBtn.addEventListener('click', async () => {
    const addrId = custAddressInput.value.trim();
    if (!addrId) return alert("Enter address ID");
    try {
        const resp = await fetch(`${API_URL}/dispatch/${addrId}`);
        const data = await resp.json();
        custPortalBox.classList.remove('hidden');
        custCorrectionBox.classList.add('hidden');
        custStatusBanner.classList.add('hidden');
        if (data.note) {
            custNoteObj = data.note;
            custCurrentNote.textContent = `"${data.note.instruction_text}"`;
            custSourceBadge.textContent = data.note.source === 'CUSTOMER_CONFIRMED' ? 'Customer-verified' : 'Driver-logged';
            custSourceBadge.className = 'source-tag ' + (data.note.source === 'CUSTOMER_CONFIRMED' ? 'customer' : 'driver');
            custConfirmBtn.classList.remove('hidden');
        } else {
            custNoteObj = null;
            custCurrentNote.textContent = "No existing note on file for your address. Please suggest access instructions below!";
            custSourceBadge.textContent = "Unconfirmed by customer";
            custSourceBadge.className = 'source-tag driver';
            custConfirmBtn.classList.add('hidden');
        }
    } catch (err) { console.error(err); }
});

custConfirmBtn.addEventListener('click', async () => {
    if (!custNoteObj) return;
    try {
        const resp = await fetch(`${API_URL}/notes/${custNoteObj.note_id}/confirm?source=CUSTOMER_CONFIRMED`, { method: 'POST' });
        if (resp.status === 429) {
            showBanner(custStatusBanner, "⚠ Confirmation rate limit reached. Please wait before confirming again.", "warning");
            return;
        }
        showBanner(custStatusBanner, "✓ Thank you! You have verified this instruction (confidence weight boosted by +3).", "success");
    } catch (err) { console.error(err); }
});

custCorrectToggleBtn.addEventListener('click', () => custCorrectionBox.classList.toggle('hidden'));

custSubmitCorrectionBtn.addEventListener('click', async () => {
    const text = custCorrectionInput.value.trim();
    const addrId = custAddressInput.value.trim();
    if (!text || !addrId) return alert("Enter correction text");
    if (text.length < 5) return alert("Correction text too short — minimum 5 characters");
    try {
        const resp = await fetch(`${API_URL}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address_id: addrId, instruction_text: text, source: "CUSTOMER_CONFIRMED" })
        });
        if (!resp.ok) {
            const err = await resp.json();
            return alert(`Error: ${JSON.stringify(err.detail)}`);
        }
        showBanner(custStatusBanner, "✓ Customer correction submitted! Stored with high initial confidence weighting (Customer-verified).", "success");
        custCorrectionBox.classList.add('hidden');
        custCorrectionInput.value = '';
    } catch (err) { console.error(err); }
});

// ==========================================
// 3. ADDRESS NOTES EXPLORER LOGIC
// ==========================================
const explorerSearch = document.getElementById('explorer-search');
const explorerSort = document.getElementById('explorer-sort');
const explorerRefreshBtn = document.getElementById('explorer-refresh-btn');
const explorerTableBody = document.getElementById('explorer-table-body');
const auditTrailContainer = document.getElementById('audit-trail-container');
const auditAddressId = document.getElementById('audit-address-id');
const auditAddressText = document.getElementById('audit-address-text');
const auditNotesList = document.getElementById('audit-notes-list');
const auditAttemptsList = document.getElementById('audit-attempts-list');
const closeAuditBtn = document.getElementById('close-audit-btn');
const dupReviewPanel = document.getElementById('duplicate-review-panel');
const closeDupPanelBtn = document.getElementById('close-dup-panel-btn');
const dupMergeBtn = document.getElementById('dup-merge-btn');
const dupSeparateBtn = document.getElementById('dup-separate-btn');
const dupDecisionBanner = document.getElementById('dup-decision-banner');

async function loadAddressExplorer() {
    const search = explorerSearch.value.trim();
    const sort = explorerSort.value;
    explorerTableBody.innerHTML = `<tr><td colspan="8">Loading address registry...</td></tr>`;
    try {
        const resp = await fetch(`${API_URL}/explorer?search=${encodeURIComponent(search)}&sort_by=${sort}`);
        const items = await resp.json();
        if (items.length === 0) {
            explorerTableBody.innerHTML = `<tr><td colspan="8">No matching addresses found.</td></tr>`;
            return;
        }
        explorerTableBody.innerHTML = items.map(item => {
            const dupBadge = item.possible_duplicate_of
                ? `<span class="dup-flag" onclick="openDupReview('${item.address_id}', '${item.possible_duplicate_of}')" title="Possible duplicate — click to review">⚠ Dup?</span>`
                : '';
            const confClass = item.confidence_score >= 0.7 ? 'customer' : (item.confidence_score >= 0.4 ? 'driver' : '');
            return `
            <tr>
                <td>
                    <div style="font-weight:600; color:var(--text-main); font-size:0.92rem; line-height:1.35;">${item.raw_text}</div>
                    <div style="font-size:0.75rem; color:var(--text-muted); margin-top:3px;">
                        <span class="sub-badge" style="font-family:monospace; background:rgba(255,255,255,0.06);">${item.address_id}</span>
                        ${dupBadge}
                    </div>
                </td>
                <td><span class="source-tag driver">${item.area}</span></td>
                <td><span class="source-tag ${confClass}">${item.confidence_label}</span></td>
                <td><strong>${Math.round(item.confidence_score * 100)}%</strong></td>
                <td>${item.confirmation_count} / <span style="color:var(--danger)">${item.contradiction_count}</span></td>
                <td>${item.total_attempts}</td>
                <td>${item.sources.map(s => `<span class="source-tag ${s === 'CUSTOMER_CONFIRMED' ? 'customer' : 'driver'}">${s}</span>`).join(' ')}</td>
                <td><button class="primary-btn" onclick="openAuditTrail('${item.address_id}')" style="padding:0.3rem 0.7rem; font-size:0.8rem;">Audit Trail</button></td>
            </tr>`;
        }).join('');
    } catch (err) {
        console.error(err);
        explorerTableBody.innerHTML = `<tr><td colspan="8">Failed to load explorer data.</td></tr>`;
    }
}

explorerRefreshBtn.addEventListener('click', loadAddressExplorer);
explorerSort.addEventListener('change', loadAddressExplorer);
explorerSearch.addEventListener('keyup', e => { if (e.key === 'Enter') loadAddressExplorer(); });

async function openAuditTrail(addressId) {
    try {
        const resp = await fetch(`${API_URL}/history/${addressId}`);
        const data = await resp.json();
        auditAddressId.textContent = data.address_id;
        auditAddressText.textContent = `${data.raw_text} (${data.area})`;
        auditNotesList.innerHTML = data.notes.length === 0 ? '<div class="audit-item">No notes logged</div>' :
            data.notes.map(n => `
                <div class="audit-item">
                    <strong>Note #${n.note_id}:</strong> "${n.instruction_text}"
                    <br><span class="source-tag ${n.source === 'CUSTOMER_CONFIRMED' ? 'customer' : 'driver'}">${n.source}</span>
                    <span>Confirms: ${n.confirmation_count} | Contradicts: ${n.contradiction_count}</span>
                    <br><small style="color:var(--text-muted)">Created: ${new Date(n.created_at).toLocaleString()}</small>
                </div>`).join('');
        auditAttemptsList.innerHTML = data.attempts.length === 0 ? '<div class="audit-item">No delivery attempts recorded</div>' :
            data.attempts.map(a => `
                <div class="audit-item">
                    <strong>Attempt #${a.attempt_id}:</strong>
                    <span style="color:${a.outcome === 'SUCCESS' ? 'var(--success)' : 'var(--danger)'}">${a.outcome}</span>
                    <br><small>Driver: ${a.driver_id} | Used Note: ${a.used_note_id || 'None'}</small>
                    <br><small style="color:var(--text-muted)">${new Date(a.timestamp).toLocaleString()}</small>
                </div>`).join('');
        auditTrailContainer.classList.remove('hidden');
        auditTrailContainer.scrollIntoView({ behavior: 'smooth' });
    } catch (err) { console.error(err); }
}

closeAuditBtn.addEventListener('click', () => auditTrailContainer.classList.add('hidden'));

// --- Duplicate review panel ---
async function openDupReview(addrIdA, addrIdB) {
    dupReviewPanel.classList.remove('hidden');
    dupReviewPanel.scrollIntoView({ behavior: 'smooth' });
    dupDecisionBanner.classList.add('hidden');
    document.getElementById('dup-addr-id-a').value = addrIdA;
    document.getElementById('dup-addr-id-b').value = addrIdB;

    // Find the log_id for this pair
    try {
        const flagResp = await fetch(`${API_URL}/duplicates/flag?pending_only=true`);
        const flags = await flagResp.json();
        const pair = flags.find(f =>
            (f.addr_id_a === addrIdA && f.addr_id_b === addrIdB) ||
            (f.addr_id_a === addrIdB && f.addr_id_b === addrIdA)
        );
        if (!pair) {
            document.getElementById('dup-detail-a').innerHTML = `<div class="audit-item">No pending flag found for this pair.</div>`;
            return;
        }
        document.getElementById('dup-current-log-id').value = pair.log_id;

        const [histA, histB] = await Promise.all([
            fetch(`${API_URL}/history/${addrIdA}`).then(r => r.json()),
            fetch(`${API_URL}/history/${addrIdB}`).then(r => r.json())
        ]);

        const renderHistory = (hist) => {
            const noteHtml = hist.notes.length === 0 ? '<em>No notes</em>' :
                hist.notes.map(n => `<div class="audit-item">
                    "${n.instruction_text}" 
                    <span class="source-tag ${n.source === 'CUSTOMER_CONFIRMED' ? 'customer' : 'driver'}">${n.source}</span>
                    <br><small>Conf: ${n.confirmation_count} / Contra: ${n.contradiction_count}</small>
                </div>`).join('');
            return `
                <div class="audit-item"><strong>${hist.address_id}</strong><br><em>${hist.raw_text}</em></div>
                <h5>Notes:</h5>${noteHtml}
                <h5>Attempts: ${hist.attempts.length}</h5>
                <small style="color:var(--text-muted)">Similarity: ${(pair.similarity_score * 100).toFixed(1)}%</small>`;
        };

        document.getElementById('dup-detail-a').innerHTML = renderHistory(histA);
        document.getElementById('dup-detail-b').innerHTML = renderHistory(histB);
    } catch (err) { console.error(err); }
}

closeDupPanelBtn.addEventListener('click', () => dupReviewPanel.classList.add('hidden'));

dupSeparateBtn.addEventListener('click', async () => {
    const logId = document.getElementById('dup-current-log-id').value;
    const managerId = document.getElementById('dup-manager-id').value.trim();
    if (!logId) return alert("No duplicate pair loaded");
    if (!managerId) return alert("Enter Ops Manager ID before deciding");
    try {
        const resp = await fetch(`${API_URL}/duplicates/${logId}/decide`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ decision: 'KEPT_SEPARATE', decided_by: managerId })
        });
        if (resp.status === 409) {
            showBanner(dupDecisionBanner, "⚠ Decision already recorded for this pair.", "warning");
            return;
        }
        showBanner(dupDecisionBanner, "✓ Decision logged: KEPT SEPARATE permanently. Pair will not re-flag.", "success");
        loadAddressExplorer();
    } catch (err) { console.error(err); }
});

dupMergeBtn.addEventListener('click', async () => {
    const logId = document.getElementById('dup-current-log-id').value;
    const managerId = document.getElementById('dup-manager-id').value.trim();
    const addrIdA = document.getElementById('dup-addr-id-a').value;
    if (!logId) return alert("No duplicate pair loaded");
    if (!managerId) return alert("Enter Ops Manager ID before deciding");
    const confirmed = confirm(`Merge: Archive second address under "${addrIdA}" as canonical?\nThis action is logged and auditable but requires DB fix to reverse. Confirm?`);
    if (!confirmed) return;
    try {
        const resp = await fetch(`${API_URL}/duplicates/${logId}/decide`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ decision: 'MERGED', decided_by: managerId, canonical_id: addrIdA })
        });
        if (resp.status === 409) {
            showBanner(dupDecisionBanner, "⚠ Decision already recorded for this pair.", "warning");
            return;
        }
        showBanner(dupDecisionBanner, `✓ MERGED: Second address archived under ${addrIdA}. Note history preserved.`, "success");
        loadAddressExplorer();
    } catch (err) { console.error(err); }
});

// ==========================================
// 4. OPS DASHBOARD & CHART.JS LOGIC
// ==========================================
const DARK_BG = '#0f172a';
const GRID_C = 'rgba(255,255,255,0.07)';
const TEXT_C = '#94a3b8';
const BASE_C = '#ef4444';
const PROTO_C = '#10b981';

// Fallback data (single-run Review 1 numbers) — overridden if multi_seed_results.json loads
let dashData = {
    fixed: {
        baseline: { rfr: 51.3, rfr_ci: 2.0, rel: 56.7, rel_ci: 1.5, cost: 70.55, cost_ci: 2.0, emi: 420.0, emi_ci: 0.0, rto: 7.7, rto_ci: 0.5 },
        prototype: { rfr: 36.3, rfr_ci: 2.5, rel: 71.4, rel_ci: 1.8, cost: 56.02, cost_ci: 2.5, emi: 420.0, emi_ci: 0.0, rto: 6.5, rto_ci: 0.6 }
    },
    responsive: {
        baseline: { emi: 420.0, emi_ci: 5.0 },
        prototype: { emi: 378.0, emi_ci: 8.0 }
    },
    calibration: { high: 88.5, medium: 54.2, low: 36.1 }
};

async function tryLoadMultiSeedResults() {
    try {
        const resp = await fetch('/evaluation/multi_seed_results.json');
        if (!resp.ok) return;
        const raw = await resp.json();

        const fx = raw.fixed_volume;
        const rv = raw.responsive_volume;

        const pct = (key, src) => (src[key]?.mean ?? 0) * 100;
        const ci = (key, src) => ((src[key]?.ci_upper ?? 0) - (src[key]?.ci_lower ?? 0)) / 2 * 100;

        dashData.fixed.baseline.rfr = pct('repeat_failure_rate', fx.baseline);
        dashData.fixed.baseline.rfr_ci = ci('repeat_failure_rate', fx.baseline);
        dashData.fixed.baseline.rel = pct('reliability', fx.baseline);
        dashData.fixed.baseline.rel_ci = ci('reliability', fx.baseline);
        dashData.fixed.baseline.cost = fx.baseline.cost_per_success?.mean ?? 70.55;
        dashData.fixed.baseline.cost_ci = ((fx.baseline.cost_per_success?.ci_upper ?? 0) - (fx.baseline.cost_per_success?.ci_lower ?? 0)) / 2;
        dashData.fixed.baseline.emi = fx.baseline.emissions_kg?.mean ?? 420.0;
        dashData.fixed.baseline.rto = pct('rto_rate', fx.baseline);
        dashData.fixed.baseline.rto_ci = ci('rto_rate', fx.baseline);

        dashData.fixed.prototype.rfr = pct('repeat_failure_rate', fx.prototype);
        dashData.fixed.prototype.rfr_ci = ci('repeat_failure_rate', fx.prototype);
        dashData.fixed.prototype.rel = pct('reliability', fx.prototype);
        dashData.fixed.prototype.rel_ci = ci('reliability', fx.prototype);
        dashData.fixed.prototype.cost = fx.prototype.cost_per_success?.mean ?? 56.02;
        dashData.fixed.prototype.cost_ci = ((fx.prototype.cost_per_success?.ci_upper ?? 0) - (fx.prototype.cost_per_success?.ci_lower ?? 0)) / 2;
        dashData.fixed.prototype.emi = fx.prototype.emissions_kg?.mean ?? 420.0;
        dashData.fixed.prototype.rto = pct('rto_rate', fx.prototype);
        dashData.fixed.prototype.rto_ci = ci('rto_rate', fx.prototype);

        dashData.responsive.baseline.emi = rv.baseline.emissions_kg?.mean ?? 420.0;
        dashData.responsive.baseline.emi_ci = ((rv.baseline.emissions_kg?.ci_upper ?? 0) - (rv.baseline.emissions_kg?.ci_lower ?? 0)) / 2;
        dashData.responsive.prototype.emi = rv.prototype.emissions_kg?.mean ?? 378.0;
        dashData.responsive.prototype.emi_ci = ((rv.prototype.emissions_kg?.ci_upper ?? 0) - (rv.prototype.emissions_kg?.ci_lower ?? 0)) / 2;

        const cal = fx.calibration_prototype;
        if (cal?.high?.observed_success_rate != null) dashData.calibration.high = cal.high.observed_success_rate * 100;
        if (cal?.medium?.observed_success_rate != null) dashData.calibration.medium = cal.medium.observed_success_rate * 100;
        if (cal?.low?.observed_success_rate != null) dashData.calibration.low = cal.low.observed_success_rate * 100;

        dashData.num_seeds = raw.num_seeds || 5;
        updateStripFromData();
        updateCalibrationPanel();
        console.log("Multi-seed results loaded from evaluation/multi_seed_results.json");
    } catch (e) {
        console.warn("Could not load multi_seed_results.json — using fallback data.", e);
    }
}

function updateStripFromData() {
    const b = dashData.fixed.baseline;
    const p = dashData.fixed.prototype;
    const methodEl = document.querySelector('#multi-seed-strip .strip-item .strip-value');
    if (methodEl && dashData.num_seeds) {
        methodEl.textContent = `${dashData.num_seeds} seeds evaluated across both fixed & responsive arms. 95% CI = mean ± 1.96·(SD/√n). Documented in evaluation_report.md.`;
    }
    document.getElementById('strip-rfr').querySelector('.strip-value').innerHTML =
        `Baseline: ${b.rfr.toFixed(1)}% | Target: &lt;40% | <strong>Prototype: ${p.rfr.toFixed(1)}% ±${p.rfr_ci.toFixed(1)}%</strong>`;
    document.getElementById('strip-rel').querySelector('.strip-value').innerHTML =
        `Baseline: ${b.rel.toFixed(1)}% | Target: &gt;70% | <strong>Prototype: ${p.rel.toFixed(1)}% ±${p.rel_ci.toFixed(1)}%</strong>`;
    document.getElementById('strip-cost').querySelector('.strip-value').innerHTML =
        `Baseline: Rs.${b.cost.toFixed(2)} | Target: &lt;Rs.60 | <strong>Prototype: Rs.${p.cost.toFixed(2)} ±${p.cost_ci.toFixed(2)}</strong>`;
}

function updateCalibrationPanel() {
    const c = dashData.calibration;
    document.getElementById('cal-high-stat').textContent = `${c.high.toFixed(1)}% Actual Success`;
    document.getElementById('cal-medium-stat').textContent = `${c.medium.toFixed(1)}% Actual Success`;
    document.getElementById('cal-low-stat').textContent = `${c.low.toFixed(1)}% Actual Success`;
}

function makeBarOptions(yLabel) {
    return {
        responsive: true,
        plugins: { legend: { labels: { color: TEXT_C } } },
        scales: {
            x: { ticks: { color: TEXT_C }, grid: { color: GRID_C } },
            y: { ticks: { color: TEXT_C }, grid: { color: GRID_C }, title: { display: true, text: yLabel, color: TEXT_C } }
        }
    };
}

async function initOpsCharts() {
    if (typeof Chart === 'undefined') return;
    chartsInitialized = true;
    await tryLoadMultiSeedResults();

    const b = dashData.fixed.baseline;
    const p = dashData.fixed.prototype;

    const makeErrDataset = (label, mean, ci, color) => ({
        label,
        data: [mean],
        backgroundColor: color,
        borderColor: color,
        error: [ci]
    });

    const plugin_errorBar = {
        id: 'errorBar',
        afterDatasetsDraw(chart) {
            const { ctx } = chart;
            chart.data.datasets.forEach((ds, i) => {
                if (!ds.error) return;
                const meta = chart.getDatasetMeta(i);
                meta.data.forEach((bar, idx) => {
                    const err = ds.error[idx];
                    if (err == null) return;
                    const x = bar.x;
                    const top = bar.y - (err / (chart.scales.y.max - chart.scales.y.min)) * chart.scales.y.height;
                    const bot = bar.y + (err / (chart.scales.y.max - chart.scales.y.min)) * chart.scales.y.height;
                    ctx.save();
                    ctx.strokeStyle = 'white';
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.moveTo(x, Math.max(top, bar.y - 30));
                    ctx.lineTo(x, Math.min(bot, bar.y + 30));
                    ctx.moveTo(x - 5, Math.max(top, bar.y - 30));
                    ctx.lineTo(x + 5, Math.max(top, bar.y - 30));
                    ctx.moveTo(x - 5, Math.min(bot, bar.y + 30));
                    ctx.lineTo(x + 5, Math.min(bot, bar.y + 30));
                    ctx.stroke();
                    ctx.restore();
                });
            });
        }
    };

    // Chart 1: Repeat Failure Rate
    chartInstances.rfr = new Chart(document.getElementById('chart-repeat-failure'), {
        type: 'bar',
        plugins: [plugin_errorBar],
        data: {
            labels: ['Baseline', 'Prototype'],
            datasets: [{
                label: 'Repeat Failure Rate (%)',
                data: [b.rfr, p.rfr],
                backgroundColor: [BASE_C, PROTO_C]
            }]
        },
        options: makeBarOptions('Repeat Failure Rate (%)')
    });

    // Chart 2: Reliability
    chartInstances.rel = new Chart(document.getElementById('chart-reliability'), {
        type: 'bar',
        data: {
            labels: ['Baseline', 'Prototype'],
            datasets: [{
                label: 'First-Attempt Reliability (%)',
                data: [b.rel, p.rel],
                backgroundColor: ['#f59e0b', '#3b82f6']
            }]
        },
        options: makeBarOptions('Reliability (%)')
    });

    // Chart 3: Cost per Success
    chartInstances.cost = new Chart(document.getElementById('chart-cost'), {
        type: 'bar',
        data: {
            labels: ['Baseline', 'Prototype'],
            datasets: [{
                label: 'Cost per Success (Rs.)',
                data: [b.cost, p.cost],
                backgroundColor: [BASE_C, PROTO_C]
            }]
        },
        options: makeBarOptions('Cost per Success (Rs.)')
    });

    // Chart 4: Emissions
    chartInstances.emi = new Chart(document.getElementById('chart-emissions'), {
        type: 'bar',
        data: {
            labels: ['Baseline', 'Prototype'],
            datasets: [{
                label: 'Emissions (kg CO₂)',
                data: [b.emi, p.emi],
                backgroundColor: ['#64748b', PROTO_C]
            }]
        },
        options: makeBarOptions('Emissions (kg CO₂)')
    });

    updateStripFromData();
    updateCalibrationPanel();
    tryLoadMultiSeedResults();
}

// Emissions mode toggle
document.getElementById('toggle-fixed').addEventListener('click', () => {
    currentEmissionsMode = 'fixed';
    document.getElementById('toggle-fixed').classList.add('active');
    document.getElementById('toggle-responsive').classList.remove('active');
    document.getElementById('emissions-mode-desc').textContent = 'Mode A: Both arms run exactly 1000 attempts — fair like-for-like reliability comparison.';
    document.getElementById('emissions-chart-mode-label').textContent = 'Mode A: Fixed Volume';
    if (chartInstances.emi) {
        chartInstances.emi.data.datasets[0].data = [dashData.fixed.baseline.emi, dashData.fixed.prototype.emi];
        chartInstances.emi.update();
    }
});

document.getElementById('toggle-responsive').addEventListener('click', () => {
    currentEmissionsMode = 'responsive';
    document.getElementById('toggle-responsive').classList.add('active');
    document.getElementById('toggle-fixed').classList.remove('active');
    document.getElementById('emissions-mode-desc').textContent = 'Mode B: Attempts emerge from failure rate — fewer total trips means fewer total emissions with the prototype.';
    document.getElementById('emissions-chart-mode-label').textContent = 'Mode B: Responsive Volume';
    if (chartInstances.emi) {
        chartInstances.emi.data.datasets[0].data = [dashData.responsive.baseline.emi, dashData.responsive.prototype.emi];
        chartInstances.emi.update();
    }
});

// ==========================================
// 5. EDGE CASE DEMO LOGIC
// ==========================================
const edgeButtons = document.querySelectorAll('.edge-btn');
const edgeResultBox = document.getElementById('edge-result-box');
const edgeResultTitle = document.getElementById('edge-result-title');
const edgeResultDesc = document.getElementById('edge-result-desc');
const edgeJsonOutput = document.getElementById('edge-json-output');

edgeButtons.forEach(btn => {
    btn.addEventListener('click', async () => {
        const caseId = btn.getAttribute('data-case');
        try {
            edgeResultBox.classList.remove('hidden');
            edgeJsonOutput.textContent = "Executing edge case scenario...";
            const resp = await fetch(`${API_URL}/demo/edge-case/${caseId}`, { method: 'POST' });
            const data = await resp.json();
            edgeResultTitle.textContent = data.title;
            edgeResultDesc.textContent = data.description;
            edgeJsonOutput.textContent = JSON.stringify(data.scenario_result, null, 2);
            edgeResultBox.scrollIntoView({ behavior: 'smooth' });
        } catch (err) { console.error(err); }
    });
});

// ==========================================
// 6. OPS EXTENSIONS: AREA BREAKDOWN & LEADERBOARD
// ==========================================
async function loadAreaBreakdown() {
    const grid = document.getElementById('area-breakdown-grid');
    if (!grid) return;
    try {
        const resp = await fetch(`${API_URL}/ops/area-breakdown`);
        if (!resp.ok) return;
        const areas = await resp.json();
        grid.innerHTML = areas.map(a => {
            const failPct = Math.round(a.repeat_failure_rate * 100);
            const succPct = Math.round(a.success_rate * 100);
            return `
            <div class="area-card">
                <h4>${a.area}</h4>
                <div style="margin-bottom:0.5rem;">
                    <div style="font-size:0.75rem; color:var(--text-muted);">REPEAT FAILURE RATE</div>
                    <div class="area-stat-val" style="color:${failPct > 40 ? 'var(--danger)' : 'var(--warning)'};">${failPct}%</div>
                </div>
                <div style="font-size:0.8rem; color:var(--text-muted); line-height: 1.5;">
                    <div>Addresses: <strong>${a.total_addresses}</strong></div>
                    <div>Total Attempts: <strong>${a.total_attempts}</strong></div>
                    <div>Overall Success: <strong style="color:var(--success)">${succPct}%</strong></div>
                </div>
            </div>`;
        }).join('');
    } catch(e) {
        console.error("Failed to load area breakdown:", e);
    }
}

async function loadDriverLeaderboard() {
    const tbody = document.getElementById('driver-leaderboard-body');
    if (!tbody) return;
    try {
        const resp = await fetch(`${API_URL}/ops/driver-leaderboard`);
        if (!resp.ok) return;
        const drivers = await resp.json();
        tbody.innerHTML = drivers.slice(0, 10).map((d, i) => {
            const firstSucc = Math.round(d.first_attempt_success_rate * 100);
            const repFail = Math.round(d.repeat_failure_rate * 100);
            const slaPct = Math.round(d.sla_adherence_rate * 100);
            const rankBadge = i === 0 ? '🥇 ' : (i === 1 ? '🥈 ' : (i === 2 ? '🥉 ' : ''));
            return `
            <tr>
                <td><strong>${rankBadge}${d.driver_id}</strong></td>
                <td>${d.total_attempts}</td>
                <td><strong style="color:var(--success)">${firstSucc}%</strong></td>
                <td><span style="color:${repFail > 35 ? 'var(--danger)' : 'var(--text-main)'}">${repFail}%</span></td>
                <td><span class="source-tag driver">${slaPct}% in window</span></td>
            </tr>`;
        }).join('');
    } catch(e) {
        console.error("Failed to load driver leaderboard:", e);
    }
}

// ==========================================
// 7. ML RISK EVALUATOR HANDLER
// ==========================================
const mlEvalBtn = document.getElementById('ml-eval-btn');
const mlEvalInput = document.getElementById('ml-eval-address-id');
const mlEvalResult = document.getElementById('ml-eval-result');
const mlEvalConfBand = document.getElementById('ml-eval-conf-band');
const mlEvalRiskScore = document.getElementById('ml-eval-risk-score');
const mlEvalNoteText = document.getElementById('ml-eval-note-text');

if (mlEvalBtn) {
    mlEvalBtn.addEventListener('click', async () => {
        const aid = mlEvalInput.value.trim();
        if (!aid) return alert("Please enter an Address ID");
        try {
            const resp = await fetch(`${API_URL}/dispatch/${aid}/risk-score`);
            if (!resp.ok) {
                const err = await resp.json();
                return alert(`Error: ${err.detail}`);
            }
            const data = await resp.json();
            mlEvalConfBand.textContent = data.confidence_band;
            mlEvalConfBand.className = 'cal-stat ' + (data.confidence_band === 'High' ? 'customer' : (data.confidence_band === 'Medium' ? 'driver' : ''));
            mlEvalRiskScore.textContent = data.model_risk_label;
            mlEvalNoteText.textContent = data.model_note;
            mlEvalResult.classList.remove('hidden');
        } catch(e) {
            console.error(e);
            alert("Failed to compute ML risk score.");
        }
    });
}

// Pre-fill quick addresses on load
document.addEventListener('DOMContentLoaded', () => {
    initQuickSampleAddresses();
    tryLoadMultiSeedResults();
});

