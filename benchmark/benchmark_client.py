#!/usr/bin/env python3
"""
benchmark_client.py
====================
CBDC Benchmark Client — Deploys CBDC contract, replays transaction
dataset, measures TPS / latency / block-time / finality for
PoA (Clique) and QBFT Besu networks.

Usage:
    python benchmark_client.py --network poa  --port 8545 --txns 500
    python benchmark_client.py --network qbft --port 8546 --txns 500
"""

import argparse
import csv
import json
import os
import sys
import time
import random
import statistics
import threading
from collections import defaultdict
from pathlib import Path
from datetime import datetime

import pandas as pd
from web3 import Web3
from web3.middleware import geth_poa_middleware

# ── Contract ABI (matches CBDC.sol) ──────────────────────────────────────────
CBDC_ABI = json.loads("""[
  {"inputs":[],"stateMutability":"nonpayable","type":"constructor"},
  {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],
   "name":"mint","outputs":[],"stateMutability":"nonpayable","type":"function"},
  {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],
   "name":"transfer","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
  {"inputs":[{"name":"from","type":"address"},{"name":"amount","type":"uint256"}],
   "name":"burn","outputs":[],"stateMutability":"nonpayable","type":"function"},
  {"inputs":[{"name":"recipients","type":"address[]"},{"name":"amount","type":"uint256"}],
   "name":"batchMint","outputs":[],"stateMutability":"nonpayable","type":"function"},
  {"inputs":[{"name":"","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],
   "stateMutability":"view","type":"function"},
  {"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],
   "stateMutability":"view","type":"function"},
  {"anonymous":false,"inputs":[{"indexed":true,"name":"from","type":"address"},
   {"indexed":true,"name":"to","type":"address"},{"indexed":false,"name":"value","type":"uint256"}],
   "name":"Transfer","type":"event"}
]""")

# Compiled CBDC bytecode (solc 0.8.x, optimizer enabled)
CBDC_BYTECODE = (
    "608060405234801561001057600080fd5b50336000806101000a81548173ffffffffffffffff"
    "ffffffffffffffffffffffff021916908373ffffffffffffffffffffffffffffffffffffffff"
    "160217905550610a5e806100616000396000f3fe608060405234801561001057600080fd5b50"
    "600436106100935760003560e01c8063156e29f61161006657806340c10f191161004b57806340"
    "c10f191461013657806370a082311461015257806318160ddd146101825761009357"
    "80639dc29fac14610186576100935761008e61019c565b80631249c58b146100985780632e1a7d4d"
    "146100b4578063313ce567146100d0575b600080fd5b6100b2600480360381019061"
    "00ad9190610609565b6101ac565b005b6100ce60048036038101906100c99190610609565b610300"
    "565b005b6100da6103e4565b6040516100e79190610671565b60405180910390f35b61013460"
    "0480360381019061012f919061068c565b6103e9565b005b610150600480360381019061014b"
    "9190610742565b61054e565b005b61016c60048036038101906101679190610782565b610620"
    "565b60405161017991906107be565b60405180910390f35b61018a610638565b604051610191"
    "91906107be565b60405180910390f35b6101a461019c565b005b600060000b60"
)

# Pre-compiled bytecode hex (minimal, from solc compilation)
# We use the full compiled bytecode embedded as a constant
FULL_BYTECODE = "0x" + (
    "60806040523480156200001157600080fd5b50336000806101000a81548173ffffffff"
    "ffffffffffffffffffffffffffffffff021916908373ffffffffffffffffffffffffffffff"
    "ffffffffff16021790555062000074565b6109dc806200007460003960"
    "00f3fe608060405234801561001057600080fd5b506004361061007"
    "05760003560e01c8063156e29f6116100505780631"
    # truncated — will use py-solc-x to compile at runtime
)

DEPLOYER_KEY  = "0x8f2a55949038a9610f50fb23b5883af3b4ecb3c3bb792cbcefbd1542c692be63"
DEPLOYER_ADDR = "0xFE3B557E8Fb62b89F4916B721be55cEb828dBd73"

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def connect_web3(port: int, network: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(f"http://localhost:{port}",
              request_kwargs={"timeout": 60}))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    assert w3.is_connected(), f"Cannot connect to node at port {port}"
    print(f"[+] Connected to {network} node. Chain ID: {w3.eth.chain_id}")
    return w3


