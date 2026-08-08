<div align="center">
  
# 🛡️ DarkGuard: Vigil AI
  
**An Enterprise-Grade Dark Pattern Detection Engine & ML Privacy Guardian**

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Framework: Flask](https://img.shields.io/badge/framework-Flask-lightgrey.svg)](https://flask.palletsprojects.com/)
[![ML: scikit-learn](https://img.shields.io/badge/ML-scikit--learn-orange.svg)](https://scikit-learn.org/)

</div>

---

## 📖 Overview

**DarkGuard Vigil AI** is an advanced, multi-engine cybersecurity tool designed to protect users from **dark patterns** — deceptive digital design practices that manipulate, trick, or coerce users into unintended actions online. 

Moving far beyond simple regex scraping, Vigil AI features a live **9-engine architecture**, integrating Scikit-Learn Machine Learning, Natural Language Processing (NLP), structural DOM analysis, cross-engine consensus filtering, and exact regulatory mapping to identify UI violations dynamically.

Whether running via a localized web application or integrated into a continuous CI/CD pipeline, DarkGuard Vigil AI sets a new standard for enforcing transparency and protecting digital autonomy.

---

## ✨ Enterprise-Grade Architecture

### 9-Engine AI Detection Pipeline
Every dark pattern scan runs through a comprehensive, asynchronous suite:

*   🤖 **ML Classifier** — Trained Scikit-Learn logistic regression models detecting deceptive text tonalities.
*   🧬 **DOM Analysis** — Deep structural checks capturing pre-checked hidden boxes, drip pricing, and un-closable popups.
*   🧠 **NLP Engine** — Over 200 linguistic patterns (spaCy-driven) checking for confirmshaming, FUD (Fear/Uncertainty/Doubt), and trick questions.
*   🎨 **Visual Analyzer** — Reads computed styles for color contrast manipulation, disguised ads, and deceptive button styling.
*   🛡️ **Elite Privacy Filter** — Detects invasive tracking mechanisms like session replays, fingerprinting, and non-essential data brokering.
*   📝 **Disclosure Language Filter** — An AI validation edge that parses contextual disclosures (e.g., "interest-based advertising") as informational, preventing false positives.
*   🍪 **Consent Auditor** — GDPR-grade checks for absolute cookie walls and accept-only banners.
*   🔗 **Journey Analysis (Roach Motels)** — Maps dead-ends and intentionally obfuscated cancellation paths.
*   📖 **Readability Engine** — Flesch-Kincaid complexity grader targeted at deliberately dense Terms of Service and Privacy Policies.

### System Intelligence
*   **Cross-Engine Consensus** — Raw findings dynamically aggregate; weak signals (<0.65 confidence) are dropped, and multi-engine agreements naturally boost the final score.
*   **Contextual Evidence Mapping** — Results provide DOM selectors and the exact sentence context surrounding the dark pattern finding.
*   **Graceful Fault Tolerance** — A robust Playwright backend bypasses captchas and handles heavy Single Page Applications (SPAs) with intelligent cascading timeouts.

---

## 🚀 Quick Start (Windows)

Vigil AI is engineered to be fully self-contained. You can deploy it locally in minutes.

### Standard Launch

1.  Clone this repository or extract the project zip.
2.  Double-click the `run.bat` deployer.
3.  The launcher automatically:
    *   Verifies your Python 3.9+ runtime environment.
    *   Installs dependencies mapping (`scikit-learn`, `playwright`, `spacy`).
    *   Downloads and provisions the spaCy `en_core_web_sm` language models.
    *   Initiates the backend Waitress WSGI production server.
4.  Navigate to `http://localhost:5000` to access the local dashboard.

### 🧪 Running the Test Suite

```bash
cd backend
python -m pytest tests/ -v --tb=short
```

This runs the full automated test suite (300+ unit tests covering all 9 engines, HADE pipeline, aggregator, and report scoring).

---

## 🛠️ The Technology Stack

| Architecture Layer | Core Technologies |
| :--- | :--- |
| **Backend API** | Python 3.9+, Flask, Waitress WSGI |
| **Web Scraping** | Playwright (Headless Chromium), Requests, BeautifulSoup4 |
| **Machine Learning** | Scikit-Learn, Joblib (Model Persistence), spaCy |
| **Visual Processing** | CSSUtils, Playwright Computed Styles |
| **Data Persistence** | SQLite3 (Zero-Config DB for History & Analytics) |
| **Frontend UI** | HTML5, CSS3 Variables, Vanilla JS (Zero-bloat integration) |

---

## 📊 Comprehensive Dark Pattern Coverage

Vigil AI maps its detections against over twenty distinct categories directly tied to active legislation and regulatory guidelines, including:

1.  **Privacy Zuckering / Data Exploitation** *(GDPR Art. 13, CPRA §1798)*
2.  **Forced Continuity / Subscription Traps** *(FTC ROSCA Act)*
3.  **Confirmshaming** *(FTC Act §5 — Unfair or Deceptive Acts)*
4.  **Targeted Visual Misdirection** *(WCAG 2.1, ADA Title III)*
5.  **Fake Urgency / Countdown Timers** *(ASA CAP Code Rule 3.1)*
6.  **Deceptive Compound Behavioral Funnels** *(DSA Art. 25)*

---

## 📂 Project Structure

```text
VigilAI/
├── run.bat                        # One-click Windows deployment script
├── README.md                      # Project documentation
├── chrome_extension/              # Browser extension for live detection
│   ├── manifest.json
│   ├── popup.html
│   └── popup.js
└── backend/
    ├── run.py                     # Waitress WSGI production server entry point
    ├── requirements.txt           # Python dependencies
    ├── pytest.ini                 # Test runner configuration
    ├── static/                    # Frontend (HTML/CSS/JS)
    │   ├── index.html
    │   ├── css/styles.css
    │   └── js/app.js
    ├── train/                     # ML model training scripts & datasets
    ├── tests/                     # Automated test suites (300+ tests)
    │   ├── test_unit.py           # Primary: 25 test classes
    │   ├── test_suite.py          # Secondary: analyzer-level tests
    │   ├── test_comprehensive.py  # 100+ FP/FN edge cases
    │   └── test_production.py     # Infrastructure & performance
    └── app/                       # Application core
        ├── __init__.py            # Flask app factory
        ├── worker.py              # Async ThreadPoolExecutor task worker
        ├── tasks.py               # Task submission interface
        ├── extensions.py          # Rate limiter, logging, IP extraction
        ├── core/                  # Infrastructure (config, auth, cache, metrics)
        ├── engine/                # Detection pipeline, fusion, risk assessment
        ├── analyzers/             # BaseAnalyzer contract & adapter layer
        ├── routes/                # REST API endpoints (/scan, /report, etc.)
        ├── services/              # 9-engine analysis + supporting services
        └── models/                # Pre-trained ML classifiers (.pkl)
```

---

<div align="center">
  <i>Built to enforce transparency. Deployed to protect digital autonomy.</i>
</div>
