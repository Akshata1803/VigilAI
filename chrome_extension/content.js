/* Vigil AI — In-Page Content Script for Real-Time Dark Pattern Highlighting */

(() => {
  let activeHighlights = [];
  let isHighlightsVisible = true;

  // Listen for messages from popup.js
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'HIGHLIGHT_PATTERNS') {
      highlightPatterns(request.findings || []);
      sendResponse({ status: 'success', count: activeHighlights.length });
    } else if (request.action === 'TOGGLE_HIGHLIGHTS') {
      isHighlightsVisible = !isHighlightsVisible;
      toggleHighlightVisibility(isHighlightsVisible);
      sendResponse({ status: 'success', visible: isHighlightsVisible });
    } else if (request.action === 'CLEAR_HIGHLIGHTS') {
      clearHighlights();
      sendResponse({ status: 'success' });
    }
    return true;
  });

  function highlightPatterns(findings) {
    clearHighlights();

    if (!findings || findings.length === 0) return;

    findings.forEach((finding, index) => {
      let targetEl = null;

      // Strategy 1: Try CSS Selector if available
      if (finding.selector) {
        try {
          targetEl = document.querySelector(finding.selector);
        } catch (e) {
          // invalid selector fallback
        }
      }

      // Strategy 2: Match by context sentence or text snippet
      if (!targetEl && (finding.sentence || finding.evidence || finding.description)) {
        const searchText = (finding.sentence || finding.evidence || finding.description).toLowerCase();
        targetEl = findElementByText(searchText);
      }

      if (targetEl && !targetEl.classList.contains('vigil-highlight-target')) {
        applyHighlight(targetEl, finding, index);
      }
    });
  }

  function findElementByText(text) {
    if (!text || text.length < 3) return null;
    const cleanText = text.trim();
    
    // Search common interactive & text elements
    const elements = document.querySelectorAll('button, a, input, label, span, p, div, form');
    for (const el of elements) {
      if (el.children.length > 3) continue; // Skip large container blocks
      const elText = el.textContent || '';
      if (elText.toLowerCase().includes(cleanText)) {
        return el;
      }
    }
    return null;
  }

  function applyHighlight(el, finding, index) {
    const severity = (finding.severity || 'HIGH').toUpperCase();
    const category = (finding.category || 'Dark Pattern').replace(/_/g, ' ');
    const formattedCat = category.replace(/\b\w/g, l => l.toUpperCase());
    const statute = finding.legal_statute || 'FTC Act §5 / GDPR Art. 13';
    const description = finding.description || finding.evidence || 'Deceptive UI pattern detected by Vigil AI.';

    el.classList.add('vigil-highlight-target');
    el.setAttribute('data-severity', severity);
    el.setAttribute('data-vigil-id', index);

    // Create floating badge
    const badge = document.createElement('div');
    badge.className = 'vigil-badge';
    badge.setAttribute('data-severity', severity);
    badge.innerHTML = `
      <span class="vigil-badge-shield"></span>
      <span>🛡️ ${formattedCat}</span>
      <div class="vigil-tooltip">
        <div class="vigil-tt-header">
          <span class="vigil-tt-title">${formattedCat}</span>
          <span style="color: ${getSeverityColor(severity)}">[${severity}]</span>
        </div>
        <div>${escapeHtml(description)}</div>
        <div class="vigil-tt-statute">
          <strong>Violation:</strong> ${escapeHtml(statute)}
        </div>
      </div>
    `;

    // Attach badge
    if (getComputedStyle(el).position === 'static') {
      el.style.position = 'relative';
    }
    el.appendChild(badge);
    activeHighlights.push({ element: el, badge });
  }

  function toggleHighlightVisibility(visible) {
    activeHighlights.forEach(item => {
      if (visible) {
        item.element.classList.add('vigil-highlight-target');
        if (item.badge) item.badge.style.display = 'inline-flex';
      } else {
        item.element.classList.remove('vigil-highlight-target');
        if (item.badge) item.badge.style.display = 'none';
      }
    });
  }

  function clearHighlights() {
    activeHighlights.forEach(item => {
      if (item.element) item.element.classList.remove('vigil-highlight-target');
      if (item.badge) item.badge.remove();
    });
    activeHighlights = [];
  }

  function getSeverityColor(sev) {
    switch (sev) {
      case 'CRITICAL': return '#ef4444';
      case 'HIGH': return '#f97316';
      case 'MEDIUM': return '#eab308';
      default: return '#3b82f6';
    }
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
