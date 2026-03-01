#!/bin/bash
# =============================================================
# push_results.sh — Commit and push benchmark results to GitHub
# Configure GITHUB_TOKEN and REPO in Colab secrets or env vars
# =============================================================

REPO="${GITHUB_REPO:-your-username/cbdc-besu-benchmark}"
TOKEN="${GITHUB_TOKEN:-}"
BRANCH="results/$(date +%Y%m%d-%H%M%S)"

if [ -z "${TOKEN}" ]; then
  echo "[!] GITHUB_TOKEN not set. Skipping push."
  echo "    Set it with: export GITHUB_TOKEN=ghp_yourtoken"
  exit 0
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Configure git
git config --global user.email "benchmark@cbdc-eval.local"
git config --global user.name  "CBDC Benchmark Bot"

# Set remote with token auth
git remote set-url origin "https://${TOKEN}@github.com/${REPO}.git" 2>/dev/null || \
git remote add origin "https://${TOKEN}@github.com/${REPO}.git"

# Create results branch
git checkout -b "${BRANCH}" 2>/dev/null || git checkout "${BRANCH}"

# Stage results
git add results/ 2>/dev/null || true

SUMMARY=""
if [ -f "results/comparison_summary.csv" ]; then
  SUMMARY=$(cat results/comparison_summary.csv | head -5)
fi

git commit -m "Benchmark results $(date '+%Y-%m-%d %H:%M UTC')

TXN Dataset: FinalDataset.xlsx
$(cat results/metrics_poa.json 2>/dev/null | python3 -c "import sys,json; m=json.load(sys.stdin); print(f'PoA TPS: {m[\"actual_tps\"]} | Latency: {m[\"avg_latency_s\"]*1000:.1f}ms')" 2>/dev/null || echo 'PoA: N/A')
$(cat results/metrics_qbft.json 2>/dev/null | python3 -c "import sys,json; m=json.load(sys.stdin); print(f'QBFT TPS: {m[\"actual_tps\"]} | Latency: {m[\"avg_latency_s\"]*1000:.1f}ms')" 2>/dev/null || echo 'QBFT: N/A')
" 2>/dev/null || echo "[push] Nothing new to commit"

git push origin "${BRANCH}" 2>/dev/null && \
  echo "[+] Results pushed to branch: ${BRANCH}" || \
  echo "[!] Push failed. Check your GITHUB_TOKEN and repo permissions."
