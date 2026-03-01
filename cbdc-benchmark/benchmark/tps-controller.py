#!/usr/bin/env python3
"""
TPS Controller
Runs a ramp-up test: 10 → 25 → 50 → 100 → 150 TPS steps
Finds the maximum sustainable TPS for each consensus type.
"""

import os
import sys
import json
import time
import subprocess
import logging
import argparse
from datetime import datetime

import boto3
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("tps-controller")

TPS_STEPS = [10, 25, 50, 75, 100, 150]
STEP_DURATION = 60  # seconds per TPS step


def run_tps_step(
    rpc_url: str,
    consensus: str,
    bucket: str,
    dataset_key: str,
    target_tps: int,
    duration: int,
    run_id: str,
    region: str,
) -> dict:
    """Run workload-loader for one TPS step and return summary."""
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "workload-loader.py"),
        "--rpc-url", rpc_url,
        "--consensus", consensus,
        "--bucket", bucket,
        "--dataset-key", dataset_key,
        "--target-tps", str(target_tps),
        "--duration", str(duration),
        "--run-id", f"{run_id}-tps{target_tps}",
        "--region", region,
    ]
    log.info(f"Running TPS step: {target_tps} TPS for {duration}s")
    result = subprocess.run(cmd, capture_output=False, text=True)

    try:
        with open("/tmp/benchmark_summary.json") as f:
            return json.load(f)
    except Exception:
        return {"target_tps": target_tps, "error": "step failed"}


def find_max_sustainable_tps(step_results: list) -> float:
    """Max TPS where success rate >= 95%."""
    max_tps = 0
    for r in step_results:
        if r.get("success_rate_pct", 0) >= 95:
            max_tps = max(max_tps, r.get("actual_tps", 0))
    return max_tps


def main():
    parser = argparse.ArgumentParser(description="CBDC TPS Ramp Controller")
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--consensus", required=True, choices=["PoA", "QBFT"])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--dataset-key", default="dataset/FinalDataset.xlsx")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--tps-steps", default=",".join(map(str, TPS_STEPS)))
    parser.add_argument("--step-duration", type=int, default=STEP_DURATION)
    args = parser.parse_args()

    run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    tps_steps = list(map(int, args.tps_steps.split(",")))
    step_results = []

    log.info(f"TPS Ramp Test: {args.consensus}")
    log.info(f"Steps: {tps_steps}")

    for tps in tps_steps:
        result = run_tps_step(
            rpc_url=args.rpc_url,
            consensus=args.consensus,
            bucket=args.bucket,
            dataset_key=args.dataset_key,
            target_tps=tps,
            duration=args.step_duration,
            run_id=run_id,
            region=args.region,
        )
        step_results.append(result)
        log.info(
            f"Step {tps} TPS: actual={result.get('actual_tps', 0):.1f}, "
            f"success={result.get('success_rate_pct', 0):.1f}%, "
            f"p95={result.get('p95_latency_ms', 0):.0f}ms"
        )

        # Stop if success rate drops below 80%
        if result.get("success_rate_pct", 0) < 80:
            log.warning(f"Success rate dropped below 80% at {tps} TPS. Stopping ramp.")
            break

        # Cool-down between steps
        time.sleep(5)

    max_tps = find_max_sustainable_tps(step_results)
    log.info(f"Max sustainable TPS for {args.consensus}: {max_tps:.1f}")

    # Save ramp results
    s3 = boto3.client("s3", region_name=args.region)
    ramp_summary = {
        "consensus": args.consensus,
        "run_id": run_id,
        "max_sustainable_tps": max_tps,
        "steps": step_results,
    }
    s3.put_object(
        Bucket=args.bucket,
        Key=f"results/{run_id}/{args.consensus}/tps_ramp_summary.json",
        Body=json.dumps(ramp_summary, indent=2).encode(),
    )

    with open(f"/tmp/tps_ramp_{args.consensus}.json", "w") as f:
        json.dump(ramp_summary, f, indent=2)

    print(f"Max sustainable TPS: {max_tps:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
