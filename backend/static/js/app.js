/* ============================================================
   Vigil — Always watching. Always honest.
   Frontend engine: scan pipeline, results rendering,
   animated gauge, 9-engine bars, export, history
   ============================================================ */

'use strict';

// ── Globals ───────────────────────────────────────────────────
let currentReport = null;
let allFindings = [];
let scanCount = 0;
let _scanAbort = null;   // UX-1: AbortController for cancel support
let _scanTimer = null;   // UX-1: Elapsed timer interval
let _scanStart = 0;      // UX-1: Scan start timestamp

// ── DOM helpers ───────────────────────────────────────────────
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    initNavScroll();
    initNavLinks();
    initInputKey();
    updateHeroScanCount();
    showView('hero');
    animateHeroMetrics();
});

// ═══════════════════════════════════════════════════════════════
// NAVBAR
// ═══════════════════════════════════════════════════════════════
function initNavScroll() {
    window.addEventListener('scroll', () => {
        $('#navbar').classList.toggle('scrolled', window.scrollY > 20);
    }, { passive: true });
}
function initNavLinks() {
    $$('[data-nav]').forEach(el => {
        el.addEventListener('click', e => {
            e.preventDefault();
            const target = el.dataset.nav;
            if (target === 'history') loadHistory();
            showView(target);
        });
    });
}

// ═══════════════════════════════════════════════════════════════
// VIEW ROUTING
// ═══════════════════════════════════════════════════════════════
function showView(id) {
    $$('section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(id);
    if (target) {
        target.classList.add('active');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    if (id !== 'results') {
        $('#scan-overlay').classList.remove('active');
    }
}

// ═══════════════════════════════════════════════════════════════
// SCAN FLOW
// ═══════════════════════════════════════════════════════════════
function setExample(url) {
    $('#url-input').value = url;
    $('#url-input').focus();
}

function initInputKey() {
    const inp = $('#url-input');
    if (!inp) return;
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') startScan(); });
}

async function startScan() {
    const input = $('#url-input');
    const btn = $('#scan-btn');
    let url = (input?.value || '').trim();

    if (!url) { showToast('Please enter a URL to scan'); return; }
    if (!url.startsWith('http')) url = 'https://' + url;
    input.value = url;

    showScanOverlay(url);
    btn.disabled = true;

    // ── Stage → progress mapping (matches async task state updates) ────
    const STAGE_PROGRESS = {
        'PENDING': 5,
        'SCANNING': 20,   // Playwright browser scan
        'ANALYZING': 55,   // 9-engine parallel pipeline
        'CALIBRATING': 80,   // HADE + Fusion
        'SUCCESS': 100,
    };

    // ── Step index driven by real task state, not fake timers ─────────
    const STAGE_STEP = {
        'SCANNING': 1,
        'ANALYZING': 5,
        'CALIBRATING': 8,
        'SUCCESS': 9,
    };

    // ── Hard timeout: 120s (async task limit) ─────────────────────────
    let cancelled = false;
    const timeoutId = setTimeout(() => {
        cancelled = true;
        showScanError('Scan timed out after 120s. The site may be unreachable or blocking automated access.');
        btn.disabled = false;
    }, 120000);

    try {
        // ── Step 1: Submit to async queue — returns immediately ───────
        setProgress(5);
        await activateStep(0);

        _scanAbort = new AbortController();
        const submitRes = await fetch('/api/scan/async', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
            signal: _scanAbort.signal,
        });

        // ── Graceful fallback: if async queue unavailable, use sync ────
        if (submitRes.status === 503) {
            const syncRes = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
                signal: _scanAbort.signal,
            });
            const syncData = await syncRes.json();
            if (!syncRes.ok || syncData.status === 'error') {
                throw new Error(syncData.error || 'Scan failed');
            }
            clearTimeout(timeoutId);
            setProgress(100);
            completeAllSteps();
            await sleep(400);
            currentReport = syncData;
            allFindings = syncData.findings || [];
            scanCount++;
            updateHeroScanCount();
            hideScanOverlay();
            renderResults(syncData);
            showView('results');
            return;
        }

        const { task_id } = await submitRes.json();
        if (!task_id) throw new Error('No task ID returned from server.');

        // ── Step 2: Poll /api/scan/status/<task_id> for real progress ─
        let lastStage = '';
        while (!cancelled) {
            await sleep(1500);
            if (cancelled) break;

            const pollRes = await fetch(`/api/scan/status/${task_id}`, {
                signal: _scanAbort.signal,
            });
            const poll = await pollRes.json();

            const state = poll.state || poll.status || 'PENDING';
            const stage = poll.stage || state;
            const pct = STAGE_PROGRESS[state] ?? STAGE_PROGRESS['PENDING'];
            const stepIdx = STAGE_STEP[state];

            // Advance steps and progress bar only forward
            if (pct > 0) setProgress(pct);
            if (stepIdx !== undefined && stage !== lastStage) {
                await activateStep(stepIdx);
                lastStage = stage;
            }

            if (state === 'SUCCESS' || state === 'FAILURE') {
                clearTimeout(timeoutId);
                if (state === 'FAILURE' || poll.status === 'error') {
                    throw new Error(poll.error || 'Scan failed on worker.');
                }
                const data = poll.result || poll;
                setProgress(100);
                completeAllSteps();
                await sleep(400);
                currentReport = data;
                allFindings = data.findings || [];
                scanCount++;
                updateHeroScanCount();
                hideScanOverlay();
                renderResults(data);
                showView('results');
                return;
            }
        }

    } catch (err) {
        clearTimeout(timeoutId);
        if (err.name === 'AbortError') {
            showScanError('Scan cancelled.');
        } else if (!cancelled) {
            showScanError(err.message || 'An unexpected error occurred.');
        }
    } finally {
        btn.disabled = false;
        _stopScanTimer();
        _scanAbort = null;
    }
}

