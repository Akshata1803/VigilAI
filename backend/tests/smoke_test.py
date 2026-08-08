import requests
import sys

BASE = 'http://localhost:5000/api'
results = []

def check(name, resp, expected_status):
    ok = resp.status_code == expected_status
    results.append((name, ok, resp.status_code))
    status = 'PASS' if ok else 'FAIL'
    print(f'  [{status}] {name}: HTTP {resp.status_code}')
    if not ok:
        print(f'         Body: {resp.text[:120]}')

print()
print('=' * 55)
print('  VIGIL AI v3 - SMOKE TEST')
print('=' * 55)

# Health
r = requests.get(f'{BASE}/health', timeout=5)
check('GET /health', r, 200)

# Readiness
r = requests.get(f'{BASE}/ready', timeout=5)
check('GET /ready', r, 200)

# Validation: missing URL -> 400
r = requests.post(f'{BASE}/scan', json={}, timeout=5)
check('POST /scan (no URL) -> 400', r, 400)

# Validation: bad scheme -> 400
r = requests.post(f'{BASE}/scan', json={'url': 'file:///etc/passwd'}, timeout=5)
check('POST /scan (file://) -> 400', r, 400)

# Validation: ftp blocked -> 400
r = requests.post(f'{BASE}/scan', json={'url': 'ftp://files.example.com'}, timeout=5)
check('POST /scan (ftp://) -> 400', r, 400)

# Metrics (dev mode, no API key set)
r = requests.get(f'{BASE}/metrics', timeout=5)
check('GET /metrics (dev mode)', r, 200)

# Stats
r = requests.get(f'{BASE}/stats', timeout=5)
check('GET /stats', r, 200)

# Cache invalidate
r = requests.post(f'{BASE}/scan/cache/invalidate', json={'url': 'https://example.com'}, timeout=5)
check('POST /scan/cache/invalidate', r, 200)

# Bad scan ID
r = requests.get(f'{BASE}/scan/NOTEXIST', timeout=5)
check('GET /scan/NOTEXIST -> 404', r, 404)

print()
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f'  Result: {passed}/{total} passed')
print('=' * 55)
sys.exit(0 if passed == total else 1)