def compile_and_deploy(w3: Web3, sol_path: str) -> str:
    """Compile CBDC.sol with py-solc-x, deploy, return contract address."""
    from solcx import compile_source, install_solc
    install_solc("0.8.20", show_progress=False)

    with open(sol_path) as f:
        source = f.read()

    compiled = compile_source(source, output_values=["abi", "bin"],
                               solc_version="0.8.20")
    contract_id = list(compiled.keys())[0]
    abi      = compiled[contract_id]["abi"]
    bytecode = compiled[contract_id]["bin"]

    account  = w3.eth.account.from_key(DEPLOYER_KEY)
    nonce    = w3.eth.get_transaction_count(account.address)
    chain_id = w3.eth.chain_id

    tx = {
        "from":     account.address,
        "nonce":    nonce,
        "gas":      3_000_000,
        "gasPrice": 0,
        "chainId":  chain_id,
        "data":     "0x" + bytecode,
    }
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    addr    = receipt["contractAddress"]
    print(f"[+] CBDC contract deployed at: {addr}")

    # Save ABI for reference
    with open(RESULTS_DIR / "cbdc_abi.json", "w") as f:
        json.dump(abi, f, indent=2)

    return addr, abi


def seed_accounts(w3: Web3, contract, accounts: list, amount_per: int = 10**24):
    """Batch-mint CBDC to all test accounts."""
    account = w3.eth.account.from_key(DEPLOYER_KEY)
    nonce   = w3.eth.get_transaction_count(account.address)
    chain_id = w3.eth.chain_id

    batch_size = 50
    for i in range(0, len(accounts), batch_size):
        batch = accounts[i:i+batch_size]
        tx = contract.functions.batchMint(
            batch, amount_per
        ).build_transaction({
            "from":     account.address,
            "nonce":    nonce,
            "gas":      2_000_000,
            "gasPrice": 0,
            "chainId":  chain_id,
        })
        signed  = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        nonce += 1
    print(f"[+] Seeded {len(accounts)} accounts")


# ── TPS Controller ────────────────────────────────────────────────────────────

class TPSController:
    """Token-bucket rate limiter to control target TPS."""
    def __init__(self, target_tps: float):
        self.target_tps   = target_tps
        self.interval     = 1.0 / target_tps if target_tps > 0 else 0
        self._last        = time.monotonic()
        self._lock        = threading.Lock()

    def wait(self):
        if self.interval == 0:
            return
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last
            sleep_t = self.interval - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)
            self._last = time.monotonic()


# ── Main Benchmark ────────────────────────────────────────────────────────────

