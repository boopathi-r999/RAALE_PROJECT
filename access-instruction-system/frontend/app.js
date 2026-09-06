const API_URL = "http://127.0.0.1:8000";

// --- GLOBAL STATE ---
let currentAddressId = null;
let currentNoteId = null;
let chartsInitialized = false;
let chartInstances = {};

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

// --- TAB SWITCHING ---
document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        
        tab.classList.add('active');
        const targetTab = tab.getAttribute('data-tab');
        document.getElementById(targetTab).classList.add('active');
        
        if (targetTab === 'explorer-view') {
            loadAddressExplorer();
        } else if (targetTab === 'ops-view' && !chartsInitialized) {
            initOpsCharts();
        }
    });
});

// ==========================================
// 1. DRIVER VIEW LOGIC
// ==========================================
const dispatchBtn = document.getElementById('dispatch-btn');
const addressInput = document.getElementById('address-id');
const resultBox = document.getElementById('dispatch-result');
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
const btnSuccess = document.getElementById('log-success-btn');
const btnFail = document.getElementById('log-fail-btn');

dispatchBtn.addEventListener('click', async () => {
    const addressId = addressInput.value.trim();
    if (!addressId) return alert("Enter an address ID");

    try {
        const response = await fetch(`${API_URL}/dispatch/${addressId}`);
        const data = await response.json();
        
        currentAddressId = addressId;
        currentNoteId = data.note ? data.note.note_id : null;
        
        resultBox.classList.remove('hidden');
        feedbackBanner.classList.add('hidden');
        inlineNoteBox.classList.add('hidden');
        
        confLabel.textContent = data.confidence_label;
        
        if (data.note) {
            instText.textContent = data.note.instruction_text;
            const scorePercent = Math.round(data.confidence_score * 100);
            confBadge.textContent = `${scorePercent}%`;
            confBadge.style.display = 'block';
            
            relativeTimeBadge.textContent = formatRelativeTime(data.note.last_confirmed_at);
            
            // Source badge
            sourceBadge.textContent = data.note.source;
            sourceBadge.className = 'source-tag ' + (data.note.source === 'CUSTOMER_CONFIRMED' ? 'customer' : 'driver');
            
            // Confidence indicator color
            confIndicator.className = 'confidence-indicator';
            if (data.confidence_score >= 0.7) confIndicator.classList.add('high');
            else if (data.confidence_score >= 0.4) confIndicator.classList.add('medium');
            else confIndicator.classList.add('low');
        } else {
            // Explicit Cold Start Empty State
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
    
    try {
        const payload = {
            address_id: currentAddressId,
            outcome: 'SUCCESS',
            failure_reason: 'NONE',
            driver_id: 'DRIVER_MOBILE_APP',
            used_note_id: currentNoteId
        };
        
        await fetch(`${API_URL}/attempts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        // If success on cold start (no note used), show inline text field immediately
        if (!currentNoteId) {
            inlineNoteBox.classList.remove('hidden');
            feedbackBanner.textContent = "Success logged! Prompt: Add an access note below for the next driver.";
            feedbackBanner.classList.remove('hidden');
        } else {
            feedbackBanner.textContent = "Attempt logged as SUCCESS. Confirmation count updated!";
            feedbackBanner.classList.remove('hidden');
        }
    } catch (err) {
        console.error(err);
    }
});

submitInlineNoteBtn.addEventListener('click', async () => {
    const text = newNoteInput.value.trim();
    if (!text) return alert("Enter instruction text");
    
    try {
        await fetch(`${API_URL}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address_id: currentAddressId,
                instruction_text: text,
                source: "DRIVER_LOGGED"
            })
        });
        
        feedbackBanner.textContent = "Access note saved successfully! Next driver will receive this note.";
        inlineNoteBox.classList.add('hidden');
        newNoteInput.value = '';
    } catch (err) {
        console.error(err);
    }
});

