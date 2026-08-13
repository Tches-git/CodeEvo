"""Import auditable, labelled public GitHub PRs into the Evaluation Harness.

Each manifest record must use schema version 1 and include a human-reviewed
ground truth plus licence evidence. Public PR content alone is not ground truth,
so unlabelled or private records are intentionally rejected.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from codeevo.diff_parser import parse_unified_diff  # noqa: E402
from codeevo.evaluation_dataset import (  # noqa: E402
    CASE_SCHEMA_VERSION,
    DatasetManifest,
    repository_split,
    sha256_text,
)
from codeevo.evaluation_harness import validate_case  # noqa: E402


def fetch_pull_request(repository, pull_request, token=""):
    url = "https://api.github.com/repos/%s/pulls/%d" % (repository, pull_request)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "codeevo-evaluation-importer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            "GitHub returned HTTP %d for %s#%d"
            % (exc.code, repository, pull_request)
        ) from exc
    diff_url = str(metadata.get("diff_url") or "")
    if not diff_url:
        raise RuntimeError("GitHub did not return a diff URL for %s#%d" % (repository, pull_request))
    diff_request = urllib.request.Request(diff_url, headers={
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "codeevo-evaluation-importer",
    })
    try:
        with urllib.request.urlopen(diff_request, timeout=60) as response:
            diff = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError("GitHub diff download returned HTTP %d" % exc.code) from exc
    return diff, metadata, url


def require_text(item, field, line_number):
    value = str(item.get(field, "")).strip()
    if not value:
        raise ValueError("manifest line %d is missing %s" % (line_number, field))
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="Labelled JSONL manifest")
    parser.add_argument("output", help="Evaluation JSONL output")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dataset-name", default="codeevo-public-pr")
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--split-salt", default="codeevo-public-pr-v1")
    parser.add_argument(
        "--allow-manual-split", action="store_true",
        help="Accept manifest splits; repository leakage is still rejected.",
    )
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    records = []
    with open(args.manifest, "r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            item = json.loads(raw)
            if item.get("schema_version") != 1:
                raise ValueError(
                    "manifest line %d must use schema_version 1" % line_number
                )
            if "expected_findings" not in item:
                raise ValueError(
                    "manifest line %d has no human-reviewed expected_findings"
                    % line_number
                )
            annotator = require_text(item, "annotator", line_number)
            annotated_at = require_text(item, "annotated_at", line_number)
            methodology = require_text(item, "methodology", line_number)
            license_spdx = require_text(item, "license_spdx", line_number)
            license_evidence_url = require_text(
                item, "license_evidence_url", line_number
            )
            try:
                datetime.datetime.fromisoformat(annotated_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    "manifest line %d annotated_at must be ISO-8601" % line_number
                ) from exc
            evidence_urls = item.get("evidence_urls", [])
            if not isinstance(evidence_urls, list):
                raise ValueError("manifest line %d evidence_urls must be an array" % line_number)
            if item["expected_findings"] and not evidence_urls:
                raise ValueError("manifest line %d risk case needs evidence_urls" % line_number)
            diff, metadata, api_url = fetch_pull_request(
                str(item["repository"]), int(item["pull_request"]), token
            )
            parsed = parse_unified_diff(diff)
            repository_metadata = (metadata.get("base") or {}).get("repo") or {}
            if repository_metadata.get("private") is not False:
                raise ValueError(
                    "PR %s#%s is not proven to be from a public repository"
                    % (item["repository"], item["pull_request"])
                )
            assigned_split = repository_split(str(item["repository"]), args.split_salt)
            if args.allow_manual_split:
                assigned_split = str(item.get("split", assigned_split))
            record = {
                "schema_version": CASE_SCHEMA_VERSION,
                "id": item.get(
                    "id", "%s#%s" % (item["repository"], item["pull_request"])
                ),
                "repository": item["repository"],
                "pull_request": int(item["pull_request"]),
                "split": assigned_split,
                "source": {
                    "kind": "public-github-pr",
                    "public_url": "https://github.com/%s/pull/%d"
                    % (item["repository"], int(item["pull_request"])),
                    "api_url": api_url,
                    "base_sha": str((metadata.get("base") or {}).get("sha", "")),
                    "head_sha": str((metadata.get("head") or {}).get("sha", "")),
                    "diff_sha256": sha256_text(diff),
                    "repository_visibility": "public",
                    "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "license": {
                        "spdx_id": license_spdx,
                        "evidence_url": license_evidence_url,
                    },
                },
                "annotation": {
                    "annotator": annotator,
                    "annotated_at": annotated_at,
                    "methodology": methodology,
                    "evidence_urls": [str(value) for value in evidence_urls],
                    "reviewer_count": int(item.get("reviewer_count", 1)),
                },
                "diff": diff,
                "after_files": item.get("after_files", {}),
                "expected_findings": item["expected_findings"],
                "repair_validation": item.get("repair_validation", {}),
            }
            validate_case(record)
            if not parsed.added_lines:
                raise ValueError("PR %s has no added lines" % record["id"])
            records.append(record)
            if len(records) >= args.limit:
                break
    if len(records) < args.limit:
        raise ValueError(
            "manifest produced %d records; %d required" % (len(records), args.limit)
        )
    manifest, integrity = DatasetManifest.from_cases(
        records, args.dataset_name, args.dataset_version,
        require_public_provenance=True,
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    manifest_path = args.output + ".manifest.json"
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {**manifest.to_dict(), "integrity": integrity}, handle,
            ensure_ascii=False, indent=2, sort_keys=True,
        )
        handle.write("\n")
    print("wrote %d labelled public PRs to %s" % (len(records), args.output))
    print("manifest:", manifest_path)


if __name__ == "__main__":
    main()
