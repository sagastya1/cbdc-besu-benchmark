#!/usr/bin/env python3
"""
generate_graphs.py
==================
Reads benchmark results and generates comparative visualizations:
  - TPS comparison bar chart
  - Latency CDF
  - Block time distribution
  - Summary metrics table → CSV
"""

import json
import os
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

RESULTS_DIR = Path("results")
GRAPHS_DIR  = Path("results/graphs")
GRAPHS_DIR.mkdir(parents=True, exist_ok=True)

COLORS = {"poa": "#2196F3", "qbft": "#FF5722"}
LABELS = {"poa": "PoA (Clique)", "qbft": "QBFT"}


def load_metrics(network):
    path = RESULTS_DIR / f"metrics_{network}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_latencies(network):
    path = RESULTS_DIR / f"latencies_{network}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)["latency_s"].tolist()


def load_block_times(network):
    path = RESULTS_DIR / f"block_times_{network}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)["block_time_s"].tolist()


def load_monitor(network):
    path = RESULTS_DIR / f"monitor_{network}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def plot_tps_comparison(metrics_poa, metrics_qbft):
    fig, ax = plt.subplots(figsize=(8, 5))
    networks = []
    tps_vals = []
    colors   = []

    for net, m in [("poa", metrics_poa), ("qbft", metrics_qbft)]:
        if m:
            networks.append(LABELS[net])
            tps_vals.append(m["actual_tps"])
            colors.append(COLORS[net])

    bars = ax.bar(networks, tps_vals, color=colors, width=0.5, edgecolor="black", linewidth=0.8)
    for bar, val in zip(bars, tps_vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f"{val:.2f}", ha="center", va="bottom", fontsize=12, fontweight="bold")

    ax.set_ylabel("Transactions Per Second (TPS)", fontsize=12)
    ax.set_title("CBDC Throughput: PoA vs QBFT", fontsize=14, fontweight="bold")
    ax.set_ylim(0, max(tps_vals) * 1.3 if tps_vals else 10)
    ax.grid(axis="y", alpha=0.4, linestyle="--")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(GRAPHS_DIR / "tps_comparison.png", dpi=150)
    plt.close()
    print("[+] Saved tps_comparison.png")


