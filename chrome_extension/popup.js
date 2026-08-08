document.addEventListener('DOMContentLoaded', async () => {
  const urlEl = document.getElementById('url-text');
  const btn = document.getElementById('scan-btn');
  const mainView = document.getElementById('main-view');
  const loadingView = document.getElementById('loading-view');
  const resultsView = document.getElementById('results-view');
  const errorBox = document.getElementById('error-box');
  
  // Progress Ring logic
  const circle = document.getElementById('score-ring');
  const radius = circle.r.baseVal.value;
  const circumference = radius * 2 * Math.PI;
  circle.style.strokeDasharray = `${circumference} ${circumference}`;
  circle.style.strokeDashoffset = circumference;

  function setProgress(percent, color) {
    const offset = circumference - (percent / 100) * circumference;
    circle.style.strokeDashoffset = offset;
    circle.style.stroke = color;
  }

  let currentUrl = '';

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    currentUrl = tabs[0].url;
  } catch (err) {
    urlEl.textContent = 'Error reading URL';
    btn.disabled = true;
    return;
  }
  
  if (!currentUrl || currentUrl.startsWith('chrome://') || currentUrl.startsWith('edge://') || currentUrl.startsWith('about:')) {
    urlEl.textContent = 'Invalid Protocol';
    btn.disabled = true;
    return;
  }
  
  const displayUrl = new URL(currentUrl);
  urlEl.textContent = displayUrl.hostname + (displayUrl.pathname.length > 20 ? displayUrl.pathname.substring(0, 20) + '...' : displayUrl.pathname === '/' ? '' : displayUrl.pathname);

  btn.addEventListener('click', async () => {
    btn.style.display = 'none';
    errorBox.style.display = 'none';
    mainView.style.display = 'none';
    loadingView.style.display = 'block';
    
    try {
      // Direct call to local Vigil AI backend
      const res = await fetch('http://localhost:5000/api/scan/quick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: currentUrl })
      });
      
      const data = await res.json();
      
      if (data.status === 'error' || data.error) {
        throw new Error(data.error || "Scan failed");
      }
      
      loadingView.style.display = 'none';
      resultsView.style.display = 'block';
      
      const score = data.trust_score || 0;
      let color = '#10b981'; // safe
      if (score < 80) color = '#eab308'; // medium
      if (score < 60) color = '#f97316'; // high
      if (score < 40) color = '#ef4444'; // critical

      // Animations & Data
      setTimeout(() => setProgress(score, color), 100);
      document.getElementById('score-text').textContent = score;
      document.getElementById('score-text').style.color = color;
      
      const riskBadge = document.getElementById('risk-badge');
      riskBadge.textContent = data.risk_level?.label || 'UNKNOWN';
      riskBadge.style.color = color;
      riskBadge.style.background = color + '22'; // 22 hex for transparency

      document.getElementById('grade-text').textContent = data.grade?.letter || '--';
      document.getElementById('total-patterns').textContent = data.total_patterns || 0;
      
      // Calculate High/Critical patterns
      const sevBreakdown = data.severity_breakdown || {};
      const highCriticalCount = (sevBreakdown.critical || 0) + (sevBreakdown.high || 0);
      document.getElementById('high-risk-patterns').textContent = highCriticalCount;
      document.getElementById('high-risk-patterns').style.color = highCriticalCount > 0 ? '#ef4444' : '#a1a1aa';

      // Top Findings list
      const findingsList = document.getElementById('findings-list');
      const findings = data.findings || [];
      if (findings.length > 0) {
        // Sort by severity 
        const sevOrder = { 'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'INFORMATIONAL': 0 };
        findings.sort((a, b) => sevOrder[b.severity || 'LOW'] - sevOrder[a.severity || 'LOW']);
        
        // Take top 3 unique categories
        const addedCats = new Set();
        let html = '';
        for (const f of findings) {
          if (!addedCats.has(f.category) && addedCats.size < 3) {
            addedCats.add(f.category);
            let tagColor = f.severity === 'CRITICAL' || f.severity === 'HIGH' ? '#ff8787' : '#a1a1aa';
            let catName = f.category.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            html += `<span class="finding-tag" style="color: ${tagColor}">${catName}</span>`;
          }
        }
        findingsList.innerHTML = html;
      } else {
        findingsList.innerHTML = `<span class="finding-tag" style="color: #10b981;">No Dark Patterns Detected</span>`;
      }

      // Dispatch in-page visual highlights to active tab
      try {
        const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (activeTab && activeTab.id) {
          chrome.tabs.sendMessage(activeTab.id, {
            action: 'HIGHLIGHT_PATTERNS',
            findings: data.findings || []
          }).catch(() => {
            // Content script may not be loaded on non-http/https page
          });
        }
      } catch (e) {
        // Ignore extension messaging errors
      }

      // Handle Toggle Highlights button
      const toggleBtn = document.getElementById('toggle-highlight-btn');
      if (toggleBtn) {
        toggleBtn.onclick = async () => {
          try {
            const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (activeTab && activeTab.id) {
              chrome.tabs.sendMessage(activeTab.id, { action: 'TOGGLE_HIGHLIGHTS' });
            }
          } catch (e) {}
        };
      }

      // UX-3 FIX: Remove existing rescan button before adding new one
      const existingRescan = resultsView.querySelector('.rescan-btn');
      if (existingRescan) existingRescan.remove();

      const rescanBtn = document.createElement('button');
      rescanBtn.textContent = '↻ Scan Again';
      rescanBtn.className = 'rescan-btn';
      rescanBtn.style.cssText = 'margin-top:12px;padding:8px 18px;background:#6366f1;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;width:100%;';
      rescanBtn.addEventListener('click', async () => {
        resultsView.style.display = 'none';
        mainView.style.display = 'block';
        btn.style.display = 'flex';
        try {
          const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (activeTab && activeTab.id) {
            chrome.tabs.sendMessage(activeTab.id, { action: 'CLEAR_HIGHLIGHTS' });
          }
        } catch (e) {}
      });
      resultsView.appendChild(rescanBtn);

    } catch (err) {
      loadingView.style.display = 'none';
      mainView.style.display = 'block';
      btn.style.display = 'flex';
      
      let errorMsg = err.message;
      if (err.message.includes('Failed to fetch')) {
        errorMsg = 'Cannot connect to backend. Is Vigil AI running on localhost:5000?';
      }
      
      errorBox.textContent = errorMsg;
      errorBox.style.display = 'block';
    }
  });
});
