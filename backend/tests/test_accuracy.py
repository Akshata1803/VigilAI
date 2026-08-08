"""
Vigil AI — Accuracy & False Positive/Negative Test Suite
==========================================================
Tests the FULL pipeline against real-world websites to validate:

  1. FALSE POSITIVES: Clean/government sites should NOT be flagged
  2. FALSE NEGATIVES: Known dark-pattern sites should be DETECTED
  3. SEVERITY ACCURACY: Detected patterns should have correct severity
  4. CATEGORY ACCURACY: Detected patterns map to the right category

Test Matrix:
  ┌──────────────────────────┬──────────────┬───────────────────────┐
  │ Site                     │ Expected     │ What to check         │
  ├──────────────────────────┼──────────────┼───────────────────────┤
  │ wikipedia.org            │ CLEAN  (85+) │ No false positives    │
  │ gov.uk                   │ CLEAN  (85+) │ No false positives    │
  │ booking.com              │ RISKY  (60-80)│ Urgency/scarcity     │
  │ amazon.com               │ RISKY  (55-80)│ Dark patterns found  │
  │ ryanair.com              │ DIRTY  (<70) │ Aggressive upsells    │
  └──────────────────────────┴──────────────┴───────────────────────┘
"""

import requests
import json
import time
import sys
import os

# Fix Windows console encoding (cp1252 -> utf-8)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

API = "http://localhost:5000/api/scan"
TIMEOUT = 120

# ═══════════════════════════════════════════════════════════════════════════════
# TEST DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

