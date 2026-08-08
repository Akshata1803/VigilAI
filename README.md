# 🛡️ Vigil AI

**Vigil AI** is an enterprise-grade dark pattern detection engine that protects users from deceptive digital design. It scans any website using a 9-engine AI pipeline — combining Machine Learning, NLP, DOM analysis, and GDPR-grade consent auditing — and maps every finding to exact legal frameworks like GDPR, FTC, and DSA.

The project also ships a **Chrome Extension (v1.1)** that highlights detected dark patterns directly on live web pages with severity-coded glowing badges and interactive legal tooltips.

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey.svg)](https://flask.palletsprojects.com/)
[![ML: scikit-learn](https://img.shields.io/badge/ML-scikit--learn-orange.svg)](https://scikit-learn.org/)
[![Chrome Extension](https://img.shields.io/badge/Chrome%20Extension-v1.1-4f46e5.svg)](#-chrome-extension-v11)
[![Tests](https://img.shields.io/badge/tests-339%20passed-10b981.svg)](#-running-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## ✨ Features

### 🤖 **9-Engine AI Detection Pipeline**
- **ML Classifier** — Scikit-Learn logistic regression detecting deceptive text tonalities
- **DOM Analyzer** — Structural checks for pre-checked boxes, drip pricing, and un-closable popups
- **NLP Engine** — 200+ linguistic patterns detecting confirmshaming, FUD, and trick questions
- **Visual Analyzer** — Reads computed CSS styles for color contrast manipulation and button misdirection
- **Elite Privacy Filter** — Detects session replays, fingerprinting, and invasive data brokering
- **Consent Auditor** — GDPR-grade checks for cookie walls and accept-only banners
- **Journey Analysis** — Maps roach motels and obfuscated cancellation paths
- **Readability Engine** — Flesch-Kincaid grader for deliberately dense Terms of Service
- **Disclosure Filter** — Prevents false positives by parsing contextual legal disclosures

### 🧩 **Chrome Extension v1.1 — In-Page Highlighting**
- **Real-Time Overlays** — Detected dark patterns are outlined on the live page with severity-coded glowing borders
- **Floating Risk Badges** — Each flagged element gets a badge showing the dark pattern category
- **Interactive Legal Tooltips** — Hover to see the exact legal statute violated (GDPR Art. 13, FTC Act §5, DSA Art. 25)
- **Toggle Highlights** — One-click show/hide all overlays on the page
- **Auto-Clear on Rescan** — Highlights are automatically cleared when you scan again

### ⚙️ **Core System Intelligence**
- **Cross-Engine Consensus** — Weak signals (<0.65 confidence) are filtered by the HADE pipeline; multi-engine agreements boost the final score
- **Trust Score & Grade** — Every scan produces a 0–100 Trust Score with letter grade (A+ to F)
- **Regulatory Mapping** — Findings are mapped to GDPR, FTC ROSCA, DSA Art. 25, WCAG 2.1, and more
- **Scan History** — SQLite-backed history and analytics dashboard
- **Graceful Fault Tolerance** — Playwright handles heavy SPAs; falls back to requests on failure

### 🌐 **Web Dashboard**
- Clean, modern UI with animated radar scan and real-time results
- One-click example URLs (Booking.com, Amazon, LinkedIn, Spotify)
- Detailed findings with DOM selectors, evidence sentences, and legal citations
- Exportable scan reports

---

## 🛠️ Tech Stack

### **Backend**
- **Python** (3.9+) — Core runtime
- **Flask** (3.x) — REST API framework
- **Waitress** — Production WSGI server

### **AI & Machine Learning**
- **Scikit-Learn** — ML dark pattern classifier
- **Joblib** — Model persistence with SHA-256 integrity verification
- **Custom NLP** — 200+ hand-crafted linguistic detection patterns

### **Web Scraping**
- **Playwright** — Headless Chromium for SPA rendering and computed style extraction
- **BeautifulSoup4** — HTML parsing and DOM traversal
- **Requests** — Fallback HTTP client

### **Browser Extension**
- **Chrome Manifest V3** — Content scripts with scoped CSS overlays
- **Vanilla JS** — Zero-dependency popup and content script logic

### **Data & Security**
- **SQLite3** — Zero-config scan history and analytics database
- **Flask-Limiter** — API rate limiting
- **CSSUtils** — Visual style analysis

---

## 📋 Prerequisites

Before running this application, make sure you have:

- **Python** 3.9 or higher
- **pip** package manager
- **Google Chrome** (for the extension)

---

## 🚀 Installation & Setup

### 1️⃣ **Clone the Repository**

```bash
git clone https://github.com/Akshata1803/VigilAI.git
cd VigilAI
```

### 2️⃣ **Launch the Backend (Windows)**

Simply double-click `run.bat`. It will automatically:
- Verify your Python version
- Install all dependencies from `requirements.txt`
- Download the Playwright Chromium browser
- Start the Waitress production server

```bash
# Or run manually:
cd backend
pip install -r requirements.txt
python -m playwright install chromium
python run.py
```

### 3️⃣ **Open the Dashboard**

Navigate to **http://localhost:5000** in your browser.

### 4️⃣ **Load the Chrome Extension**

1. Open `chrome://extensions/` in Chrome
2. Enable **Developer mode** (top-right toggle)
3. Click **"Load unpacked"**
4. Select the `chrome_extension/` folder
5. Browse any website → click the Vigil AI shield icon → **Scan Current Page**

---

## 🧪 Running Tests

```bash
cd backend
python -m pytest tests/ -v --tb=short
```

Runs the full automated test suite — **339 unit tests** covering all 9 engines, HADE pipeline, aggregator, and report scoring.

---

## 📊 Dark Pattern Coverage

Vigil AI detects over **20 dark pattern categories** tied to active legislation:

| Dark Pattern | Legal Framework |
| :--- | :--- |
| Privacy Zuckering / Data Exploitation | GDPR Art. 13, CPRA §1798 |
| Forced Continuity / Subscription Traps | FTC ROSCA Act |
| Confirmshaming | FTC Act §5 |
| Targeted Visual Misdirection | WCAG 2.1, ADA Title III |
| Fake Urgency / Countdown Timers | ASA CAP Code Rule 3.1 |
| Deceptive Compound Behavioral Funnels | DSA Art. 25 |

---

## 📂 Project Structure

```text
VigilAI/
├── run.bat                        # One-click Windows launcher
├── README.md
├── chrome_extension/              # Browser Extension v1.1
│   ├── manifest.json              # Manifest V3
│   ├── popup.html / popup.js      # Extension popup UI & logic
│   ├── content.js                 # In-page DOM finder & overlay renderer
│   └── overlay.css                # Severity-coded glowing borders & tooltips
└── backend/
    ├── run.py                     # Waitress WSGI entry point
    ├── requirements.txt
    ├── static/                    # Frontend dashboard (HTML/CSS/JS)
    ├── train/                     # ML model training scripts
    ├── tests/                     # 339 automated tests
    └── app/
        ├── core/                  # Config, auth, cache, metrics
        ├── engine/                # Detection pipeline, fusion, HADE, risk scoring
        ├── analyzers/             # BaseAnalyzer contract & adapters
        ├── routes/                # REST API (/scan, /report, /analytics)
        ├── services/              # 9-engine analyzers + scanner + DB
        └── models/                # Pre-trained ML classifiers
```

---

<div align="center">
  <i>Built to enforce transparency. Deployed to protect digital autonomy.</i>
</div>
