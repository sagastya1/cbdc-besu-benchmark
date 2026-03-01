# CBDC Benchmark: PoA vs QBFT on Hyperledger Besu
### Automated, reproducible evaluation of CBDC transaction performance

---

## 📁 Folder Structure

```
cbdc-besu-benchmark/
│
├── contracts/
│   └── CBDC.sol                 ← Solidity CBDC token contract
│
├── config/
│   ├── genesis-poa.json         ← Clique (PoA) genesis block config
│   └── genesis-qbft.json        ← QBFT genesis block config
│
├── scripts/
│   ├── setup_network.sh         ← Download Besu, start node (poa/qbft)
│   └── push_results.sh          ← Commit & push results to GitHub
│
├── benchmark/
│   ├── benchmark_client.py      ← Deploy contract, replay dataset, measure metrics
│   ├── monitor.py               ← Real-time node metrics collector
│   └── generate_graphs.py       ← CSV + chart generator
│
├── notebooks/
│   └── CBDC_Benchmark_PoA_vs_QBFT.ipynb   ← Master Colab notebook
│
├── results/                     ← Auto-created, stores all outputs
│   ├── metrics_poa.json
│   ├── metrics_qbft.json
│   ├── latencies_poa.csv
│   ├── latencies_qbft.csv
│   ├── block_times_poa.csv
│   ├── block_times_qbft.csv
│   ├── comparison_summary.csv
│   └── graphs/
│       ├── dashboard.png
│       ├── tps_comparison.png
│       ├── latency_cdf.png
│       └── block_times.png
│
├── FinalDataset.xlsx            ← Your real transaction dataset
├── run_benchmark.sh             ← Master one-command run script
└── README.md
```

---

## 🚀 Step-by-Step Colab Usage Guide

### Step 0: Fork / Push to GitHub

1. Create a new GitHub repo: `your-username/cbdc-besu-benchmark`
2. Push this folder:
   ```bash
   git init
   git add .
   git commit -m "Initial benchmark framework"
   git remote add origin https://github.com/your-username/cbdc-besu-benchmark.git
   git push -u origin main
   ```

---

### Step 1: Open Colab

1. Go to [colab.research.google.com](https://colab.research.google.com)
2. Click **File → Open Notebook → GitHub**
3. Paste: `https://github.com/your-username/cbdc-besu-benchmark`
4. Open: `notebooks/CBDC_Benchmark_PoA_vs_QBFT.ipynb`

> **Runtime:** Use default CPU runtime. GPU/TPU not needed.

---

### Step 2: (Optional) Set GitHub Secrets

To auto-push results back to GitHub:

1. Click the 🔑 **Secrets** icon in the Colab left sidebar
2. Add secrets:
   - `GITHUB_TOKEN` → your Personal Access Token (repo scope)
   - `GITHUB_REPO`  → `your-username/cbdc-besu-benchmark`

---

### Step 3: Run Cells in Order

| Cell | Action | Time |
|------|--------|------|
| **Cell 1** | Install Java 21, Python packages, download Besu | ~3 min |
| **Cell 2** | Clone repo, upload `FinalDataset.xlsx` | ~1 min |
| **Cell 3** | Run full benchmark (PoA + QBFT) | ~10-15 min |
| **Cell 4** | Display results & graphs | instant |
| **Cell 5** | Download results as ZIP | instant |
| **Cell 6** | Push results to GitHub | ~1 min |

---

### Step 4: Customize Parameters

In **Cell 3**, adjust these variables before running:

```python
TXNS = 500    # Number of transactions (500–5000 recommended)
TPS  = 50     # TPS controller cap (10–200)
PUSH = False  # True = auto-push results to GitHub
```

---

### Step 5: Interpret Results

After Cell 4, you'll see:

- **TPS Comparison** — Which consensus is faster
- **Latency CDF** — P50/P95 latency distribution
- **Block Time Distribution** — Consistency of block production
- **Summary Dashboard** — All key metrics side-by-side

**Quick interpretation guide:**

| Metric | PoA (Clique) | QBFT |
|--------|-------------|------|
| TPS | Higher (no BFT overhead) | Slightly lower |
| Finality | Probabilistic | Deterministic (immediate) |
| Latency | Lower avg | Consistent (low variance) |
| Block Time | Configurable | Configurable |
| Fault Tolerance | Majority honest | 1/3 Byzantine |

---

## 🔧 Direct Command-Line Usage

```bash
# Full benchmark (both networks)
bash run_benchmark.sh --txns 500 --tps 50

# With GitHub push
bash run_benchmark.sh --txns 1000 --tps 100 --push

# PoA only
bash scripts/setup_network.sh poa
python3 benchmark/benchmark_client.py --network poa --port 8545 --txns 500

# QBFT only  
bash scripts/setup_network.sh qbft
python3 benchmark/benchmark_client.py --network qbft --port 8546 --txns 500

# Generate graphs from existing results
python3 benchmark/generate_graphs.py

# Monitor a running node
python3 benchmark/monitor.py --network poa --port 8545 --duration 120
```

---

## 📊 Output Files

| File | Description |
|------|-------------|
| `results/metrics_{network}.json` | All metrics in JSON |
| `results/latencies_{network}.csv` | Per-tx latency data |
| `results/block_times_{network}.csv` | Per-block timing |
| `results/comparison_summary.csv` | Side-by-side comparison |
| `results/graphs/dashboard.png` | 4-panel summary chart |
| `results/graphs/tps_comparison.png` | TPS bar chart |
| `results/graphs/latency_cdf.png` | Latency CDF curves |
| `results/graphs/block_times.png` | Block time histograms |

---

## ⚡ TPS Controller

The benchmark uses a **token-bucket TPS controller** (`TPSController` class) to cap send rate. This prevents overwhelming the node and allows fair comparison:

```python
controller = TPSController(target_tps=50)
for tx in transactions:
    controller.wait()   # sleeps to maintain target rate
    send_transaction(tx)
```

Adjust `--tps` to test different load profiles.

---

## 🏗️ Architecture

```
Google Colab Runtime
│
├── Besu Node (PoA/Clique) :8545
│   └── CBDC Contract (deployed)
│
├── Besu Node (QBFT) :8546
│   └── CBDC Contract (deployed)
│
├── Benchmark Client (Python/web3.py)
│   ├── Reads FinalDataset.xlsx
│   ├── Controls TPS via token bucket
│   ├── Sends mint/transfer txns
│   └── Records latency per tx
│
├── Monitor (background)
│   └── Polls block data → CSV
│
└── Graph Generator
    └── matplotlib → PNG charts
```

---

## 📋 Requirements

- Google Colab (free tier works)
- GitHub account (for clone/push)
- `FinalDataset.xlsx` (your transaction dataset)
- No local setup needed!
