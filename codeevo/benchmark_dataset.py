"""Build evaluation truth from reproducible security benchmarks, without annotators."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Tuple

from .diff_parser import parse_unified_diff
from .evaluation_dataset import CASE_SCHEMA_VERSION, repository_split, sha256_text


VUL4J_DATASET_URL = (
    "https://raw.githubusercontent.com/tuhh-softsec/Vul4J/main/"
    "dataset/vul4j_dataset.csv"
)
VUL4J_EVIDENCE_URL = "https://github.com/tuhh-softsec/Vul4J#reproduction-status"
VUL4J_LICENSE_URL = "https://github.com/tuhh-softsec/Vul4J#introduction"
NVD_CVE_URL = "https://nvd.nist.gov/vuln/detail/{cve_id}"
GITHUB_API = "https://api.github.com/repos/{repository}/commits/{sha}"
COMMIT_URL = re.compile(
    r"^https://github\.com/(?P<repository>[^/]+/[^/]+)/commit/(?P<sha>[0-9a-fA-F]{7,40})/?$"
)
MAPPED_CWE = re.compile(r"^CWE-\d+$", re.IGNORECASE)
_DOWNLOAD_CACHE_DIR = ""


class SourceRateLimitError(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def configure_download_cache(path: str) -> None:
    global _DOWNLOAD_CACHE_DIR
    _DOWNLOAD_CACHE_DIR = os.path.abspath(path) if path else ""
    if _DOWNLOAD_CACHE_DIR:
        os.makedirs(_DOWNLOAD_CACHE_DIR, exist_ok=True)


def _cache_path(url: str, accept: str) -> str:
    if not _DOWNLOAD_CACHE_DIR:
        return ""
    digest = hashlib.sha256((accept + "\n" + url).encode("utf-8")).hexdigest()
    return os.path.join(_DOWNLOAD_CACHE_DIR, digest + ".response")


def _request(
    url: str, accept: str, token: str = "", extra_headers: Dict[str, str] | None = None,
) -> bytes:
    headers = {
        "Accept": accept,
        "User-Agent": "codeevo-benchmark-importer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, headers=headers)
    cache_path = _cache_path(url, accept)
    if cache_path and os.path.isfile(cache_path):
        with open(cache_path, "rb") as handle:
            return handle.read()
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        pass
    else:
        context = ssl.create_default_context(cafile=certifi.where())
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as response:
                payload = response.read()
            if cache_path:
                temporary = cache_path + ".tmp-%d" % os.getpid()
                with open(temporary, "wb") as handle:
                    handle.write(payload)
                os.replace(temporary, cache_path)
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0":
                reset = exc.headers.get("X-RateLimit-Reset", "unknown")
                raise SourceRateLimitError(
                    "GitHub API rate limit exhausted; reset epoch is %s. "
                    "Set GITHUB_TOKEN and rerun to resume from cache." % reset
                ) from exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(
                    "source returned HTTP %d for %s" % (exc.code, url)
                ) from exc
            last_error = exc
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError("source request failed after 3 attempts for %s: %s" % (
        url, last_error,
    )) from last_error


def load_vul4j_rows(url: str = VUL4J_DATASET_URL) -> List[dict]:
    payload = _request(url, "text/csv").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(payload)))


def fetch_github_commit(
    repository: str, sha: str, token: str = "",
) -> Tuple[dict, str, str]:
    api_url = GITHUB_API.format(repository=repository, sha=sha)
    metadata = json.loads(_request(api_url, "application/vnd.github+json", token))
    diff = _request(api_url, "application/vnd.github.v3.diff", token).decode(
        "utf-8", errors="replace"
    )
    parents = metadata.get("parents") or []
    if len(parents) != 1:
        raise ValueError("benchmark fixes must have exactly one parent commit")
    full_sha = str(metadata.get("sha", ""))
    parent_sha = str(parents[0].get("sha", ""))
    if len(full_sha) != 40 or len(parent_sha) != 40:
        raise ValueError("GitHub did not return full commit SHAs")
    return metadata, diff, api_url


def fetch_nvd_severity(cve_id: str) -> Tuple[str, str, str]:
    """Return CodeEvo severity, CVSS vector, and immutable public evidence URL."""
    api_url = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=" + urllib.parse.quote(
        cve_id
    )
    nvd_key = os.environ.get("NVD_API_KEY", "").strip()
    extra_headers = {"apiKey": nvd_key} if nvd_key else {}
    payload = json.loads(_request(api_url, "application/json", extra_headers=extra_headers))
    vulnerabilities = payload.get("vulnerabilities") or []
    if not vulnerabilities:
        raise ValueError("NVD has no record for %s" % cve_id)
    metrics = (vulnerabilities[0].get("cve") or {}).get("metrics") or {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        values = metrics.get(key) or []
        if not values:
            continue
        preferred = next((item for item in values if item.get("type") == "Primary"), values[0])
        cvss = preferred.get("cvssData") or {}
        score = float(cvss.get("baseScore", 0.0))
        if score >= 9.0:
            severity = "critical"
        elif score >= 7.0:
            severity = "high"
        elif score >= 4.0:
            severity = "medium"
        else:
            severity = "low"
        return severity, str(cvss.get("vectorString", "")), NVD_CVE_URL.format(cve_id=cve_id)
    raise ValueError("NVD has no CVSS severity for %s" % cve_id)


def reverse_unified_diff(diff: str) -> str:
    """Reverse a normal Git diff while preserving correct hunk line coordinates."""
    output: List[str] = []
    lines = diff.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        if raw.startswith("diff --git a/"):
            match = re.match(r"diff --git a/(.+) b/(.+)$", raw)
            if match:
                output.append("diff --git a/%s b/%s" % (match.group(2), match.group(1)))
                index += 1
                continue
        if raw.startswith("index "):
            match = re.match(r"index ([0-9a-f]+)\.\.([0-9a-f]+)(.*)$", raw)
            if match:
                output.append("index %s..%s%s" % (match.group(2), match.group(1), match.group(3)))
                index += 1
                continue
        if raw.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
            old_path = raw[4:]
            new_path = lines[index + 1][4:]
            reverse_old = "/dev/null" if new_path == "/dev/null" else (
                "a/" + new_path[2:] if new_path.startswith("b/") else new_path
            )
            reverse_new = "/dev/null" if old_path == "/dev/null" else (
                "b/" + old_path[2:] if old_path.startswith("a/") else old_path
            )
            output.extend(("--- " + reverse_old, "+++ " + reverse_new))
            index += 2
            continue
        if raw.startswith("rename from ") and index + 1 < len(lines) and lines[index + 1].startswith("rename to "):
            output.extend((
                "rename from " + lines[index + 1][len("rename to "):],
                "rename to " + raw[len("rename from "):],
            ))
            index += 2
            continue
        hunk = re.match(
            r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", raw
        )
        if hunk:
            old_start, old_count, new_start, new_count, suffix = hunk.groups()
            old_range = old_start + (("," + old_count) if old_count is not None else "")
            new_range = new_start + (("," + new_count) if new_count is not None else "")
            output.append("@@ -%s +%s @@%s" % (new_range, old_range, suffix))
            index += 1
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            output.append("-" + raw[1:])
        elif raw.startswith("-") and not raw.startswith("---"):
            output.append("+" + raw[1:])
        else:
            output.append(raw)
        index += 1
    return "\n".join(output) + "\n"


def _license_from_repository(metadata: dict, repository: str) -> dict:
    license_document = metadata.get("repository_license") or {}
    license_info = license_document.get("license") or {}
    spdx_id = str(license_info.get("spdx_id") or "").strip()
    if not spdx_id or spdx_id == "NOASSERTION":
        raise ValueError("repository %s has no machine-verifiable SPDX license" % repository)
    evidence_url = str(license_document.get("html_url") or "").strip()
    if not evidence_url.startswith("https://github.com/"):
        raise ValueError("repository %s has no public license evidence URL" % repository)
    return {"spdx_id": spdx_id, "evidence_url": evidence_url}


def _metadata_with_repository(
    repository: str, sha: str, token: str,
) -> Tuple[dict, str, str]:
    metadata, diff, api_url = fetch_github_commit(repository, sha, token)
    repository_api = "https://api.github.com/repos/%s" % repository
    repository_info = json.loads(
        _request(repository_api, "application/vnd.github+json", token)
    )
    if repository_info.get("private") is not False:
        raise ValueError("benchmark repository must be public")
    license_document = json.loads(
        _request(repository_api + "/license", "application/vnd.github+json", token)
    )
    metadata["repository"] = repository_info
    metadata["repository_license"] = license_document
    return metadata, diff, api_url


def build_vul4j_case_pair(
    row: dict, benchmark_version: str, split_salt: str, token: str = "",
    verification_status: str = "published-reproducible",
) -> List[dict]:
    cwe = str(row.get("cwe_id", "")).upper().strip()
    cve = str(row.get("cve_id", "")).upper().strip()
    if not MAPPED_CWE.fullmatch(cwe):
        raise ValueError("Vul4J record has no mapped CWE")
    if not cve.startswith("CVE-"):
        raise ValueError("Vul4J record has no CVE for NVD severity")
    match = COMMIT_URL.fullmatch(str(row.get("human_patch", "")).strip())
    if not match:
        raise ValueError("Vul4J human_patch is not a GitHub commit URL")
    repository = match.group("repository")
    sha = match.group("sha")
    metadata, forward_diff, api_url = _metadata_with_repository(repository, sha, token)
    reverse_diff = reverse_unified_diff(forward_diff)
    forward_parsed = parse_unified_diff(forward_diff)
    reverse_parsed = parse_unified_diff(reverse_diff)
    if not forward_parsed.added_lines or not reverse_parsed.added_lines:
        raise ValueError("patch cannot produce both risk and clean scoreable cases")
    severity, vector, severity_url = fetch_nvd_severity(cve)
    full_sha = str(metadata["sha"])
    parent_sha = str(metadata["parents"][0]["sha"])
    split = repository_split(repository, split_salt)
    vul_id = str(row.get("vul_id", "")).strip()
    record_hash = hashlib.sha256(_canonical_json(row).encode("utf-8")).hexdigest()
    repository_license = _license_from_repository(metadata, repository)
    shared_source = {
        "kind": "benchmark-derived",
        "public_url": str(row["human_patch"]),
        "api_url": api_url,
        "repository_visibility": "public",
        "repository_license": repository_license,
        "benchmark": {
            "name": "Vul4J",
            "version": benchmark_version,
            "record_id": vul_id,
            "record_sha256": record_hash,
            "record": dict(row),
            "dataset_url": VUL4J_DATASET_URL,
            "license": {"spdx_id": "CC-BY-4.0", "evidence_url": VUL4J_LICENSE_URL},
        },
        "verification": {
            "kind": "benchmark-reproduction",
            "status": verification_status,
            "command": "vul4j reproduce -i %s" % vul_id,
            "evidence_url": VUL4J_EVIDENCE_URL,
            "failing_tests": str(row.get("failing_tests", "")),
        },
    }
    derivation = {
        "original_fix_url": str(row["human_patch"]),
        "original_fix_sha": full_sha,
        "original_parent_sha": parent_sha,
        "source_diff_sha256": sha256_text(forward_diff),
        "localization_method": "candidate region bounded by production lines removed by the security fix",
        "cwe_method": "Vul4J cwe_id",
        "severity_method": "NVD CVSS base score mapped to CodeEvo bands",
        "severity_evidence_url": severity_url,
        "cvss_vector": vector,
    }
    source_risk = {
        **shared_source,
        "diff_sha256": sha256_text(reverse_diff),
        "derivation": {
            **derivation,
            "patch_operation": "reverse",
            "direction": "vulnerability-introducing",
        },
    }
    localized: Dict[str, List[int]] = {}
    for line in reverse_parsed.added_lines:
        normalized = "/" + line.path.lower()
        if (
            line.path.lower().endswith(".java")
            and "/test/" not in normalized
            and line.content.strip()
        ):
            localized.setdefault(line.path, []).append(line.line)
    # One target-CVE finding per changed production file. This avoids pretending
    # an automatic converter knows which individual removed statement is the root cause.
    if not localized:
        raise ValueError("reverse patch has no automatically localizable production Java lines")
    anchor_path, anchor_lines = sorted(localized.items())[0]
    risk_findings = [{
        "path": anchor_path,
        "start_line": min(anchor_lines),
        "end_line": max(anchor_lines),
        "cwe": cwe,
        "severity": severity,
    }]
    risk = {
        "schema_version": CASE_SCHEMA_VERSION,
        "id": "%s-risk" % vul_id,
        "repository": repository,
        "pull_request": 0,
        "split": split,
        "source": source_risk,
        "annotation": {
            "methodology": "benchmark-derived; no human annotation",
            "reviewer_count": 0,
            "label_scope": "target-cwe-case-level",
            "evidence_urls": [str(row["human_patch"]), severity_url],
        },
        "diff": reverse_diff,
        "scoring": {"scope": "target-cwe", "target_cwes": [cwe]},
        "expected_findings": risk_findings,
    }
    clean = {
        "schema_version": CASE_SCHEMA_VERSION,
        "id": "%s-clean" % vul_id,
        "repository": repository,
        "pull_request": 0,
        "split": split,
        "source": {
            **shared_source,
            "diff_sha256": sha256_text(forward_diff),
            "derivation": {
                **derivation,
                "patch_operation": "forward",
                "direction": "security-fix",
            },
        },
        "annotation": {
            "methodology": "benchmark-derived; no human annotation",
            "reviewer_count": 0,
            "label_scope": "target-cwe-case-level",
            "evidence_urls": [str(row["human_patch"]), severity_url],
        },
        "diff": forward_diff,
        "scoring": {"scope": "target-cwe", "target_cwes": [cwe]},
        "expected_findings": [],
    }
    return [risk, clean]


def select_vul4j_rows(rows: Iterable[dict], limit: int, offset: int = 0) -> List[dict]:
    eligible = [
        row for row in rows
        if MAPPED_CWE.fullmatch(str(row.get("cwe_id", "")).strip())
        and str(row.get("cve_id", "")).startswith("CVE-")
        and COMMIT_URL.fullmatch(str(row.get("human_patch", "")).strip())
    ]
    return eligible[offset:offset + limit]
