#!/usr/bin/env python3
"""
Report Generator
Downloads results from S3, generates side-by-side comparison graphs,
and produces CSV + JSON summary reports.
"""

import os
import sys
import json
import logging
import argparse
import io
from datetime import datetime

import boto3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("report-generator")

# Chart styling
plt.rcParams.update({
    "figure.facecolor": "#0d1117",
    "axes.facecolor": "#161b22",
    "axes.edgecolor": "#30363d",
    "axes.labelcolor": "#c9d1d9",
    "text.color": "#c9d1d9",
    "xtick.color": "#c9d1d9",
    "ytick.color": "#c9d1d9",
    "grid.color": "#21262d",
    "grid.alpha": 0.5,
    "font.family": "monospace",
})
COLORS = {"PoA": "#58a6ff", "QBFT": "#3fb950"}


class ReportGenerator:
    def __init__(self, bucket: str, run_id: str, region: str = "us-east-1"):
        self.bucket = bucket
        self.run_id = run_id
        self.region = region
        self.s3 = boto3.client("s3", region_name=region)
        self.summaries = {}
        self.raw_data = {}

    def load_results(self):
        for consensus in ["PoA", "QBFT"]:
            prefix = f"results/{self.run_id}/{consensus}"
            try:
                # Load summary
                obj = self.s3.get_object(Bucket=self.bucket, Key=f"{prefix}/summary.json")
                self.summaries[consensus] = json.loads(obj["Body"].read())
                log.info(f"Loaded {consensus} summary")

                # Load raw transactions
                obj = self.s3.get_object(Bucket=self.bucket, Key=f"{prefix}/raw_transactions.csv")
                self.raw_data[consensus] = pd.read_csv(io.BytesIO(obj["Body"].read()))
                log.info(f"Loaded {consensus} raw data: {len(self.raw_data[consensus])} rows")
            except Exception as e:
                log.warning(f"Could not load {consensus} data: {e}")

    def _upload_figure(self, fig, filename: str):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        buf.seek(0)
        key = f"results/{self.run_id}/reports/{filename}"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=buf.getvalue(), ContentType="image/png")
        log.info(f"Uploaded chart: s3://{self.bucket}/{key}")
        plt.close(fig)
        return key

    # ─── CHART 1: Key Metrics Bar Comparison ─────────────────────────────────
    def chart_metrics_comparison(self):
        if len(self.summaries) < 1:
            return
        metrics = ["actual_tps", "avg_latency_ms", "p95_latency_ms", "success_rate_pct"]
        labels = ["Actual TPS", "Avg Latency (ms)", "P95 Latency (ms)", "Success Rate (%)"]
        units = ["tx/s", "ms", "ms", "%"]

        fig, axes = plt.subplots(1, 4, figsize=(18, 5))
        fig.suptitle(
            f"CBDC Consensus Benchmark — PoA vs QBFT\nRun: {self.run_id}",
            fontsize=14, y=1.02,
        )

        for i, (metric, label, unit) in enumerate(zip(metrics, labels, units)):
            ax = axes[i]
            consensuses = list(self.summaries.keys())
            values = [self.summaries[c].get(metric, 0) for c in consensuses]
            colors = [COLORS.get(c, "#888") for c in consensuses]

            bars = ax.bar(consensuses, values, color=colors, width=0.5, edgecolor="#444")
            ax.set_title(label, fontsize=11, pad=8)
            ax.set_ylabel(unit, fontsize=9)
            ax.grid(axis="y", alpha=0.3)

            for bar, val in zip(bars, values):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(values) * 0.02,
                    f"{val:.1f}",
                    ha="center", va="bottom", fontsize=10, fontweight="bold",
                )

        plt.tight_layout()
        return self._upload_figure(fig, "01_metrics_comparison.png")

    # ─── CHART 2: Latency Distribution ───────────────────────────────────────
    def chart_latency_distribution(self):
        if not self.raw_data:
            return
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle("Latency Distribution: PoA vs QBFT", fontsize=13)

        for ax, (consensus, df) in zip(axes, self.raw_data.items()):
            latencies = df["latency_ms"].dropna()
            if latencies.empty:
                continue
            color = COLORS.get(consensus, "#888")
            ax.hist(latencies, bins=50, color=color, alpha=0.75, edgecolor="#333")
            ax.axvline(latencies.mean(), color="white", linestyle="--", linewidth=1.5,
                       label=f"Mean: {latencies.mean():.0f}ms")
            ax.axvline(np.percentile(latencies, 95), color="#ff7b72", linestyle=":",
                       linewidth=1.5, label=f"P95: {np.percentile(latencies, 95):.0f}ms")
            ax.set_title(f"{consensus} Latency Distribution")
            ax.set_xlabel("Latency (ms)")
            ax.set_ylabel("Frequency")
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)

        plt.tight_layout()
        return self._upload_figure(fig, "02_latency_distribution.png")

    # ─── CHART 3: Transaction Timeline ───────────────────────────────────────
    def chart_transaction_timeline(self):
        if not self.raw_data:
            return
        fig, axes = plt.subplots(2, 1, figsize=(16, 8), sharex=False)
        fig.suptitle("Transaction Latency Over Time", fontsize=13)

        for ax, (consensus, df) in zip(axes, self.raw_data.items()):
            df_success = df[df["success"] == True].copy()
            if df_success.empty or "timestamp" not in df_success.columns:
                continue
            color = COLORS.get(consensus, "#888")
            df_success = df_success.sort_values("timestamp")
            t0 = df_success["timestamp"].min()
            df_success["elapsed_s"] = df_success["timestamp"] - t0

            # Rolling average
            window = max(10, len(df_success) // 50)
            df_success["rolling_lat"] = df_success["latency_ms"].rolling(window).mean()

            ax.scatter(df_success["elapsed_s"], df_success["latency_ms"],
                       alpha=0.15, s=2, color=color)
            ax.plot(df_success["elapsed_s"], df_success["rolling_lat"],
                    color="white", linewidth=1.5, label=f"Rolling avg ({window})")
            ax.set_title(f"{consensus}")
            ax.set_ylabel("Latency (ms)")
            ax.set_xlabel("Time (s)")
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)

        plt.tight_layout()
        return self._upload_figure(fig, "03_latency_timeline.png")

    # ─── CHART 4: Side-by-Side Summary Dashboard ─────────────────────────────
    def chart_dashboard(self):
        if len(self.summaries) < 1:
            return

        metrics_map = {
            "Throughput (TPS)": "actual_tps",
            "Avg Latency (ms)": "avg_latency_ms",
            "P95 Latency (ms)": "p95_latency_ms",
            "P99 Latency (ms)": "p99_latency_ms",
            "Success Rate (%)": "success_rate_pct",
            "Avg Block Time (s)": "avg_block_time_s",
            "Total Transactions": "total_transactions",
            "Failed Transactions": "failed_transactions",
        }

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.axis("off")
        fig.suptitle(
            f"CBDC Benchmark Summary — Run ID: {self.run_id}\n"
            f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            fontsize=12, y=0.98,
        )

        columns = ["Metric"] + list(self.summaries.keys())
        rows = []
        for label, key in metrics_map.items():
            row = [label]
            for c in self.summaries:
                val = self.summaries[c].get(key, "N/A")
                row.append(f"{val:.2f}" if isinstance(val, float) else str(val))
            rows.append(row)

        col_colors = ["#21262d"] + [COLORS.get(c, "#444") for c in self.summaries]
        table = ax.table(
            cellText=rows,
            colLabels=columns,
            cellLoc="center",
            loc="center",
            colColours=col_colors,
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.8)

        for (row, col), cell in table.get_celld().items():
            cell.set_facecolor("#161b22" if row % 2 == 0 else "#0d1117")
            cell.set_edgecolor("#30363d")
            cell.set_text_props(color="#c9d1d9")
            if row == 0:
                cell.set_facecolor(col_colors[col] if col < len(col_colors) else "#21262d")
                cell.set_text_props(color="white", fontweight="bold")

        return self._upload_figure(fig, "04_summary_dashboard.png")

    # ─── COMPARISON CSV + JSON ────────────────────────────────────────────────
    def generate_comparison_report(self):
        if not self.summaries:
            log.warning("No summaries to compare")
            return

        comparison = []
        for consensus, summary in self.summaries.items():
            comparison.append(summary)

        # CSV
        df = pd.DataFrame(comparison)
        csv_buf = io.BytesIO(df.to_csv(index=False).encode())
        csv_key = f"results/{self.run_id}/reports/comparison_report.csv"
        self.s3.put_object(Bucket=self.bucket, Key=csv_key,
                           Body=csv_buf.getvalue(), ContentType="text/csv")

        # JSON
        full_report = {
            "run_id": self.run_id,
            "generated_at": datetime.utcnow().isoformat(),
            "results": self.summaries,
            "comparison": self._compute_differences(),
        }
        json_key = f"results/{self.run_id}/reports/comparison_report.json"
        self.s3.put_object(Bucket=self.bucket, Key=json_key,
                           Body=json.dumps(full_report, indent=2).encode(),
                           ContentType="application/json")

        log.info(f"Reports uploaded:")
        log.info(f"  s3://{self.bucket}/{csv_key}")
        log.info(f"  s3://{self.bucket}/{json_key}")
        return full_report

    def _compute_differences(self) -> dict:
        if "PoA" not in self.summaries or "QBFT" not in self.summaries:
            return {}
        poa = self.summaries["PoA"]
        qbft = self.summaries["QBFT"]

        def delta(key):
            a, b = poa.get(key, 0), qbft.get(key, 0)
            if a == 0:
                return "N/A"
            return round((b - a) / a * 100, 1)

        return {
            "tps_delta_pct": delta("actual_tps"),
            "latency_delta_pct": delta("avg_latency_ms"),
            "p95_latency_delta_pct": delta("p95_latency_ms"),
            "success_rate_delta_pct": delta("success_rate_pct"),
            "block_time_delta_pct": delta("avg_block_time_s"),
            "interpretation": (
                f"QBFT has {'higher' if qbft.get('actual_tps',0) > poa.get('actual_tps',0) else 'lower'} "
                f"throughput than PoA. "
                f"QBFT latency is {'higher' if qbft.get('avg_latency_ms',0) > poa.get('avg_latency_ms',0) else 'lower'}."
            ),
        }

    # ─── GENERATE ALL REPORTS ─────────────────────────────────────────────────
    def generate_all(self):
        log.info(f"Generating reports for run: {self.run_id}")
        self.load_results()
        self.chart_metrics_comparison()
        self.chart_latency_distribution()
        self.chart_transaction_timeline()
        self.chart_dashboard()
        report = self.generate_comparison_report()

        # Print presigned URLs for easy access
        for key_suffix in [
            "reports/01_metrics_comparison.png",
            "reports/02_latency_distribution.png",
            "reports/03_latency_timeline.png",
            "reports/04_summary_dashboard.png",
            "reports/comparison_report.csv",
            "reports/comparison_report.json",
        ]:
            key = f"results/{self.run_id}/{key_suffix}"
            try:
                url = self.s3.generate_presigned_url(
                    "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=86400
                )
                log.info(f"\n📊 {key_suffix}:\n   {url}")
            except Exception:
                pass

        return report


def main():
    parser = argparse.ArgumentParser(description="CBDC Report Generator")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args()

    generator = ReportGenerator(bucket=args.bucket, run_id=args.run_id, region=args.region)
    report = generator.generate_all()
    print(json.dumps(report.get("comparison", {}), indent=2))


if __name__ == "__main__":
    sys.exit(main())
