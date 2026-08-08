#!/usr/bin/env python3
"""Build the static F-Droid and pinned Caramel indexes from signed APKs."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
BADGING_RE = re.compile(
    r"package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'"
)
SIGNER_RE = re.compile(r"Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]{64})")


class RepositoryError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        stdout = getattr(error, "stdout", "") or ""
        stderr = getattr(error, "stderr", "") or ""
        detail = (stderr.strip() or stdout.strip() or "no diagnostic output")
        raise RepositoryError(f"command failed: {command[0]}: {detail}") from error
    return result.stdout + result.stderr


def inspect_apk(path: Path, aapt2: str, apksigner: str) -> dict[str, Any]:
    if not path.is_file():
        raise RepositoryError(f"APK does not exist: {path}")
    badging = run([aapt2, "dump", "badging", str(path)])
    match = BADGING_RE.search(badging)
    if not match:
        raise RepositoryError(f"cannot read package/version from {path}")
    signer_output = run([apksigner, "verify", "--print-certs", str(path)])
    signer = SIGNER_RE.search(signer_output)
    if not signer:
        raise RepositoryError(f"cannot read signing certificate from {path}")
    return {
        "package_name": match.group(1),
        "version_code": int(match.group(2)),
        "version_name": match.group(3),
        "downloaded_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "signing_certificate_sha256": signer.group(1).lower(),
    }


def parse_artifact(value: str) -> tuple[str, Path]:
    package, separator, path = value.partition("=")
    if not separator or not PACKAGE_RE.fullmatch(package) or not path:
        raise argparse.ArgumentTypeError("artifacts must use PACKAGE=/path/to/app.apk")
    return package, Path(path).expanduser().resolve()


def write_localized_metadata(root: Path, package: str, metadata: dict[str, Any]) -> None:
    app_dir = root / "metadata" / package / "en-US"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "name.txt").write_text(metadata["display_name"] + "\n", encoding="utf-8")
    (app_dir / "summary.txt").write_text(metadata["summary"] + "\n", encoding="utf-8")
    (app_dir / "full_description.txt").write_text(metadata["description"] + "\n", encoding="utf-8")
    lines = [
        "Categories:",
        *[f"  - {item}" for item in metadata["categories"]],
        f"License: {metadata['license']}",
        f"SourceCode: {metadata['source_code']}",
    ]
    if metadata.get("issue_tracker"):
        lines.append(f"IssueTracker: {metadata['issue_tracker']}")
    lines.extend([f"AutoName: {metadata['display_name']}", ""])
    (root / "metadata" / f"{package}.yml").write_text("\n".join(lines), encoding="utf-8")


def copy_metadata_assets(source_root: Path, output_root: Path, package: str) -> None:
    source = source_root / "metadata" / package / "en-US"
    destination = output_root / "metadata" / package / "en-US"
    if not source.is_dir():
        return
    for item in source.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def localized_asset_url(fdroid_index: dict[str, Any], package: str, key: str, repo_url: str) -> str:
    record = fdroid_index.get("packages", {}).get(package, {})
    metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
    value = metadata.get(key) if isinstance(metadata, dict) else None
    if isinstance(value, dict):
        value = value.get("en-US") or value.get("en") or next(iter(value.values()), None)
    if isinstance(value, dict):
        value = value.get("name")
    if not isinstance(value, str) or not value:
        return ""
    return repo_url.rstrip("/") + "/" + value.lstrip("/")


def localized_screenshot_urls(
    fdroid_index: dict[str, Any], package: str, repo_url: str
) -> list[str]:
    record = fdroid_index.get("packages", {}).get(package, {})
    metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
    screenshots = metadata.get("screenshots", {}) if isinstance(metadata, dict) else {}
    if not isinstance(screenshots, dict):
        return []

    urls: list[str] = []
    for form_factor in ("phone", "sevenInch", "tenInch", "tv", "wear"):
        localized = screenshots.get(form_factor)
        if not isinstance(localized, dict):
            continue
        values = localized.get("en-US") or localized.get("en")
        if values is None and localized:
            values = next(iter(localized.values()))
        if not isinstance(values, list):
            continue
        for value in values:
            name = value.get("name") if isinstance(value, dict) else value
            if not isinstance(name, str) or not name:
                continue
            url = repo_url.rstrip("/") + "/" + name.lstrip("/")
            if url not in urls:
                urls.append(url)
    return urls


def build_index(
    manifest: dict[str, Any],
    inspected: list[dict[str, Any]],
    fdroid_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = manifest["repository"]
    configured = manifest["packages"]
    packages: list[dict[str, Any]] = []
    for release in sorted(inspected, key=lambda item: item["package_name"]):
        package = release["package_name"]
        metadata = configured.get(package)
        if not isinstance(metadata, dict):
            raise RepositoryError(f"no approved metadata for {package}")
        expected_signer = metadata.get("trusted_signing_certificate_sha256", "").lower()
        if not SHA256_RE.fullmatch(expected_signer):
            raise RepositoryError(f"{package} has no trusted signing-certificate digest")
        if release["signing_certificate_sha256"] != expected_signer:
            raise RepositoryError(
                f"{package} signer is {release['signing_certificate_sha256']}, expected {expected_signer}"
            )
        item_metadata = {
            "locale": "en-US",
            "display_name": metadata["display_name"],
            "summary": metadata["summary"],
            "description": metadata["description"],
            "categories": metadata["categories"],
            "license": metadata["license"],
        }
        if fdroid_index:
            icon = localized_asset_url(fdroid_index, package, "icon", repository["url"])
            feature = localized_asset_url(fdroid_index, package, "featureGraphic", repository["url"])
            if icon:
                item_metadata["icon_url"] = icon
            if feature:
                item_metadata["feature_graphic_url"] = feature
            screenshots = localized_screenshot_urls(fdroid_index, package, repository["url"])
            if screenshots:
                item_metadata["screenshot_urls"] = screenshots
        filename = f"{package}_{release['version_code']}.apk"
        packages.append(
            {
                **release,
                "apk_url": repository["url"].rstrip("/") + "/" + filename,
                "canonical_apk_url": repository["url"].rstrip("/") + "/" + filename,
                "metadata": item_metadata,
                "manifest_findings": metadata.get("manifest_findings", {}),
                "upstream_urls": {
                    "source_code": metadata["source_code"],
                    **(
                        {"issue_tracker": metadata["issue_tracker"]}
                        if metadata.get("issue_tracker")
                        else {}
                    ),
                },
                "first_party": True,
            }
        )
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "repository": {
            "name": repository["name"],
            "description": repository["description"],
            "url": repository["url"],
        },
        "packages": packages,
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RepositoryError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise RepositoryError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("apps.json"))
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--apk", action="append", type=parse_artifact, required=True)
    parser.add_argument("--aapt2", required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--fdroid", default="fdroid")
    parser.add_argument("--skip-fdroid", action="store_true")
    parser.add_argument("--index-private-key", type=Path, required=True)
    parser.add_argument("--index-key-password-file", type=Path, required=True)
    parser.add_argument("--index-public-key", type=Path, required=True)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    manifest = load_json(args.manifest)
    output = args.output.resolve()
    for _, apk in args.apk:
        if apk == output or output in apk.parents:
            raise RepositoryError("input APKs must be outside the generated output directory")
    if output.exists():
        shutil.rmtree(output)
    (output / "repo").mkdir(parents=True)

    generated_config = output / "config.yml"
    shutil.copy2(root / "config.yml", generated_config)
    with generated_config.open("a", encoding="utf-8") as config:
        config.write(f"\napksigner: {args.apksigner}\n")
    generated_config.chmod(0o600)
    inspected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for declared_package, apk in args.apk:
        if declared_package in seen:
            raise RepositoryError(f"duplicate artifact for {declared_package}")
        seen.add(declared_package)
        release = inspect_apk(apk, args.aapt2, args.apksigner)
        if release["package_name"] != declared_package:
            raise RepositoryError(
                f"artifact declared as {declared_package}, contains {release['package_name']}"
            )
        metadata = manifest.get("packages", {}).get(declared_package)
        if not isinstance(metadata, dict):
            raise RepositoryError(f"no approved metadata for {declared_package}")
        write_localized_metadata(output, declared_package, metadata)
        copy_metadata_assets(root, output, declared_package)
        filename = f"{declared_package}_{release['version_code']}.apk"
        shutil.copy2(apk, output / "repo" / filename)
        inspected.append(release)

    fdroid_index = None
    if not args.skip_fdroid:
        run([args.fdroid, "update", "--pretty"], cwd=output, env=os.environ.copy())
        index_path = output / "repo" / "index-v2.json"
        if index_path.is_file():
            fdroid_index = load_json(index_path)

    index = build_index(manifest, inspected, fdroid_index)
    index_path = output / "repo" / "caramel-index-v1.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    signature_path = output / "repo" / "caramel-index-v1.json.sig"
    run(
        [
            "openssl", "dgst", "-sha256",
            "-sign", str(args.index_private_key),
            "-passin", f"file:{args.index_key_password_file}",
            "-out", str(signature_path),
            str(index_path),
        ]
    )
    shutil.copy2(args.index_public_key, output / "repo" / "caramel-index-v1.pem")
    print(f"built {len(inspected)} releases in {output / 'repo'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RepositoryError as error:
        print(f"repository build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
