#!/usr/bin/env python3
"""
CBDC Benchmark Workload Loader
Reads FinalDataset.xlsx from S3, replays transactions against Besu,
measures TPS / latency / success rate, ships metrics to CloudWatch.
"""

import os
import sys
import json
import time
import asyncio
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Any

import boto3
import pandas as pd
import numpy as np
from web3 import Web3
from eth_account import Account
from tqdm import tqdm

# ─── CONFIG ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("cbdc-workload")

# Pre-funded test accounts (Besu dev accounts)
FUNDED_ACCOUNTS = [
    {
        "address": "0xfe3b557e8fb62b89f4916b721be55ceb828dbd73",
        "private_key": "0x8f2a55949038a9610f50fb23b5883af3b4ecb3c3bb792cbcefbd1542c692be63",
    },
    {
        "address": "0x627306090abaB3A6e1400e9345bC60c78a8BEf57",
        "private_key": "0xc87509a1c067bbde78beb793e6fa76530b6382a4c0241e5e4a9ec0a0f44dc0d3",
    },
    {
        "address": "0xf17f52151EbEF6C7334FAD080c5704D77216b732",
        "private_key": "0xae6ae8e5ccbfb04590405997ee2d52d2b330726137b875053c36d94e974d162f",
    },
]


class CBDCBenchmark:
    def __init__(
        self,
        rpc_url: str,
        consensus: str,
        bucket: str,
        dataset_key: str,
        target_tps: int = 50,
        duration_seconds: int = 300,
        region: str = "us-east-1",
    ):
        self.rpc_url = rpc_url
        self.consensus = consensus
        self.bucket = bucket
        self.dataset_key = dataset_key
        self.target_tps = target_tps
        self.duration_seconds = duration_seconds
        self.region = region

        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))
        self.s3 = boto3.client("s3", region_name=region)
        self.cw = boto3.client("cloudwatch", region_name=region)

        self.results: List[Dict[str, Any]] = []
        self.block_times: List[float] = []
        self.last_block = None

    # ─── DATASET LOADING ─────────────────────────────────────────────────────
    def load_dataset(self) -> pd.DataFrame:
        log.info(f"Loading dataset from s3://{self.bucket}/{self.dataset_key}")
        obj = self.s3.get_object(Bucket=self.bucket, Key=self.dataset_key)
        df = pd.read_excel(obj["Body"].read(), engine="openpyxl")
        log.info(f"Loaded {len(df)} transactions from dataset")

        # Normalize: use only columns we need
        df = df[["from_address", "to_address", "value", "gas"]].copy()
        df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0)
        df["gas"] = pd.to_numeric(df["gas"], errors="coerce").fillna(21000).astype(int)
        # Cap gas to reasonable limit
        df["gas"] = df["gas"].clip(upper=500000)
        return df

    # ─── WAIT FOR NODE READY ─────────────────────────────────────────────────
    def wait_for_node(self, timeout: int = 300):
        log.info(f"Waiting for Besu RPC at {self.rpc_url} ...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.w3.is_connected():
                    block = self.w3.eth.block_number
                    log.info(f"Node ready. Current block: {block}")
                    return True
            except Exception:
                pass
            time.sleep(5)
        raise TimeoutError(f"Node not ready after {timeout}s")

    # ─── SEND SINGLE TRANSACTION ─────────────────────────────────────────────
    def send_transaction(self, row: pd.Series, account: dict, nonce: int) -> Dict:
        result = {
            "consensus": self.consensus,
            "timestamp": time.time(),
            "success": False,
            "latency_ms": None,
            "tx_hash": None,
            "error": None,
        }
        try:
            # Use dataset value but cap to available balance
            value_wei = min(int(row["value"]), 100_000_000_000_000_000)  # max 0.1 ETH

            tx = {
                "from": account["address"],
                "to": self.w3.to_checksum_address(
                    # Map dataset addresses to valid funded addresses
                    FUNDED_ACCOUNTS[nonce % len(FUNDED_ACCOUNTS)]["address"]
                ),
                "value": value_wei,
                "gas": int(row["gas"]),
                "gasPrice": 0,
                "nonce": nonce,
                "chainId": self.w3.eth.chain_id,
            }

            start = time.monotonic()
            signed = Account.sign_transaction(tx, account["private_key"])
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

            # Wait for receipt (with timeout)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            elapsed_ms = (time.monotonic() - start) * 1000

            result.update(
                {
                    "success": receipt.status == 1,
                    "latency_ms": elapsed_ms,
                    "tx_hash": tx_hash.hex(),
                    "block_number": receipt.blockNumber,
                    "gas_used": receipt.gasUsed,
                }
            )
        except Exception as e:
            result["error"] = str(e)[:200]

        return result

    # ─── BLOCK TIME MONITOR ──────────────────────────────────────────────────
    def sample_block_time(self):
        try:
            current = self.w3.eth.get_block("latest")
            if self.last_block and current.number > self.last_block.number:
                dt = current.timestamp - self.last_block.timestamp
                if 0 < dt < 60:
                    self.block_times.append(dt)
            self.last_block = current
        except Exception:
            pass

    # ─── CLOUDWATCH METRICS ──────────────────────────────────────────────────
    def push_metrics(self, window_results: List[Dict]):
        if not window_results:
            return
        latencies = [r["latency_ms"] for r in window_results if r["latency_ms"]]
        successes = [r for r in window_results if r["success"]]
        window_duration = 10  # seconds

        tps = len(successes) / window_duration
        avg_lat = np.mean(latencies) if latencies else 0
        p95_lat = np.percentile(latencies, 95) if latencies else 0
        success_rate = (len(successes) / len(window_results) * 100) if window_results else 0

        metrics = [
            {"MetricName": "TPS", "Value": tps, "Unit": "Count/Second"},
            {"MetricName": "AvgLatencyMs", "Value": avg_lat, "Unit": "Milliseconds"},
            {"MetricName": "P95LatencyMs", "Value": p95_lat, "Unit": "Milliseconds"},
            {"MetricName": "SuccessRate", "Value": success_rate, "Unit": "Percent"},
        ]

        try:
            self.cw.put_metric_data(
                Namespace="CBDCBenchmark",
                MetricData=[
                    {**m, "Dimensions": [{"Name": "Consensus", "Value": self.consensus}]}
                    for m in metrics
                ],
            )
        except Exception as e:
            log.warning(f"CloudWatch push failed: {e}")

    # ─── MAIN BENCHMARK LOOP ─────────────────────────────────────────────────
    def run(self) -> Dict[str, Any]:
        df = self.load_dataset()
        self.wait_for_node()

        # Use round-robin across funded accounts
        account = FUNDED_ACCOUNTS[0]
        nonce = self.w3.eth.get_transaction_count(account["address"])

        log.info(
            f"Starting {self.consensus} benchmark | "
            f"TPS={self.target_tps} | Duration={self.duration_seconds}s"
        )

        tx_interval = 1.0 / self.target_tps
        end_time = time.time() + self.duration_seconds
        window_start = time.time()
        window_results = []
        total_sent = 0
        row_idx = 0

        pbar = tqdm(total=self.duration_seconds, unit="s", desc=f"{self.consensus}")

        while time.time() < end_time:
            t0 = time.monotonic()

            row = df.iloc[row_idx % len(df)]
            result = self.send_transaction(row, account, nonce)
            self.results.append(result)
            window_results.append(result)

            if result["success"]:
                nonce += 1
            total_sent += 1
            row_idx += 1

            # Sample block time every ~5s
            if total_sent % (self.target_tps * 5) == 0:
                self.sample_block_time()

            # Push to CloudWatch every 10s window
            elapsed_window = time.time() - window_start
            if elapsed_window >= 10:
                self.push_metrics(window_results)
                window_results = []
                window_start = time.time()
                pbar.update(10)

            # TPS throttle
            elapsed = time.monotonic() - t0
            sleep_time = tx_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        pbar.close()

        return self._compute_summary()

    # ─── SUMMARY ─────────────────────────────────────────────────────────────
    def _compute_summary(self) -> Dict[str, Any]:
        total = len(self.results)
        successful = [r for r in self.results if r["success"]]
        failed = [r for r in self.results if not r["success"]]
        latencies = [r["latency_ms"] for r in successful if r["latency_ms"]]

        summary = {
            "consensus": self.consensus,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_seconds": self.duration_seconds,
            "target_tps": self.target_tps,
            "total_transactions": total,
            "successful_transactions": len(successful),
            "failed_transactions": len(failed),
            "success_rate_pct": round(len(successful) / total * 100, 2) if total else 0,
            "actual_tps": round(len(successful) / self.duration_seconds, 2),
            "avg_latency_ms": round(np.mean(latencies), 2) if latencies else 0,
            "median_latency_ms": round(np.median(latencies), 2) if latencies else 0,
            "p95_latency_ms": round(np.percentile(latencies, 95), 2) if latencies else 0,
            "p99_latency_ms": round(np.percentile(latencies, 99), 2) if latencies else 0,
            "min_latency_ms": round(min(latencies), 2) if latencies else 0,
            "max_latency_ms": round(max(latencies), 2) if latencies else 0,
            "avg_block_time_s": round(np.mean(self.block_times), 2) if self.block_times else 0,
            "std_block_time_s": round(np.std(self.block_times), 2) if self.block_times else 0,
        }

        log.info(f"\n{'='*60}")
        log.info(f"BENCHMARK COMPLETE: {self.consensus}")
        log.info(f"{'='*60}")
        for k, v in summary.items():
            log.info(f"  {k:<35} {v}")

        return summary

    # ─── SAVE RESULTS ────────────────────────────────────────────────────────
    def save_results(self, summary: Dict, run_id: str):
        prefix = f"results/{run_id}/{self.consensus}"

        # Raw results as JSON lines
        raw_json = "\n".join(json.dumps(r) for r in self.results)
        self.s3.put_object(
            Bucket=self.bucket,
            Key=f"{prefix}/raw_transactions.jsonl",
            Body=raw_json.encode(),
            ContentType="application/json",
        )

        # Summary
        self.s3.put_object(
            Bucket=self.bucket,
            Key=f"{prefix}/summary.json",
            Body=json.dumps(summary, indent=2).encode(),
            ContentType="application/json",
        )

        # Raw as CSV
        df = pd.DataFrame(self.results)
        self.s3.put_object(
            Bucket=self.bucket,
            Key=f"{prefix}/raw_transactions.csv",
            Body=df.to_csv(index=False).encode(),
            ContentType="text/csv",
        )

        log.info(f"Results saved to s3://{self.bucket}/{prefix}/")
        return prefix


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="CBDC Benchmark Workload Loader")
    parser.add_argument("--rpc-url", required=True, help="Besu JSON-RPC URL")
    parser.add_argument(
        "--consensus", required=True, choices=["PoA", "QBFT"], help="Consensus type"
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument(
        "--dataset-key",
        default="dataset/FinalDataset.xlsx",
        help="S3 key for dataset",
    )
    parser.add_argument("--target-tps", type=int, default=50, help="Target TPS")
    parser.add_argument(
        "--duration", type=int, default=300, help="Duration in seconds"
    )
    parser.add_argument("--run-id", default=None, help="Unique run ID")
    parser.add_argument(
        "--region", default=os.environ.get("AWS_REGION", "us-east-1"), help="AWS region"
    )
    args = parser.parse_args()

    run_id = args.run_id or datetime.utcnow().strftime("%Y%m%d-%H%M%S")

    benchmark = CBDCBenchmark(
        rpc_url=args.rpc_url,
        consensus=args.consensus,
        bucket=args.bucket,
        dataset_key=args.dataset_key,
        target_tps=args.target_tps,
        duration_seconds=args.duration,
        region=args.region,
    )

    summary = benchmark.run()
    prefix = benchmark.save_results(summary, run_id)

    # Write run ID to file for subsequent scripts
    with open("/tmp/run_id.txt", "w") as f:
        f.write(run_id)

    with open("/tmp/benchmark_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nRun ID: {run_id}")
    print(f"Results: s3://{args.bucket}/{prefix}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
