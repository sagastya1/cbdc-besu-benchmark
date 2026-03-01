#!/usr/bin/env python3
"""
Besu Network Bootstrapper
Generates node keys, builds genesis extraData for PoA (Clique) and QBFT.
Runs on each EC2 instance via SSM before network start.
"""

import os
import sys
import json
import subprocess
import logging
import argparse
import secrets
import hashlib
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bootstrapper")


def generate_node_key(data_dir: str) -> str:
    """Generate a random 32-byte private key and write to data/key."""
    key_path = os.path.join(data_dir, "key")
    os.makedirs(data_dir, exist_ok=True)
    if not os.path.exists(key_path):
        private_key = "0x" + secrets.token_hex(32)
        with open(key_path, "w") as f:
            f.write(private_key)
        log.info(f"Generated node key: {key_path}")
    else:
        with open(key_path) as f:
            private_key = f.read().strip()
        log.info(f"Using existing node key: {key_path}")
    return private_key


def get_node_address_from_key(private_key: str) -> str:
    """Derive Ethereum address from private key using eth_account."""
    try:
        from eth_account import Account
        acct = Account.from_key(private_key)
        return acct.address
    except Exception as e:
        log.warning(f"Could not derive address: {e}")
        return "0x0000000000000000000000000000000000000001"


def build_clique_extra_data(validator_addresses: list) -> str:
    """
    Clique extraData = 32 zero bytes + validator addresses (packed) + 65 zero bytes
    """
    prefix = "0" * 64  # 32 bytes
    validators = "".join(addr.lower().replace("0x", "") for addr in validator_addresses)
    suffix = "0" * 130  # 65 bytes (signature placeholder)
    return "0x" + prefix + validators + suffix


def build_qbft_extra_data(validator_addresses: list) -> str:
    """
    QBFT uses RLP-encoded extra data.
    Format: RLP([vanity, [validators], votes, round, seals])
    Using a simplified valid encoding for genesis.
    """
    # For genesis, use Besu's standard QBFT extra data format
    # We use a pre-computed valid RLP structure
    vanity = "00" * 32
    num_validators = len(validator_addresses)

    # Build RLP manually for simple case
    def rlp_encode_address(addr):
        raw = bytes.fromhex(addr.replace("0x", "").lower())
        return bytes([0x94]) + raw  # 0x94 = 0x80 + 20 (length of address)

    def rlp_encode_list(items_bytes):
        total = sum(len(i) for i in items_bytes)
        if total <= 55:
            return bytes([0xc0 + total]) + b"".join(items_bytes)
        else:
            length_bytes = total.to_bytes((total.bit_length() + 7) // 8, "big")
            return bytes([0xf7 + len(length_bytes)]) + length_bytes + b"".join(items_bytes)

    validator_rlp = [rlp_encode_address(addr) for addr in validator_addresses]
    validators_list = rlp_encode_list(validator_rlp)

    # vanity (32 bytes as RLP string)
    vanity_bytes = bytes(32)
    vanity_rlp = bytes([0xa0]) + vanity_bytes  # 0xa0 = 0x80 + 32

    # empty votes, round=0, empty seals
    empty_list = bytes([0xc0])
    round_rlp = bytes([0x80])  # RLP empty = round 0

    outer = rlp_encode_list([vanity_rlp, validators_list, empty_list, round_rlp, empty_list])
    return "0x" + outer.hex()


def patch_genesis(genesis_path: str, extra_data: str, validator_addresses: list):
    """Patch genesis.json with real validator addresses in alloc."""
    with open(genesis_path) as f:
        genesis = json.load(f)

    genesis["extraData"] = extra_data

    # Fund validator addresses
    for addr in validator_addresses:
        genesis["alloc"][addr] = {"balance": "0xad78ebc5ac6200000"}

    with open(genesis_path, "w") as f:
        json.dump(genesis, f, indent=2)
    log.info(f"Patched genesis: {genesis_path}")


def main():
    parser = argparse.ArgumentParser(description="Besu Network Bootstrapper")
    parser.add_argument("--consensus", required=True, choices=["poa", "qbft"])
    parser.add_argument("--node-count", type=int, default=4)
    parser.add_argument("--base-dir", default="/opt/besu")
    parser.add_argument("--config-dir", default=None)
    args = parser.parse_args()

    base_dir = args.base_dir
    config_dir = args.config_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "besu",
        f"{'poa' if args.consensus == 'poa' else 'qbft'}-config",
    )

    log.info(f"Bootstrapping {args.consensus.upper()} network with {args.node_count} nodes")

    # Generate keys for all nodes
    addresses = []
    for i in range(1, args.node_count + 1):
        data_dir = os.path.join(base_dir, f"node{i}", "data")
        private_key = generate_node_key(data_dir)
        address = get_node_address_from_key(private_key)
        addresses.append(address)
        log.info(f"Node {i}: {address}")

    # Build extra data
    if args.consensus == "poa":
        extra_data = build_clique_extra_data(addresses)
    else:
        extra_data = build_qbft_extra_data(addresses)

    log.info(f"extraData: {extra_data[:80]}...")

    # Patch genesis
    genesis_path = os.path.join(config_dir, "genesis.json")
    if os.path.exists(genesis_path):
        patch_genesis(genesis_path, extra_data, addresses)
    else:
        log.warning(f"Genesis not found at {genesis_path}")

    # Save node addresses for reference
    info = {
        "consensus": args.consensus,
        "node_count": args.node_count,
        "validator_addresses": addresses,
        "extra_data": extra_data,
    }
    info_path = os.path.join(base_dir, "network_info.json")
    with open(info_path, "w") as f:
        json.dump(info, f, indent=2)
    log.info(f"Network info saved: {info_path}")

    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    sys.exit(main())
