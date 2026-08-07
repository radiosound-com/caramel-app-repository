#!/usr/bin/env python3
"""Report first-party forks whose tracked upstream branch has moved."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")


class UpstreamError(RuntimeError):
    pass


def load_config(path: Path) -> dict[str, dict[str, str]]:
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UpstreamError(f"cannot read {path}: {error}") from error
    packages = root.get("packages") if isinstance(root, dict) else None
    if not isinstance(packages, dict):
        raise UpstreamError("upstreams.json must contain a packages object")
    for package, value in packages.items():
        if not PACKAGE_RE.fullmatch(package) or not isinstance(value, dict):
            raise UpstreamError(f"invalid package entry: {package}")
        repository = value.get("repository", "")
        branch = value.get("branch", "")
        reviewed = value.get("last_reviewed_commit", "")
        if (
            not REPOSITORY_RE.fullmatch(repository)
            or not isinstance(branch, str)
            or not branch
            or not SHA_RE.fullmatch(reviewed)
        ):
            raise UpstreamError(f"invalid upstream configuration for {package}")
    return packages


def fetch_branch_head(repository: str, branch: str, token: str = "") -> dict[str, str]:
    endpoint = (
        "https://api.github.com/repos/"
        + repository
        + "/commits/"
        + quote(branch, safe="")
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "caramel-app-repository-upstream-check",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(endpoint, headers=headers), timeout=20) as response:
            payload: Any = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise UpstreamError(f"cannot query {repository}@{branch}: {error}") from error
    sha = payload.get("sha", "") if isinstance(payload, dict) else ""
    html_url = payload.get("html_url", "") if isinstance(payload, dict) else ""
    if not SHA_RE.fullmatch(sha) or not isinstance(html_url, str):
        raise UpstreamError(f"GitHub returned an invalid commit for {repository}@{branch}")
    return {"sha": sha, "html_url": html_url}


def find_updates(
    packages: dict[str, dict[str, str]], token: str = ""
) -> list[dict[str, str]]:
    updates: list[dict[str, str]] = []
    for package, value in sorted(packages.items()):
        head = fetch_branch_head(value["repository"], value["branch"], token)
        if head["sha"] == value["last_reviewed_commit"]:
            continue
        updates.append(
            {
                "package_name": package,
                "display_name": value.get("display_name", package),
                "repository": value["repository"],
                "branch": value["branch"],
                "reviewed_commit": value["last_reviewed_commit"],
                "head_commit": head["sha"],
                "head_url": head["html_url"],
                "review_notes": value.get("review_notes", "Review and test before release."),
            }
        )
    return updates


def render_report(updates: list[dict[str, str]]) -> str:
    if not updates:
        return "No tracked upstream branches have moved since their last review.\n"
    lines = [
        "The following upstream branches moved after the commit last reviewed for the Caramel repository.",
        "Nothing is built or published automatically.",
        "",
    ]
    for update in updates:
        lines.extend(
            [
                f"## {update['display_name']} (`{update['package_name']}`)",
                "",
                f"- Upstream: `{update['repository']}@{update['branch']}`",
                f"- Last reviewed: `{update['reviewed_commit']}`",
                f"- Current head: [`{update['head_commit']}`]({update['head_url']})",
                f"- Review gate: {update['review_notes']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_github_output(path: Path, has_updates: bool) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write("has_updates=" + ("true" if has_updates else "false") + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("upstreams.json"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    packages = load_config(args.config)
    updates = find_updates(packages, os.environ.get("GITHUB_TOKEN", ""))
    report = render_report(updates)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    if args.github_output:
        write_github_output(args.github_output, bool(updates))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UpstreamError as error:
        print(f"upstream check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
