#!/bin/bash
# =============================================================
# run_benchmark.sh — Master orchestration script
# One command to rule them all.
# Usage: bash run_benchmark.sh [--txns 500] [--tps 50] [--push]
# =============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TXNS=500
TPS=50
PUSH_RESULTS=false
DATASET="${SCRIPT_DIR}/FinalDataset.xlsx"

# ── Parse args ─────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --txns)  TXNS="$2";  shift 2 ;;
    --tps)   TPS="$2";   shift 2 ;;
    --push)  PUSH_RESULTS=true; shift ;;
    --dataset) DATASET="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

cd "${SCRIPT_DIR}"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   CBDC Blockchain Benchmark: PoA vs QBFT        ║"
echo "║   Txns: ${TXNS}  |  TPS Cap: ${TPS}            ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Install Python dependencies ───────────────────────────────────────
echo "==> [1/7] Installing Python dependencies..."
pip install -q web3 py-solc-x pandas openpyxl matplotlib numpy --break-system-packages 2>/dev/null || \
pip install -q web3 py-solc-x pandas openpyxl matplotlib numpy

# ── Step 2: Install Java & Besu ───────────────────────────────────────────────
echo "==> [2/7] Setting up Java & Besu..."
bash "${SCRIPT_DIR}/scripts/setup_network.sh" poa
echo ""

echo "==> [3/7] Starting QBFT network..."
bash "${SCRIPT_DIR}/scripts/setup_network.sh" qbft
echo ""

# ── Step 3: Run PoA benchmark ─────────────────────────────────────────────────
echo "==> [4/7] Running PoA (Clique) benchmark..."
python3 "${SCRIPT_DIR}/benchmark/benchmark_client.py" \
  --network poa \
  --port 8545 \
  --txns "${TXNS}" \
  --tps "${TPS}" \
  --dataset "${DATASET}" \
  --contract "${SCRIPT_DIR}/contracts/CBDC.sol"

echo ""

# ── Step 4: Run QBFT benchmark ────────────────────────────────────────────────
echo "==> [5/7] Running QBFT benchmark..."
python3 "${SCRIPT_DIR}/benchmark/benchmark_client.py" \
  --network qbft \
  --port 8546 \
  --txns "${TXNS}" \
  --tps "${TPS}" \
  --dataset "${DATASET}" \
  --contract "${SCRIPT_DIR}/contracts/CBDC.sol"

echo ""

# ── Step 5: Generate graphs ───────────────────────────────────────────────────
echo "==> [6/7] Generating comparison graphs..."
python3 "${SCRIPT_DIR}/benchmark/generate_graphs.py"

# ── Step 6: Stop Besu nodes ───────────────────────────────────────────────────
echo "==> Stopping Besu nodes..."
for NET in poa qbft; do
  PID_FILE="/tmp/besu-${NET}.pid"
  if [ -f "${PID_FILE}" ]; then
    kill $(cat "${PID_FILE}") 2>/dev/null || true
    rm -f "${PID_FILE}"
    echo "    Stopped ${NET} node"
  fi
done

# ── Step 7: Push to GitHub (optional) ─────────────────────────────────────────
if [ "${PUSH_RESULTS}" = true ]; then
  echo "==> [7/7] Pushing results to GitHub..."
  bash "${SCRIPT_DIR}/scripts/push_results.sh"
else
  echo "==> [7/7] Skipping GitHub push (use --push to enable)"
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   ✓ Benchmark COMPLETE                          ║"
echo "║   Results: ./results/                           ║"
echo "║   Graphs:  ./results/graphs/                    ║"
echo "╚══════════════════════════════════════════════════╝"