function showScanOverlay(url) {
    const overlay = $('#scan-overlay');
    overlay.classList.add('active');
    $('#scan-target-url').textContent = url;
    $$('.smo-step').forEach(s => s.classList.remove('active', 'done'));
    hideScanError();
    setProgress(0);
    const lbl = $('#sm-progress-label');
    if (lbl) lbl.textContent = '0%';
    _startScanTimer();
}

function hideScanOverlay() {
    $('#scan-overlay').classList.remove('active');
    _stopScanTimer();
}

// UX-1: Cancel scan via AbortController
function cancelScan() {
    if (_scanAbort) _scanAbort.abort();
    _stopScanTimer();
}

// UX-1: Elapsed timer + show cancel button after 15s
function _startScanTimer() {
    _scanStart = Date.now();
    const elapsedEl = $('#scan-elapsed');
    const cancelBtn = $('#cancel-scan-btn');
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (elapsedEl) elapsedEl.textContent = '0s';
    _scanTimer = setInterval(() => {
        const sec = Math.round((Date.now() - _scanStart) / 1000);
        if (elapsedEl) elapsedEl.textContent = sec + 's elapsed';
        if (cancelBtn && sec >= 15) cancelBtn.style.display = 'inline-block';
    }, 1000);
}
function _stopScanTimer() {
    if (_scanTimer) { clearInterval(_scanTimer); _scanTimer = null; }
    const cancelBtn = $('#cancel-scan-btn');
    if (cancelBtn) cancelBtn.style.display = 'none';
}

/** Show an inline error inside the scan overlay so users can read it. */
function showScanError(message) {
    const errEl = $('#scan-error-state');
    const msgEl = $('#scan-error-msg');
    if (msgEl) msgEl.textContent = message || 'An unexpected error occurred.';
    if (errEl) errEl.style.display = 'block';
    // Stop spinner animation
    const spinner = $('.sp-ring');
    if (spinner) spinner.style.animationPlayState = 'paused';
    showToast('Scan error — see details in the scan overlay');
}

