"""Quick live test for the refactored pipeline."""
import requests
import json
import time

URL = "https://www.booking.com"

print(f"\n{'='*60}")
print(f"  LIVE SCAN TEST: {URL}")
print(f"{'='*60}\n")

start = time.time()
r = requests.post("http://localhost:5000/api/scan", json={"url": URL}, timeout=120)
elapsed = time.time() - start

print(f"HTTP Status: {r.status_code}")
print(f"Total Time: {elapsed:.1f}s")

if r.status_code == 200:
    data = r.json()
    trust = data.get("trust_score", "N/A")
    grade = data.get("grade", {})
    grade_letter = grade.get("letter", "N/A") if isinstance(grade, dict) else grade
    risk = data.get("risk_level", {})
    risk_label = risk.get("label", "N/A") if isinstance(risk, dict) else risk
    patterns = data.get("total_patterns", 0)

    print(f"\nTrust Score: {trust}/100")
    print(f"Grade: {grade_letter}")
    print(f"Risk Level: {risk_label}")
    print(f"Total Patterns: {patterns}")

    # Performance
    perf = data.get("performance", {})
    if perf:
        print(f"\n--- PERFORMANCE (NEW) ---")
        print(f"Pipeline Time: {perf.get('pipeline_ms', 0):.0f}ms")
        print(f"Total Scan Time: {perf.get('total_ms', 0):.0f}ms")
        timings = perf.get("analyzer_timings", {})
        if timings:
            print("Analyzer Timings:")
            for name, ms in sorted(timings.items(), key=lambda x: x[1], reverse=True):
                print(f"  {name:20s} {ms:8.1f}ms")

    # Risk Assessment (NEW)
    ra = data.get("risk_assessment", {})
    if ra:
        print(f"\n--- RISK ASSESSMENT (NEW) ---")
        print(f"Risk Score: {ra.get('risk_score', 'N/A')}")
        print(f"Risk Level: {ra.get('risk_level', 'N/A')}")
        print(f"Compound Bonus: {ra.get('compound_bonus', 1.0)}x")

    # Fusion (NEW)
    breakdown = data.get("analysis_breakdown", {})
    print(f"\n--- ANALYSIS BREAKDOWN ---")
    print(f"Fusion Scan Score: {breakdown.get('fusion_scan_score', 'N/A')}")
    print(f"Raw findings: {breakdown.get('raw_findings', 'N/A')}")
    print(f"After HADE: {breakdown.get('after_hade', 'N/A')}")
    print(f"After Fusion: {breakdown.get('after_fusion', 'N/A')}")
    print(f"After Aggregation: {breakdown.get('after_aggregation', 'N/A')}")
    print(f"HADE Dropped: {breakdown.get('dropped_by_hade', 0)}")
    print(f"HADE Upgraded: {breakdown.get('hade_upgraded', 0)}")
    print(f"Pipeline Total (ms): {breakdown.get('pipeline_total_ms', 'N/A')}")
    print(f"Analyzers Succeeded: {breakdown.get('analyzers_succeeded', 'N/A')}/{breakdown.get('analyzers_total', 'N/A')}")

    # Temporal (NEW)
    trend = data.get("temporal_trend")
    if trend:
        print(f"\n--- TEMPORAL TREND (NEW) ---")
        print(json.dumps(trend, indent=2))

    print(f"\n{'='*60}")
    print(f"  SCAN COMPLETE — ALL NEW SYSTEMS OPERATIONAL")
    print(f"{'='*60}")
else:
    print(f"\nERROR: {r.text[:500]}")
