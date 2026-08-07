#!/usr/bin/env python3
"""Verify the detached Caramel index signature and every indexed APK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

from build_repository import RepositoryError, sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--public-key", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve()
    index_path = repository / "caramel-index-v1.json"
    signature = repository / "caramel-index-v1.json.sig"
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(args.public_key), "-signature", str(signature), str(index_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode or result.stdout.strip() != "Verified OK":
        raise RepositoryError("Caramel index signature verification failed")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for package in index.get("packages", []):
        filename = Path(urlparse(package["apk_url"]).path).name
        apk = repository / filename
        if not apk.is_file():
            raise RepositoryError(f"missing indexed APK: {filename}")
        if sha256_file(apk) != package["sha256"]:
            raise RepositoryError(f"checksum mismatch: {filename}")
    print(f"verified {len(index.get('packages', []))} releases")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RepositoryError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"repository verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