def plot_latency_cdf(lat_poa, lat_qbft):
    fig, ax = plt.subplots(figsize=(9, 5))

    for net, lats, label in [
        ("poa",  lat_poa,  LABELS["poa"]),
        ("qbft", lat_qbft, LABELS["qbft"]),
    ]:
        if lats:
            sorted_lats = sorted(lats)
            cdf = np.arange(1, len(sorted_lats) + 1) / len(sorted_lats)
            ax.plot([l * 1000 for l in sorted_lats], cdf,
                    label=label, color=COLORS[net], linewidth=2)
            # Mark P50, P95
            p50 = sorted_lats[int(0.50 * len(sorted_lats))] * 1000
            p95 = sorted_lats[int(0.95 * len(sorted_lats))] * 1000
            ax.axvline(p50, color=COLORS[net], linestyle=":", alpha=0.7)
            ax.axvline(p95, color=COLORS[net], linestyle="--", alpha=0.7)

    ax.set_xlabel("Latency (ms)", fontsize=12)
    ax.set_ylabel("CDF", fontsize=12)
    ax.set_title("Transaction Latency CDF: PoA vs QBFT", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(GRAPHS_DIR / "latency_cdf.png", dpi=150)
    plt.close()
    print("[+] Saved latency_cdf.png")


def plot_block_times(bt_poa, bt_qbft):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    for ax, net, bts in [
        (axes[0], "poa",  bt_poa),
        (axes[1], "qbft", bt_qbft),
    ]:
        if bts:
            ax.hist(bts, bins=20, color=COLORS[net], edgecolor="black",
                    linewidth=0.6, alpha=0.85)
            ax.axvline(np.mean(bts), color="black", linestyle="--",
                       label=f"Mean: {np.mean(bts):.2f}s")
            ax.set_title(f"Block Time Distribution — {LABELS[net]}",
                         fontsize=12, fontweight="bold")
            ax.set_xlabel("Block Time (s)", fontsize=11)
            ax.set_ylabel("Count", fontsize=11)
            ax.legend(fontsize=10)
            ax.grid(alpha=0.3)
            ax.spines[["top", "right"]].set_visible(False)

    plt.suptitle("Block Time Distribution: PoA vs QBFT", fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(GRAPHS_DIR / "block_times.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("[+] Saved block_times.png")


def plot_summary_dashboard(metrics_poa, metrics_qbft):
    """4-panel summary dashboard."""
    fig = plt.figure(figsize=(14, 10))
    fig.suptitle("CBDC Benchmark: PoA vs QBFT — Summary Dashboard",
                 fontsize=16, fontweight="bold", y=0.98)
    gs = gridspec.GridSpec(2, 2, hspace=0.45, wspace=0.35)

    # -- Panel 1: TPS
    ax1 = fig.add_subplot(gs[0, 0])
    data = [(LABELS[n], m["actual_tps"], COLORS[n])
            for n, m in [("poa", metrics_poa), ("qbft", metrics_qbft)] if m]
    if data:
        ax1.bar([d[0] for d in data], [d[1] for d in data],
                color=[d[2] for d in data], edgecolor="black", linewidth=0.7, width=0.5)
        ax1.set_title("Actual TPS", fontweight="bold")
        ax1.set_ylabel("TPS")
        ax1.grid(axis="y", alpha=0.3)

    # -- Panel 2: Avg Latency
    ax2 = fig.add_subplot(gs[0, 1])
    data2 = [(LABELS[n], m["avg_latency_s"] * 1000, COLORS[n])
             for n, m in [("poa", metrics_poa), ("qbft", metrics_qbft)] if m]
    if data2:
        ax2.bar([d[0] for d in data2], [d[1] for d in data2],
                color=[d[2] for d in data2], edgecolor="black", linewidth=0.7, width=0.5)
        ax2.set_title("Average Latency", fontweight="bold")
        ax2.set_ylabel("Latency (ms)")
        ax2.grid(axis="y", alpha=0.3)

    # -- Panel 3: Block Time
    ax3 = fig.add_subplot(gs[1, 0])
    data3 = [(LABELS[n], m["avg_block_time_s"], COLORS[n])
             for n, m in [("poa", metrics_poa), ("qbft", metrics_qbft)] if m]
    if data3:
        ax3.bar([d[0] for d in data3], [d[1] for d in data3],
                color=[d[2] for d in data3], edgecolor="black", linewidth=0.7, width=0.5)
        ax3.set_title("Avg Block Time", fontweight="bold")
        ax3.set_ylabel("Seconds")
        ax3.grid(axis="y", alpha=0.3)

    # -- Panel 4: Finality Time
    ax4 = fig.add_subplot(gs[1, 1])
    data4 = [(LABELS[n], m["finality_time_s"], COLORS[n])
             for n, m in [("poa", metrics_poa), ("qbft", metrics_qbft)] if m]
    if data4:
        ax4.bar([d[0] for d in data4], [d[1] for d in data4],
                color=[d[2] for d in data4], edgecolor="black", linewidth=0.7, width=0.5)
        ax4.set_title("Total Finality Time", fontweight="bold")
        ax4.set_ylabel("Seconds")
        ax4.grid(axis="y", alpha=0.3)

    for ax in [ax1, ax2, ax3, ax4]:
        ax.spines[["top", "right"]].set_visible(False)

    plt.savefig(GRAPHS_DIR / "dashboard.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("[+] Saved dashboard.png")


def save_comparison_csv(metrics_poa, metrics_qbft):
    rows = []
    for net, m in [("poa", metrics_poa), ("qbft", metrics_qbft)]:
        if m:
            rows.append({
                "Network":          LABELS[net],
                "TPS":              m["actual_tps"],
                "Avg Latency (ms)": round(m["avg_latency_s"] * 1000, 1),
                "P95 Latency (ms)": round(m["p95_latency_s"] * 1000, 1),
                "Avg Block Time (s)": m["avg_block_time_s"],
                "Finality Time (s)": m["finality_time_s"],
                "Confirmed Txns":   m["transactions_confirmed"],
                "Errors":           m["errors"],
                "Blocks Used":      m["blocks_used"],
            })
    if rows:
        df = pd.DataFrame(rows)
        path = RESULTS_DIR / "comparison_summary.csv"
        df.to_csv(path, index=False)
        print(f"[+] Saved comparison_summary.csv")
        print("\n" + df.to_string(index=False))


def main():
    print("[+] Generating graphs and comparison report...")

    metrics_poa  = load_metrics("poa")
    metrics_qbft = load_metrics("qbft")
    lat_poa      = load_latencies("poa")
    lat_qbft     = load_latencies("qbft")
    bt_poa       = load_block_times("poa")
    bt_qbft      = load_block_times("qbft")

    if not metrics_poa and not metrics_qbft:
        print("[!] No metrics found. Run benchmark_client.py first.")
        return

    plot_tps_comparison(metrics_poa, metrics_qbft)
    plot_latency_cdf(lat_poa, lat_qbft)
    plot_block_times(bt_poa, bt_qbft)
    plot_summary_dashboard(metrics_poa, metrics_qbft)
    save_comparison_csv(metrics_poa, metrics_qbft)

    print(f"\n[+] All outputs saved to {GRAPHS_DIR}/")


if __name__ == "__main__":
    main()