/** Dismiss the inline error banner (called by the × button in the HTML). */
function hideScanError() {
    const errEl = $('#scan-error-state');
    if (errEl) errEl.style.display = 'none';
    const spinner = $('.sp-ring');
    if (spinner) spinner.style.animationPlayState = 'running';
}

async function activateStep(idx) {
    const steps = $$('.smo-step');
    if (idx > 0 && steps[idx - 1]) {
        steps[idx - 1].classList.remove('active');
        steps[idx - 1].classList.add('done');
    }
    if (steps[idx]) steps[idx].classList.add('active');
}

function completeAllSteps() {
    $$('.smo-step').forEach(s => { s.classList.remove('active'); s.classList.add('done'); });
}

function setProgress(pct) {
    const fill = $('#scan-progress-fill');
    if (fill) fill.style.width = pct + '%';
    const lbl = $('#sm-progress-label');
    if (lbl) lbl.textContent = Math.round(pct) + '%';
}

// ═══════════════════════════════════════════════════════════════
// RENDER RESULTS
// ═══════════════════════════════════════════════════════════════
function renderResults(report) {
    // URL + title
    const urlEl = $('#result-url');
    if (urlEl) { urlEl.textContent = report.url; urlEl.href = report.url; }
    const titleEl = $('#result-title');
    if (titleEl) titleEl.textContent = report.page_title || report.domain;

    // Gauge
    renderGauge(report.trust_score, report.grade);

    // Score side meta
    const sv2 = $('#gauge-score-value2');
    if (sv2) { sv2.textContent = report.trust_score; sv2.style.color = gaugeColor(report.trust_score); }

    // Grade
    const gradeDisp = $('#grade-display');
    if (gradeDisp && report.grade) {
        gradeDisp.textContent = report.grade.letter;
        gradeDisp.style.color = report.grade.color;
    }

    // Risk
    const rb = $('#risk-badge');
    if (rb && report.risk_level) {
        rb.textContent = (report.risk_level.emoji || '') + ' ' + report.risk_level.label;
        rb.className = 'risk-tag ' + (report.risk_level.level || 'low').toLowerCase();
    }

    // Summary
    const su = $('#result-summary');
    if (su) su.textContent = report.summary;

    // Stats
    animateNumber($('#stat-total'), 0, report.total_patterns, 800);
    animateNumber($('#stat-high'), 0, report.severity_breakdown?.high || 0, 900);
    animateNumber($('#stat-medium'), 0, report.severity_breakdown?.medium || 0, 900);
    animateNumber($('#stat-low'), 0, report.severity_breakdown?.low || 0, 900);
    animateNumber($('#stat-elite'), 0, report.analysis_breakdown?.elite_findings || 0, 900);

    // Engine bars
    const totalF = Math.max(report.total_patterns || 1, 1);
    const bkd = report.analysis_breakdown || {};
    renderEngineBar('analysis-dom-count', 'engine-dom-bar', bkd.dom_findings || 0, totalF);
    renderEngineBar('analysis-text-count', 'engine-text-bar', bkd.text_findings || 0, totalF);
    renderEngineBar('analysis-visual-count', 'engine-visual-bar', bkd.visual_findings || 0, totalF);
    renderEngineBar('analysis-elite-count', 'engine-elite-bar', bkd.elite_findings || 0, totalF);
    renderEngineBar('analysis-cookie-count', 'engine-cookie-bar', bkd.cookie_findings || 0, totalF);
    renderEngineBar('analysis-link-count', 'engine-link-bar', bkd.link_findings || 0, totalF);
    renderEngineBar('analysis-readability-count', 'engine-readability-bar', bkd.readability_findings || 0, totalF);
    renderEngineBar('analysis-behavioral-count', 'engine-behavioral-bar', bkd.behavioral_findings || 0, totalF);
    renderEngineBar('analysis-ml-count', 'engine-ml-bar', bkd.ml_findings || 0, totalF);

    // Compliance
    renderComplianceFlags(report.compliance_flags || [], report.regulations_violated || []);

    // Categories
    renderCategories(report.category_breakdown || []);

    // Recommendations
    renderRecommendations(report.recommendations || []);

    // Findings
    filterFindings('all', null);

    // Badges
    const cc = $('#compliance-count');
    if (cc) cc.textContent = (report.compliance_flags || []).length + ' flags';
    const catC = $('#cat-count');
    if (catC) catC.textContent = (report.category_breakdown || []).length;
    const fc = $('#findings-count');
    if (fc) fc.textContent = report.total_patterns + ' found';
}

