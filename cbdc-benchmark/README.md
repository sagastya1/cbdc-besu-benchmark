# CBDC Benchmark Framework
## Hyperledger Besu — PoA (Clique) vs QBFT Performance Evaluation

> **Thesis-ready, AWS-native, one-command deployment**

---

## Architecture

```
CloudShell / GitHub Actions
        │
        ▼
  CloudFormation ──► VPC + Subnets + SGs
        │
        ├── EC2 t3.medium × 1 (Benchmark Client)
        │       └── Docker: 4× Besu validator containers
        │       └── Python: workload-loader, metrics-collector
        │
        └── S3 Bucket
                ├── dataset/FinalDataset.xlsx
                └── results/<run-id>/
                        ├── PoA/summary.json
                        ├── PoA/raw_transactions.csv
                        ├── QBFT/summary.json
                        ├── QBFT/raw_transactions.csv
                        └── reports/
                                ├── 01_metrics_comparison.png
                                ├── 02_latency_distribution.png
                                ├── 03_latency_timeline.png
                                ├── 04_summary_dashboard.png
                                ├── comparison_report.csv
                                └── comparison_report.json
```

**CloudWatch** receives real-time metrics (TPS, latency, success rate) from the benchmarker.

---

## Quick Start (AWS CloudShell)

### Step 1 — Connect GitHub in CloudShell
```bash
# Option A: HTTPS with PAT
git config --global user.email "you@example.com"
git config --global user.name "Your Name"
git clone https://<YOUR_PAT>@github.com/<username>/cbdc-benchmark.git
cd cbdc-benchmark

# Option B: SSH
mkdir -p ~/.ssh
ssh-keygen -t ed25519 -C "cloudshell" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub   # Add this to GitHub → Settings → SSH Keys
git clone git@github.com:<username>/cbdc-benchmark.git
cd cbdc-benchmark
```

### Step 2 — Add Your Dataset
```bash
# Upload FinalDataset.xlsx to CloudShell (Actions → Upload file)
cp ~/FinalDataset.xlsx dataset/FinalDataset.xlsx
```

### Step 3 — Deploy Everything
```bash
chmod +x deploy.sh
./deploy.sh
```

That's it. The script will:
1. Provision VPC, subnets, security groups, EC2 instances
2. Upload the dataset to S3
3. Bootstrap 4-node PoA network, run 300s benchmark
4. Bootstrap 4-node QBFT network, run 300s benchmark
5. Generate 4 comparison charts + CSV + JSON report
6. Print presigned S3 URLs to download results

---

## Re-Run Benchmark Only (without redeploying infra)

```bash
./scripts/run-benchmark.sh

# Custom parameters:
./scripts/run-benchmark.sh --tps 100 --duration 600 --consensus qbft
```

---

## Switch Between PoA and QBFT

```bash
# PoA only
./deploy.sh --consensus poa
./scripts/run-benchmark.sh --consensus poa

# QBFT only
./deploy.sh --consensus qbft
./scripts/run-benchmark.sh --consensus qbft

# Both (default)
./deploy.sh --consensus both
```

---

## Download Results

```bash
# Sync all results locally
RUN_ID="run-YYYYMMDD-HHMMSS"   # shown in deploy output
aws s3 sync s3://<bucket>/results/${RUN_ID}/ ./results/${RUN_ID}/

# View reports
open ./results/${RUN_ID}/reports/04_summary_dashboard.png
```

---

## Destroy Everything

```bash
./deploy.sh --teardown        # destroys stack, prompts for bucket deletion
./scripts/destroy.sh          # same
./scripts/destroy.sh --keep-data   # keep S3 results
```

---

## Metrics Collected

| Metric            | Unit        | Source                    |
|-------------------|-------------|---------------------------|
| Throughput (TPS)  | tx/s        | Workload loader           |
| Avg Latency       | ms          | submit → receipt time     |
| P95 Latency       | ms          | Workload loader           |
| P99 Latency       | ms          | Workload loader           |
| Success Rate      | %           | receipt.status == 1       |
| Block Time        | s           | eth_getBlockByNumber diff |
| Tx per Block      | count       | Besu RPC                  |
| Pending Tx        | count       | txpool_status             |
| Peer Count        | count       | net_peerCount             |

All metrics also streamed to **CloudWatch** namespace `CBDCBenchmark`.

---

## Dataset Integration

The framework reads `FinalDataset.xlsx` (71,250 Ethereum transactions) with columns:

- `hash`, `nonce`, `from_address`, `to_address`
- `value`, `gas`, `gas_price`
- `receipt_gas_used`, `block_timestamp`, `block_number`
- `from_scam`, `to_scam`, `from_category`, `to_category`

Transactions are replayed against Besu using pre-funded dev accounts, with gas and value normalized for the private network.

---

## Cost Estimate (AWS)

| Resource          | Type        | Cost/hour | Per test (~2h) |
|-------------------|-------------|-----------|----------------|
| EC2 Benchmark     | t3.medium   | $0.042    | $0.08          |
| EC2 Validators ×4 | t3.medium   | $0.168    | $0.34          |
| S3 Storage        | ~100MB      | ~$0.002   | ~$0.00         |
| CloudWatch        | 10 metrics  | ~$0.003   | ~$0.01         |
| **Total**         |             |           | **~$0.50**     |

---

## Expected Timeline

| Phase                    | Duration   |
|--------------------------|------------|
| CloudFormation deploy    | 4–6 min    |
| PoA network bootstrap    | 2 min      |
| PoA benchmark (300s)     | 6 min      |
| QBFT network bootstrap   | 2 min      |
| QBFT benchmark (300s)    | 6 min      |
| Report generation        | 1 min      |
| **Total**                | **~23 min**|

---

## Repo Structure

```
cbdc-benchmark/
├── deploy.sh                          ← ONE-COMMAND ENTRY POINT
├── infrastructure/
│   └── cloudformation.yaml            ← VPC + EC2 + S3 + CloudWatch
├── besu/
│   ├── poa-config/genesis.json        ← Clique PoA genesis
│   ├── qbft-config/genesis.json       ← QBFT genesis
│   └── dockerfiles/
│       ├── Dockerfile.besu
│       └── Dockerfile.benchmark
├── benchmark/
│   ├── requirements.txt
│   ├── workload-loader.py             ← Core TPS engine
│   ├── tps-controller.py             ← Ramp-up TPS finder
│   ├── metrics-collector.py          ← Node metrics sidecar
│   └── report-generator.py           ← Charts + CSV + JSON
├── dataset/
│   └── upload-dataset.py
├── docker/
│   ├── docker-compose.poa.yml
│   └── docker-compose.qbft.yml
├── scripts/
│   ├── deploy.sh                      ← Full infra + benchmark
│   ├── run-benchmark.sh               ← Benchmark only
│   ├── destroy.sh
│   └── bootstrap-network.py          ← Key gen + genesis patching
└── ci-cd/
    ├── buildspec.yml                  ← AWS CodeBuild
    └── github-actions.yml            ← GitHub Actions
```

---

## Thesis Citation Note

This framework runs **4-node permissioned networks** (matching real CBDC deployments) using identical:
- Hardware (t3.medium EC2)
- Workload (71,250 real Ethereum transactions)
- Network topology (same VPC, same security groups)
- Duration (300 seconds per test)
- Block period (2 seconds for both)

This ensures **fair, reproducible, research-valid** comparisons between PoA and QBFT.