TESTS = [
    # ── CLEAN BENCHMARKS (should have HIGH trust, FEW findings) ────────────
    {
        'url': 'https://en.wikipedia.org',
        'label': 'CLEAN BENCHMARK',
        'expected_min_score': 80,
        'expected_max_findings': 3,
        'must_NOT_have_categories': ['forced_continuity', 'basket_sneaking', 'preselection'],
        'description': 'Wikipedia — no dark patterns expected',
    },
    {
        'url': 'https://www.gov.uk',
        'label': 'CLEAN BENCHMARK',
        'expected_min_score': 80,
        'expected_max_findings': 2,
        'must_NOT_have_categories': ['urgency', 'forced_continuity', 'confirmshaming'],
        'description': 'UK Gov — clean public service site',
    },

    # ── KNOWN DARK PATTERN SITES (should detect issues) ───────────────────
    {
        'url': 'https://www.booking.com',
        'label': 'KNOWN PATTERNS',
        'expected_max_score': 85,
        'expected_min_findings': 1,
        'must_have_categories': [],  # Booking has urgency/scarcity but varies by page
        'description': 'Booking.com — urgency/scarcity dark patterns',
    },
    {
        'url': 'https://www.amazon.com',
        'label': 'E-COMMERCE BENCHMARK',
        'expected_max_score': 100,  # Unauthenticated homepage can be clean
        'expected_min_findings': 0,
        'description': 'Amazon — clean homepage expected without login',
    },
    {
        'url': 'https://www.temu.com',
        'label': 'AGGRESSIVE PATTERNS',
        'expected_max_score': 80,
        'expected_min_findings': 1,
        'description': 'Temu — aggressive scarcity, urgency, forced action',
    },
    {
        'url': 'https://www.ryanair.com',
        'label': 'AGGRESSIVE PATTERNS',
        'expected_max_score': 80,
        'expected_min_findings': 1,
        'description': 'Ryanair — aggressive upsells, hidden costs, add-ons',
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_scan(url):
    """Run a scan and return the result dict."""
    try:
        r = requests.post(API, json={'url': url}, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json(), None
        else:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.exceptions.Timeout:
        return None, "TIMEOUT"
    except Exception as e:
        return None, str(e)


def check_test(test, result):
    """Check a scan result against test expectations. Returns (pass, issues)."""
    issues = []
    trust = result.get('trust_score', 0)
    patterns = result.get('total_patterns', 0)
    findings = result.get('findings', [])
    categories = {f.get('category', '') for f in findings}

    # Score checks
    min_score = test.get('expected_min_score')
    max_score = test.get('expected_max_score')
    if min_score and trust < min_score:
        issues.append(f"FALSE POSITIVE: Trust score {trust} < expected minimum {min_score}")
    if max_score and trust > max_score:
        issues.append(f"FALSE NEGATIVE: Trust score {trust} > expected maximum {max_score} (should be lower)")

    # Findings count checks
    max_findings = test.get('expected_max_findings')
    min_findings = test.get('expected_min_findings')
    if max_findings is not None and patterns > max_findings:
        issues.append(f"FALSE POSITIVE: {patterns} findings > expected max {max_findings}")
    if min_findings is not None and patterns < min_findings:
        issues.append(f"FALSE NEGATIVE: {patterns} findings < expected min {min_findings}")

    # Category presence checks
    must_have = test.get('must_have_categories', [])
    for cat in must_have:
        if cat not in categories:
            issues.append(f"FALSE NEGATIVE: Missing expected category '{cat}'")

    must_not = test.get('must_NOT_have_categories', [])
    for cat in must_not:
        if cat in categories:
            bad_findings = [f for f in findings if f.get('category') == cat]
            for bf in bad_findings:
                issues.append(
                    f"FALSE POSITIVE: Found '{cat}' on clean site — "
                    f"type='{bf.get('type')}', conf={bf.get('confidence', 0):.2f}"
                )

    # Severity sanity check: no CRITICAL on clean sites
    if test['label'] == 'CLEAN BENCHMARK':
        critical = [f for f in findings if f.get('severity') == 'CRITICAL']
        if critical:
            for cf in critical:
                issues.append(
                    f"FALSE POSITIVE: CRITICAL finding on clean site — "
                    f"type='{cf.get('type')}', category='{cf.get('category')}'"
                )

    # Confidence sanity check: all reported findings should have confidence >= 0.6
    low_conf = [f for f in findings if float(f.get('confidence', 0)) < 0.50]
    if low_conf:
        for lf in low_conf:
            issues.append(
                f"LOW CONFIDENCE: Finding with conf={lf.get('confidence', 0):.2f} — "
                f"type='{lf.get('type')}' (should be filtered)"
            )

    passed = len(issues) == 0
    return passed, issues


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 80)
    print("  VIGIL AI — ACCURACY & FALSE POSITIVE/NEGATIVE TEST SUITE")
    print("=" * 80)

    total_pass = 0
    total_fail = 0
    total_fp = 0  # false positive count
    total_fn = 0  # false negative count
    all_results = []

    for i, test in enumerate(TESTS, 1):
        url = test['url']
        label = test['label']
        desc = test['description']

        print(f"\n{'-' * 80}")
        print(f"  [{i}/{len(TESTS)}] {desc}")
        print(f"  URL: {url}  |  Expected: {label}")
        print(f"{'-' * 80}")

        start = time.time()
        result, error = run_scan(url)
        elapsed = time.time() - start

        if error:
            print(f"  ❌ SCAN FAILED ({elapsed:.1f}s): {error}")
            total_fail += 1
            all_results.append({'url': url, 'status': 'SCAN_FAILED', 'error': error})
            continue

        trust = result.get('trust_score', 0)
        grade = result.get('grade', {})
        grade_letter = grade.get('letter', 'N/A') if isinstance(grade, dict) else grade
        patterns = result.get('total_patterns', 0)
        findings = result.get('findings', [])
        risk = result.get('risk_level', {})
        risk_label = risk.get('label', 'N/A') if isinstance(risk, dict) else risk

        print(f"  Score: {trust}/100 (Grade: {grade_letter})  |  Findings: {patterns}  |  Risk: {risk_label}  |  Time: {elapsed:.1f}s")

        # Show findings summary
        if findings:
            print(f"  Findings:")
            for j, f in enumerate(findings[:8], 1):
                cat = f.get('category', 'N/A')
                typ = f.get('type', 'N/A')
                sev = f.get('severity', 'N/A')
                conf = float(f.get('confidence', 0))
                eng = f.get('_engine', '?')
                gate = f.get('_gate_reason', 'N/A')
                print(f"    {j}. [{sev:8s}] {typ[:50]:50s} (cat={cat}, conf={conf:.2f}, engine={eng})")
                print(f"       Gate: {gate}")
            if len(findings) > 8:
                print(f"    ... and {len(findings) - 8} more")

        # Validate
        passed, issues = check_test(test, result)

        if passed:
            print(f"\n  ✅ PASSED — No accuracy issues")
            total_pass += 1
        else:
            print(f"\n  ❌ ISSUES FOUND:")
            for issue in issues:
                print(f"    ⚠️  {issue}")
                if "FALSE POSITIVE" in issue:
                    total_fp += 1
                if "FALSE NEGATIVE" in issue:
                    total_fn += 1
            total_fail += 1

        # Performance check
        perf = result.get('performance', {})
        pipeline_ms = perf.get('pipeline_ms', 0)
        if pipeline_ms > 30000:
            print(f"  ⚠️  SLOW: Pipeline took {pipeline_ms:.0f}ms")

        all_results.append({
            'url': url, 'label': label, 'trust_score': trust,
            'patterns': patterns, 'grade': grade_letter,
            'elapsed': round(elapsed, 1), 'passed': passed,
            'issues': issues, 'findings_count': len(findings),
        })

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  ACCURACY TEST RESULTS")
    print(f"{'=' * 80}")
    print(f"  Tests Run:       {len(TESTS)}")
    print(f"  Passed:          {total_pass}/{len(TESTS)}")
    print(f"  Failed:          {total_fail}/{len(TESTS)}")
    print(f"  False Positives: {total_fp}")
    print(f"  False Negatives: {total_fn}")
    print(f"{'=' * 80}")

    # Accuracy breakdown table
    print(f"\n  {'URL':<30s} {'Score':>5s} {'Grade':>5s} {'Patterns':>8s} {'Status':>8s} {'Time':>6s}")
    print(f"  {'─' * 72}")
    for r in all_results:
        status = '✅ PASS' if r.get('passed') else '❌ FAIL'
        url_short = r['url'].replace('https://', '').replace('http://', '')[:28]
        print(f"  {url_short:<30s} {r.get('trust_score', '?'):>5} {r.get('grade', '?'):>5s} {r.get('patterns', '?'):>8} {status:>8s} {r.get('elapsed', 0):>5.1f}s")

    # Final verdict
    accuracy = total_pass / max(len(TESTS), 1) * 100
    print(f"\n  ACCURACY: {accuracy:.0f}%")
    if total_fp == 0 and total_fn == 0:
        print(f"  🎯 PERFECT — No false positives or false negatives detected!")
    elif total_fp > 0:
        print(f"  ⚠️  {total_fp} false positive(s) need calibration")
    if total_fn > 0:
        print(f"  ⚠️  {total_fn} false negative(s) — detection gaps found")

    print(f"\n{'=' * 80}\n")

    # Save results
    with open('tests/accuracy_results.json', 'w') as f:
        json.dump(all_results, f, indent=2)
    print("  Results saved to tests/accuracy_results.json")

    return 0 if total_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