def run_benchmark(args):
    network  = args.network
    port     = args.port
    n_txns   = args.txns
    tps_cap  = args.tps
    sol_path = args.contract

    w3 = connect_web3(port, network)

    # Deploy contract
    contract_addr, abi = compile_and_deploy(w3, sol_path)
    contract = w3.eth.contract(address=contract_addr, abi=abi)

    # Load dataset
    print(f"[+] Loading dataset: {args.dataset}")
    df = pd.read_excel(args.dataset, sheet_name="Dataset", nrows=n_txns + 100)
    df = df[["from_address", "to_address", "value"]].dropna()
    df = df.head(n_txns)
    print(f"[+] Loaded {len(df)} transactions from dataset")

    # Derive unique addresses & create local keys
    all_addrs = list(set(df["from_address"].tolist() + df["to_address"].tolist()))
    # For Besu dev mode we use the deployer as sender (avoids key mgmt overhead)
    deployer = w3.eth.account.from_key(DEPLOYER_KEY)

    # Seed with enough balance
    test_addrs = [Web3.to_checksum_address(a) for a in all_addrs[:20]]
    seed_accounts(w3, contract, test_addrs)

    controller = TPSController(tps_cap)

    # ── Send transactions ──────────────────────────────────────────────────────
    print(f"\n[+] Starting benchmark: {n_txns} txns @ {tps_cap} TPS cap")
    tx_hashes   = []
    send_times  = {}
    nonce       = w3.eth.get_transaction_count(deployer.address, "pending")
    chain_id    = w3.eth.chain_id
    start_time  = time.time()
    first_block = w3.eth.block_number
    errors      = 0

    for idx, row in df.iterrows():
        controller.wait()
        to_addr = Web3.to_checksum_address(row["to_address"])
        amount  = max(1, int(abs(row["value"]) % 10**18))

        try:
            tx = contract.functions.mint(
                to_addr, amount
            ).build_transaction({
                "from":     deployer.address,
                "nonce":    nonce,
                "gas":      100_000,
                "gasPrice": 0,
                "chainId":  chain_id,
            })
            signed   = deployer.sign_transaction(tx)
            t_send   = time.time()
            tx_hash  = w3.eth.send_raw_transaction(signed.rawTransaction)
            tx_hashes.append(tx_hash)
            send_times[tx_hash.hex()] = t_send
            nonce += 1
        except Exception as e:
            errors += 1
            nonce += 1  # advance nonce anyway

        if (idx % 50 == 0):
            elapsed = time.time() - start_time
            cur_tps = (idx + 1) / elapsed if elapsed > 0 else 0
            print(f"    Sent {idx+1}/{n_txns} | TPS: {cur_tps:.1f} | Errors: {errors}")

    send_duration = time.time() - start_time
    print(f"\n[+] All transactions sent in {send_duration:.2f}s")

    # ── Wait for finality ──────────────────────────────────────────────────────
    print("[+] Waiting for finality...")
    latencies     = []
    confirmed     = 0
    finality_time = None

    for tx_hash in tx_hashes:
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            t_confirm = time.time()
            lat = t_confirm - send_times[tx_hash.hex()]
            latencies.append(lat)
            confirmed += 1
        except Exception:
            pass

    finality_time = time.time() - start_time
    last_block    = w3.eth.block_number

    # ── Block time analysis ────────────────────────────────────────────────────
    block_times = []
    for bn in range(max(first_block, last_block - 20), last_block):
        try:
            b1 = w3.eth.get_block(bn)
            b2 = w3.eth.get_block(bn + 1)
            block_times.append(b2["timestamp"] - b1["timestamp"])
        except Exception:
            pass

    # ── Compute metrics ────────────────────────────────────────────────────────
    actual_tps         = confirmed / finality_time if finality_time > 0 else 0
    avg_latency        = statistics.mean(latencies)    if latencies   else 0
    p95_latency        = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
    avg_block_time     = statistics.mean(block_times)  if block_times else 0
    blocks_used        = last_block - first_block

    metrics = {
        "network":         network,
        "timestamp":       datetime.utcnow().isoformat(),
        "transactions_sent":    n_txns,
        "transactions_confirmed": confirmed,
        "errors":          errors,
        "tps_cap":         tps_cap,
        "actual_tps":      round(actual_tps, 3),
        "avg_latency_s":   round(avg_latency, 4),
        "p95_latency_s":   round(p95_latency, 4),
        "min_latency_s":   round(min(latencies), 4) if latencies else 0,
        "max_latency_s":   round(max(latencies), 4) if latencies else 0,
        "avg_block_time_s": round(avg_block_time, 3),
        "finality_time_s": round(finality_time, 3),
        "blocks_used":     blocks_used,
        "contract_address": contract_addr,
    }

    # ── Save results ───────────────────────────────────────────────────────────
    metrics_file = RESULTS_DIR / f"metrics_{network}.json"
    with open(metrics_file, "w") as f:
        json.dump(metrics, f, indent=2)

    lat_file = RESULTS_DIR / f"latencies_{network}.csv"
    with open(lat_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["tx_index", "latency_s"])
        for i, lat in enumerate(latencies):
            writer.writerow([i, round(lat, 6)])

    bt_file = RESULTS_DIR / f"block_times_{network}.csv"
    with open(bt_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["block_number", "block_time_s"])
        for i, bt in enumerate(block_times):
            writer.writerow([first_block + i, bt])

    # ── Print summary ──────────────────────────────────────────────────────────
    print("\n" + "="*55)
    print(f"  BENCHMARK RESULTS — {network.upper()}")
    print("="*55)
    print(f"  Transactions:   {confirmed}/{n_txns} confirmed")
    print(f"  Actual TPS:     {actual_tps:.2f}")
    print(f"  Avg Latency:    {avg_latency*1000:.1f} ms")
    print(f"  P95 Latency:    {p95_latency*1000:.1f} ms")
    print(f"  Avg Block Time: {avg_block_time:.2f}s")
    print(f"  Finality Time:  {finality_time:.2f}s")
    print(f"  Blocks Used:    {blocks_used}")
    print("="*55)
    print(f"  Results saved to: {RESULTS_DIR}/")

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CBDC Benchmark Client")
    parser.add_argument("--network",  default="poa",              help="poa or qbft")
    parser.add_argument("--port",     type=int, default=8545,     help="Besu RPC port")
    parser.add_argument("--txns",     type=int, default=500,      help="Number of txns to send")
    parser.add_argument("--tps",      type=float, default=50.0,   help="Max TPS to send")
    parser.add_argument("--dataset",  default="FinalDataset.xlsx",help="Path to xlsx dataset")
    parser.add_argument("--contract", default="contracts/CBDC.sol",help="Path to CBDC.sol")
    args = parser.parse_args()

    run_benchmark(args)
