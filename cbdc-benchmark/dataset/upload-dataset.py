#!/usr/bin/env python3
"""
Dataset Loader — uploads FinalDataset.xlsx to S3.
Usage: python upload-dataset.py --bucket <name> [--file path/to/FinalDataset.xlsx]
"""

import os
import sys
import logging
import argparse

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dataset-loader")


def upload_dataset(bucket: str, file_path: str, s3_key: str, region: str):
    s3 = boto3.client("s3", region_name=region)

    # Check file exists
    if not os.path.isfile(file_path):
        log.error(f"File not found: {file_path}")
        sys.exit(1)

    file_size = os.path.getsize(file_path)
    log.info(f"Uploading {file_path} ({file_size / 1024:.1f} KB) → s3://{bucket}/{s3_key}")

    try:
        s3.upload_file(
            file_path,
            bucket,
            s3_key,
            ExtraArgs={"ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )
        log.info(f"✓ Upload complete: s3://{bucket}/{s3_key}")
    except ClientError as e:
        log.error(f"Upload failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Upload benchmark dataset to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument(
        "--file",
        default=os.path.join(os.path.dirname(__file__), "..", "dataset", "FinalDataset.xlsx"),
        help="Local path to FinalDataset.xlsx",
    )
    parser.add_argument("--s3-key", default="dataset/FinalDataset.xlsx", help="S3 object key")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args()

    upload_dataset(args.bucket, args.file, args.s3_key, args.region)


if __name__ == "__main__":
    sys.exit(main())