// ── Gauge ─────────────────────────────────────────────────────
function gaugeColor(score) {
    if (score >= 80) return '#10b981';
    if (score >= 60) return '#f59e0b';
    if (score >= 40) return '#f97316';
    return '#ef4444';
}

function renderGauge(score, grade) {
    const r = 74; // must match SVG
    const circumference = 2 * Math.PI * r;
    const offset = circumference - (score / 100) * circumference;
    const fill = $('#gauge-fill');
    const numEl = $('#gauge-score-value');
    const gradeEl = $('#gauge-grade');
    const color = gaugeColor(score);

    if (fill) {
        fill.style.strokeDasharray = circumference;
        fill.style.strokeDashoffset = circumference;
        fill.style.stroke = color;
        setTimeout(() => { fill.style.strokeDashoffset = offset; }, 150);
    }
    if (numEl) {
        animateNumber(numEl, 0, score, 1300);
        numEl.style.color = color;
    }
    if (gradeEl && grade) {
        gradeEl.textContent = grade.letter;
        gradeEl.style.color = grade.color;
    }
}

// ── Engine Bars ───────────────────────────────────────────────
function renderEngineBar(countId, barId, count, total) {
    const countEl = $(`#${countId}`);
    const barEl = $(`#${barId}`);
    if (countEl) animateNumber(countEl, 0, count, 800);
    if (barEl) {
        const pct = total > 0 ? Math.round((count / total) * 100) : 0;
        setTimeout(() => { barEl.style.width = Math.max(pct, count > 0 ? 8 : 0) + '%'; }, 300);
    }
}

// ── Compliance Flags ──────────────────────────────────────────
function renderComplianceFlags(flags, regs) {
    const container = $('#compliance-flags');
    const regsRow = $('#regs-violated-row');
    const regsTags = $('#regs-tags');
    if (!container) return;

    if (!flags.length) {
        container.innerHTML = '<div class="compliance-ok">No regulatory compliance risks detected.</div>';
        if (regsRow) regsRow.style.display = 'none';
        return;
    }

    container.innerHTML = flags.map(f => `
    <div class="compliance-flag ${(f.status || '').toLowerCase()}">
      <div class="cf-name">${escHtml(f.regulation)}</div>
      <div class="cf-desc">${escHtml(f.status)}</div>
    </div>`).join('');

    if (regs.length && regsRow && regsTags) {
        regsRow.style.display = 'flex';
        regsTags.innerHTML = regs.map(r => `<span class="reg-tag">${escHtml(r)}</span>`).join('');
    }
}

// ── Category Grid ─────────────────────────────────────────────
function renderCategories(categories) {
    const container = $('#category-list');
    if (!container) return;

    if (!categories.length) {
        container.innerHTML = '<p class="empty-msg">No specific categories detected.</p>';
        return;
    }

    const max = Math.max(...categories.map(c => c.count), 1);
    container.innerHTML = categories.map(c => {
        const info = c.info || { name: c.category.replace(/_/g, ' '), icon: '⚠️' };
        const pct = Math.round((c.count / max) * 100);
        return `
    <div class="cat-card">
      <div class="cat-header">
        <span class="cat-name">${escHtml(info.name || c.category)}</span>
        <span class="cat-count">${c.count}</span>
      </div>
      <div class="cat-bar"><div class="cat-fill" style="width:${pct}%"></div></div>
    </div>`;
    }).join('');
}

