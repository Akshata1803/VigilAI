#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Vigil AI — Git History Cleanup Script
# ═══════════════════════════════════════════════════════════════════
# USAGE:
#   1. Install git-filter-repo:  pip install git-filter-repo
#   2. Run this script from the repo root:  bash scripts/clean_git_history.sh
#   3. Force push to remote:  git push --force --all
#
# WARNING: This rewrites git history. All collaborators must re-clone.
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

echo "=== Vigil AI Git History Cleaner ==="

# Step 1: Remove sensitive files from git tracking (current index)
echo "[1/4] Removing tracked sensitive files from index..."
git rm --cached -r --ignore-unmatch \
    '*.db' '*.db-shm' '*.db-wal' '*.db-journal' \
    '*.log' \
    '*.pkl' '*.joblib' '*.h5' '*.pt' '*.onnx' \
    '**/__pycache__/' \
    'backend/test_results.json' \
    'backend/import_test.txt' \
    '.pytest_cache/' \
    2>/dev/null || true

# Step 2: Scrub from entire git history
echo "[2/4] Scrubbing sensitive files from git history..."
# If git-filter-repo is available, use it (preferred)
if command -v git-filter-repo &> /dev/null; then
    git filter-repo --invert-paths \
        --path-glob '*.db' \
        --path-glob '*.db-shm' \
        --path-glob '*.db-wal' \
        --path-glob '*.log' \
        --path-glob '*.pkl' \
        --path-glob '*.joblib' \
        --path-glob '*.h5' \
        --path-glob '*.pt' \
        --path-glob '**/__pycache__/' \
        --path 'backend/test_results.json' \
        --path 'backend/import_test.txt' \
        --force
    echo "  -> git-filter-repo completed successfully."
else
    echo "  -> git-filter-repo not found. Install with: pip install git-filter-repo"
    echo "  -> Falling back to BFG-style git filter-branch..."
    git filter-branch --force --index-filter \
        'git rm --cached --ignore-unmatch *.db *.log *.pkl *.joblib *.h5 *.pt' \
        --prune-empty -- --all
fi

# Step 3: Clean up refs and GC
echo "[3/4] Cleaning up unreachable objects..."
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Step 4: Verify
echo "[4/4] Verifying no sensitive files remain in history..."
for ext in db log pkl joblib h5 pt; do
    count=$(git log --all --diff-filter=A --name-only --format="" -- "*.$ext" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        echo "  WARNING: Found $count .$ext file(s) still in history"
    else
        echo "  OK: No .$ext files in history"
    fi
done

echo ""
echo "=== Cleanup complete ==="
echo "Run 'git push --force --all' to update remote."
echo "WARNING: All collaborators must re-clone after force push."
