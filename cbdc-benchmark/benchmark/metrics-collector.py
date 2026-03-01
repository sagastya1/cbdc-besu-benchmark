#!/usr/bin/env python3
"""
Metrics Collector
Polls Besu metrics endpoint and EC2 CloudWatch metrics.
Runs as a background sidecar during benchmarking.
"""

import os
import sys
import json
import time
import logging
import argparse
import threading
from datetime import datetime

import boto3
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("metrics-collector")

POLL_INTERVAL = 10  # seconds


class BesuMetricsCollector:
    def __init__(self, rpc_url: str, consensus: str, bucket: str, region: str):
        self.rpc_url = rpc_url
        self.metrics_url = rpc_url.replace(":8545", ":9545") + "/metrics"
        self.consensus = consensus
        self.bucket = bucket
        self.region = region
        self.cw = boto3.client("cloudwatch", region_name=region)
        self.running = False
        self.samples = []

    def _rpc(self, method: str, params: list = []) -> dict:
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        resp = requests.post(self.rpc_url, json=payload, timeout=10)
        return resp.json().get("result")

    def collect_sample(self) -> dict:
        sample = {"timestamp": time.time(), "consensus": self.consensus}
        try:
            # Block number
            bn = self._rpc("eth_blockNumber")
            sample["block_number"] = int(bn, 16) if bn else None

            # Latest block
            block = self._rpc("eth_getBlockByNumber", ["latest", False])
            if block:
                sample["block_gas_used"] = int(block.get("gasUsed", "0x0"), 16)
                sample["block_tx_count"] = len(block.get("transactions", []))
                sample["block_timestamp"] = int(block.get("timestamp", "0x0"), 16)

            # Pending transactions
            pending = self._rpc("txpool_status")
            if pending:
                sample["pending_txs"] = int(pending.get("pending", "0x0"), 16)
                sample["queued_txs"] = int(pending.get("queued", "0x0"), 16)

            # Peer count
            peers = self._rpc("net_peerCount")
            sample["peer_count"] = int(peers, 16) if peers else 0

        except Exception as e:
            sample["error"] = str(e)[:100]

        return sample

    def push_to_cloudwatch(self, sample: dict):
        if "block_number" not in sample:
            return
        try:
            metrics = []
            if "pending_txs" in sample:
                metrics.append({
                    "MetricName": "PendingTransactions",
                    "Value": float(sample["pending_txs"]),
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Consensus", "Value": self.consensus}],
                })
            if "block_tx_count" in sample:
                metrics.append({
                    "MetricName": "TxPerBlock",
                    "Value": float(sample["block_tx_count"]),
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Consensus", "Value": self.consensus}],
                })
            if "peer_count" in sample:
                metrics.append({
                    "MetricName": "PeerCount",
                    "Value": float(sample["peer_count"]),
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Consensus", "Value": self.consensus}],
                })
            if metrics:
                self.cw.put_metric_data(Namespace="CBDCBenchmark", MetricData=metrics)
        except Exception as e:
            log.debug(f"CW push error: {e}")

    def run(self, duration: int = 400):
        self.running = True
        end_time = time.time() + duration
        log.info(f"Metrics collector started for {self.consensus}")

        while self.running and time.time() < end_time:
            sample = self.collect_sample()
            self.samples.append(sample)
            self.push_to_cloudwatch(sample)
            log.debug(f"Sample: block={sample.get('block_number')}, "
                      f"peers={sample.get('peer_count')}, "
                      f"pending={sample.get('pending_txs')}")
            time.sleep(POLL_INTERVAL)

        self.save_samples()
        log.info("Metrics collector stopped")

    def stop(self):
        self.running = False

    def save_samples(self):
        s3 = boto3.client("s3", region_name=self.region)
        run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        key = f"results/{run_id}/{self.consensus}/node_metrics.json"
        s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(self.samples, indent=2).encode(),
        )
        log.info(f"Node metrics saved to s3://{self.bucket}/{key}")


def main():
    parser = argparse.ArgumentParser(description="CBDC Metrics Collector")
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--consensus", required=True, choices=["PoA", "QBFT"])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--duration", type=int, default=400)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args()

    collector = BesuMetricsCollector(
        rpc_url=args.rpc_url,
        consensus=args.consensus,
        bucket=args.bucket,
        region=args.region,
    )
    collector.run(duration=args.duration)


if __name__ == "__main__":
    sys.exit(main())