// ── Recommendations ───────────────────────────────────────────
function renderRecommendations(recs) {
    const container = $('#recommendations-list');
    if (!container) return;

    if (!recs.length) {
        container.innerHTML = '<p class="empty-msg">No issues found — this site looks clean!</p>';
        return;
    }
    container.innerHTML = recs.map((rec, i) => `
    <div class="rec-item">
      <span class="rec-num">${i + 1}</span>
      <span class="rec-text">${escHtml(rec.recommendation || rec)}</span>
    </div>`).join('');
}

// ── Findings ──────────────────────────────────────────────────
function filterFindings(severity, btnEl) {
    if (btnEl) {
        $$('.fb').forEach(b => b.classList.remove('active'));
        btnEl.classList.add('active');
    }

    const container = $('#findings-list');
    if (!container) return;

    const filtered = severity === 'all'
        ? allFindings
        : allFindings.filter(f => f.severity === severity);

    if (!filtered.length) {
        container.innerHTML = allFindings.length
            ? '<p class="empty-msg">No findings at this severity level.</p>'
            : '<p class="empty-msg">No dark patterns detected!</p>';
        return;
    }

    container.innerHTML = filtered.map((f, idx) => {
        const uid = 'fc-' + idx;
        const sev = (f.severity || 'LOW');
        const legalHtml = f.legal_refs?.length
            ? `<div class="fc-row"><span class="fc-key">Legal refs</span><div class="fc-val">${f.legal_refs.map(r => `<span class="reg-tag">${escHtml(r)}</span>`).join(' ')}</div></div>`
            : '';

        return `
    <div class="finding-card sev-${sev}" id="${uid}">
      <div class="fc-head" onclick="this.closest('.finding-card').classList.toggle('open')">
        <span class="fc-sev">${sev}</span>
        <span class="fc-title">${escHtml(f.type)}</span>
        <span class="fc-conf">${Math.round((f.confidence || 0) * 100)}%</span>
        <span class="fc-arrow">▼</span>
      </div>
      <div class="fc-body">
        <div class="fc-row"><span class="fc-key">Description</span><span class="fc-val">${escHtml(f.description)}</span></div>
        <div class="fc-row"><span class="fc-key">Evidence</span><div class="fc-evidence">${escHtml(f.evidence)}</div></div>
        <div class="fc-row"><span class="fc-key">Element</span><span class="fc-val">${escHtml(f.element)}</span></div>
        <div class="fc-row"><span class="fc-key">Fix</span><div class="fc-rec">${escHtml(f.recommendation)}</div></div>
        ${legalHtml}
      </div>
    </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════
async function exportReport(format) {
    if (!currentReport?.scan_id) {
        showToast('Run a scan first before exporting.');
        return;
    }

    const url = `/api/scan/export/${currentReport.scan_id}?format=${format}`;
    const filename = `vigil-${currentReport.domain}-${format === 'json' ? 'report.json' : 'report.txt'}`;

    try {
        showToast('Preparing ' + format.toUpperCase() + ' download...');
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            showToast('Export failed: ' + (err.error || res.statusText));
            return;
        }
        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = objectUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        // Revoke the blob URL after a short delay to free memory
        setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
        showToast('✅ Download started: ' + filename);
    } catch (err) {
        showToast('Export error: ' + err.message);
    }
}

// ═══════════════════════════════════════════════════════════════
// HISTORY
// ═══════════════════════════════════════════════════════════════
async function loadHistory() {
    try {
        const res = await fetch('/api/scan/history');
        const data = await res.json();
        renderHistory(data);
    } catch (e) {
        showToast('Failed to load history');
    }
}

function renderHistory(data) {
    const grid = $('#history-grid');
    const subtitle = $('#history-subtitle');
    const statsRow = $('#session-stats');

    if (!data.history?.length) {
        if (grid) grid.innerHTML = '<p class="empty-msg">No scans yet. Head back and scan a site!</p>';
        if (subtitle) subtitle.textContent = '0 sites scanned this session';
        if (statsRow) statsRow.style.display = 'none';
        return;
    }

    if (statsRow) {
        statsRow.style.display = 'flex';
        const ssTotal = $('#ss-total'), ssAvg = $('#ss-avg'), ssHigh = $('#ss-high');
        if (ssTotal) ssTotal.textContent = data.total;
        if (ssAvg) ssAvg.textContent = data.avg_trust_score ?? '—';
        if (ssHigh) ssHigh.textContent = data.high_risk_count ?? '—';
    }

    if (subtitle) subtitle.textContent = data.total + ' site' + (data.total === 1 ? '' : 's') + ' scanned this session';

    if (!grid) return;
    grid.innerHTML = data.history.map(h => {
        const score = h.trust_score;
        const circ = 2 * Math.PI * 20;
        const off = circ - (score / 100) * circ;
        const col = gaugeColor(score);
        const grade = (typeof h.grade === 'object' && h.grade) ? (h.grade.letter || '?') : (h.grade || '?');
        const safeScanId = escHtml(String(h.scan_id)).replace(/'/g, "\\'");
        return `
    <div class="hist-card" onclick="loadHistoryItem('${safeScanId}')">
      <div class="hist-ring">
        <svg viewBox="0 0 52 52">
          <circle cx="26" cy="26" r="20" fill="none" stroke="#e2e8f0" stroke-width="3"/>
          <circle cx="26" cy="26" r="20" fill="none" stroke="${col}" stroke-width="3"
            stroke-dasharray="${circ.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"
            stroke-linecap="round" style="transform-origin:50% 50%;transform:rotate(-90deg)"/>
        </svg>
        <span class="hist-ring-num" style="color:${col}">${score}</span>
      </div>
      <div class="hist-body">
        <div class="hist-url">${escHtml(h.domain)}</div>
        <div class="hist-meta">${h.total_patterns ?? '?'} patterns · ${h.timestamp || ''}</div>
      </div>
      <span class="hist-grade">${grade}</span>
    </div>`;
    }).join('');
}

async function loadHistoryItem(scanId) {
    try {
        // Use the report API — not the export endpoint — to reload a past scan for display
        const res = await fetch(`/api/report/${scanId}`);
        if (!res.ok) { showToast('Could not reload report'); return; }
        const data = await res.json();
        if (data.status === 'error') { showToast('Could not reload report'); return; }
        currentReport = data;
        allFindings = data.findings || [];
        renderResults(data);
        showView('results');
    } catch {
        showToast('Error loading scan');
    }
}

// ═══════════════════════════════════════════════════════════════
// HERO SCAN COUNTER
// ═══════════════════════════════════════════════════════════════
function updateHeroScanCount() {
    const el = $('#hs-scans');
    if (el) el.textContent = scanCount;
}

function animateHeroMetrics() {
    $$('.anim-counter').forEach(el => {
        if (el.id === 'hs-scans') return; // Handled by scanCount logic
        const target = parseInt(el.getAttribute('data-target'), 10);
        const suffix = el.getAttribute('data-suffix') || '';
        if (!target || target <= 0) return;

        const start = performance.now();
        const duration = 1800;
        function tick(now) {
            const elapsed = Math.min(now - start, duration);
            const progress = elapsed / duration;
            const ease = 1 - Math.pow(1 - progress, 4);
            el.textContent = Math.round(target * ease) + suffix;
            if (elapsed < duration) requestAnimationFrame(tick);
            else el.textContent = target + suffix;
        }
        requestAnimationFrame(tick);
    });
}

// ═══════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════
function animateNumber(el, from, to, duration) {
    if (!el) return;
    const start = performance.now();
    const range = to - from;
    function tick(now) {
        const elapsed = Math.min(now - start, duration);
        const progress = elapsed / duration;
        const ease = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(from + range * ease);
        if (elapsed < duration) requestAnimationFrame(tick);
        else el.textContent = to;
    }
    requestAnimationFrame(tick);
}

function escHtml(str) {
    if (typeof str !== 'string') return String(str ?? '');
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function showToast(msg) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = msg;
    t.className = 'toast show';
    setTimeout(() => { t.classList.remove('show'); }, 3500);
}