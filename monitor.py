#!/usr/bin/env python3
"""
monitor.py
==========
Real-time monitoring for Besu PoA and QBFT nodes.
Polls chain state and writes time-series data to CSV.
Run alongside benchmark_client.py in a background thread.

Usage:
    python monitor.py --network poa  --port 8545 --duration 120
    python monitor.py --network qbft --port 8546 --duration 120
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from web3 import Web3
from web3.middleware import geth_poa_middleware

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)


def monitor(network: str, port: int, duration: int, interval: float = 1.0):
    w3 = Web3(Web3.HTTPProvider(f"http://localhost:{port}",
              request_kwargs={"timeout": 10}))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if not w3.is_connected():
        print(f"[monitor] Cannot connect to {network} on port {port}")
        sys.exit(1)

    out_file = RESULTS_DIR / f"monitor_{network}.csv"
    print(f"[monitor] Starting {network} monitoring → {out_file}")

    with open(out_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "block_number", "tx_pool_size",
            "gas_used", "gas_limit", "peer_count"
        ])

        start      = time.time()
        prev_block = None

        while time.time() - start < duration:
            try:
                bn         = w3.eth.block_number
                block      = w3.eth.get_block(bn)
                pool       = w3.eth.get_transaction_count
                peers      = w3.net.peer_count
                gas_used   = block["gasUsed"]
                gas_limit  = block["gasLimit"]

                # Estimate pending pool size via RPC
                try:
                    pool_resp = w3.provider.make_request("txpool_status", [])
                    pending   = int(pool_resp["result"].get("pending", "0x0"), 16)
                    queued    = int(pool_resp["result"].get("queued", "0x0"), 16)
                    pool_size = pending + queued
                except Exception:
                    pool_size = 0

                ts = datetime.utcnow().isoformat()
                writer.writerow([ts, bn, pool_size, gas_used, gas_limit, peers])
                f.flush()

                if prev_block and bn > prev_block:
                    bt = block["timestamp"]
                    print(f"[monitor:{network}] Block {bn} | Pool: {pool_size} | "
                          f"GasUsed: {gas_used:,} | Peers: {peers}")

                prev_block = bn

            except Exception as e:
                print(f"[monitor] Error: {e}")

            time.sleep(interval)

    print(f"[monitor] Done. Data written to {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Besu Node Monitor")
    parser.add_argument("--network",  default="poa",    help="poa or qbft")
    parser.add_argument("--port",     type=int, default=8545)
    parser.add_argument("--duration", type=int, default=300, help="Seconds to monitor")
    parser.add_argument("--interval", type=float, default=1.0, help="Poll interval seconds")
    args = parser.parse_args()

    monitor(args.network, args.port, args.duration, args.interval)