btnFail.addEventListener('click', async () => {
    if (!currentAddressId) return;
    
    try {
        const payload = {
            address_id: currentAddressId,
            outcome: 'FAILED',
            failure_reason: 'NO_ACCESS',
            driver_id: 'DRIVER_MOBILE_APP',
            used_note_id: currentNoteId
        };
        
        await fetch(`${API_URL}/attempts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (currentNoteId) {
            feedbackBanner.textContent = "Noted — this instruction may be outdated, confidence will be adjusted.";
        } else {
            feedbackBanner.textContent = "Attempt logged as FAILED.";
        }
        feedbackBanner.classList.remove('hidden');
    } catch (err) {
        console.error(err);
    }
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
    } catch (err) {
        console.error(err);
    }
});

custConfirmBtn.addEventListener('click', async () => {
    if (!custNoteObj) return;
    try {
        await fetch(`${API_URL}/notes/${custNoteObj.note_id}/confirm?source=CUSTOMER_CONFIRMED`, {
            method: 'POST'
        });
        custStatusBanner.textContent = "Thank you! You have verified this instruction (weight boosted by +3).";
        custStatusBanner.classList.remove('hidden');
    } catch (err) {
        console.error(err);
    }
});

custCorrectToggleBtn.addEventListener('click', () => {
    custCorrectionBox.classList.toggle('hidden');
});

custSubmitCorrectionBtn.addEventListener('click', async () => {
    const text = custCorrectionInput.value.trim();
    const addrId = custAddressInput.value.trim();
    if (!text || !addrId) return alert("Enter correction text");

    try {
        await fetch(`${API_URL}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address_id: addrId,
                instruction_text: text,
                source: "CUSTOMER_CONFIRMED"
            })
        });
        custStatusBanner.textContent = "Customer correction submitted! Stored with high initial confidence weighting (Customer-verified).";
        custStatusBanner.classList.remove('hidden');
        custCorrectionBox.classList.add('hidden');
        custCorrectionInput.value = '';
    } catch (err) {
        console.error(err);
    }
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
        
        explorerTableBody.innerHTML = items.map(item => `
            <tr>
                <td><strong>${item.address_id}</strong></td>
                <td>${item.area}</td>
                <td>
                    <span class="source-tag ${item.confidence_score >= 0.7 ? 'customer' : (item.confidence_score >= 0.4 ? 'driver' : '')}">
                        ${item.confidence_label}
                    </span>
                </td>
                <td><strong>${Math.round(item.confidence_score * 100)}%</strong></td>
                <td>${item.confirmation_count} / <span style="color:var(--danger)">${item.contradiction_count}</span></td>
                <td>${item.total_attempts}</td>
                <td>${item.sources.map(s => `<span class="source-tag ${s === 'CUSTOMER_CONFIRMED' ? 'customer' : 'driver'}">${s}</span>`).join(' ')}</td>
                <td>
                    <button class="primary-btn" onclick="openAuditTrail('${item.address_id}')" style="padding:0.3rem 0.7rem; font-size:0.8rem;">Audit Trail</button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error(err);
        explorerTableBody.innerHTML = `<tr><td colspan="8">Failed to load explorer data.</td></tr>`;
    }
}

explorerRefreshBtn.addEventListener('click', loadAddressExplorer);
explorerSort.addEventListener('change', loadAddressExplorer);
explorerSearch.addEventListener('keyup', (e) => {
    if (e.key === 'Enter') loadAddressExplorer();
});

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
                </div>
            `).join('');
            
        auditAttemptsList.innerHTML = data.attempts.length === 0 ? '<div class="audit-item">No delivery attempts recorded</div>' :
            data.attempts.map(a => `
                <div class="audit-item">
                    <strong>Attempt #${a.attempt_id}:</strong> 
                    <span style="color:${a.outcome === 'SUCCESS' ? 'var(--success)' : 'var(--danger)'}">${a.outcome}</span>
                    <br><small>Driver: ${a.driver_id} | Used Note ID: ${a.used_note_id || 'None'}</small>
                    <br><small style="color:var(--text-muted)">${new Date(a.timestamp).toLocaleString()}</small>
                </div>
            `).join('');
            
        auditTrailContainer.classList.remove('hidden');
        auditTrailContainer.scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
        console.error(err);
    }
}

closeAuditBtn.addEventListener('click', () => {
    auditTrailContainer.classList.add('hidden');
});

// ==========================================
// 4. OPS DASHBOARD & CHART.JS LOGIC
// ==========================================
function initOpsCharts() {
    if (typeof Chart === 'undefined') return;
    chartsInitialized = true;

    const barOptions = {
        responsive: true,
        plugins: {
            legend: { labels: { color: '#94a3b8' } }
        },
        scales: {
            x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
            y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
    };

    // Chart 1: Repeat Failure Rate
    new Chart(document.getElementById('chart-repeat-failure'), {
        type: 'bar',
        data: {
            labels: ['Baseline (No Memory)', 'Prototype (System)'],
            datasets: [{
                label: 'Repeat Failure Rate (%)',
                data: [51.3, 36.3],
                backgroundColor: ['#ef4444', '#10b981']
            }]
        },
        options: barOptions
    });

    // Chart 2: Reliability
    new Chart(document.getElementById('chart-reliability'), {
        type: 'bar',
        data: {
            labels: ['Baseline (No Memory)', 'Prototype (System)'],
            datasets: [{
                label: 'First-Attempt Reliability (%)',
                data: [56.7, 71.4],
                backgroundColor: ['#f59e0b', '#3b82f6']
            }]
        },
        options: barOptions
    });

    // Chart 3: Cost Per Success
    new Chart(document.getElementById('chart-cost'), {
        type: 'bar',
        data: {
            labels: ['Baseline (No Memory)', 'Prototype (System)'],
            datasets: [{
                label: 'Cost per Success (Rs.)',
                data: [70.55, 56.02],
                backgroundColor: ['#ef4444', '#10b981']
            }]
        },
        options: barOptions
    });

    // Chart 4: Emissions
    new Chart(document.getElementById('chart-emissions'), {
        type: 'bar',
        data: {
            labels: ['Baseline (1000 Trips)', 'Prototype (1000 Trips)'],
            datasets: [{
                label: 'Total Emissions (kg CO2)',
                data: [420.0, 420.0],
                backgroundColor: ['#64748b', '#64748b']
            }]
        },
        options: barOptions
    });
}

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
        } catch (err) {
            console.error(err);
        }
    });
});
