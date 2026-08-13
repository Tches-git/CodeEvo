"""CLI for importing reproducible Vul4J cases without human annotation."""
import argparse
import json
import os

from .benchmark_dataset import (
    VUL4J_DATASET_URL,
    SourceRateLimitError,
    build_vul4j_case_pair,
    configure_download_cache,
    load_vul4j_rows,
    select_vul4j_rows,
)
from .evaluation_dataset import DatasetManifest
from .evaluation_harness import validate_case


def main():
    parser = argparse.ArgumentParser(
        description="Convert Vul4J fixes to target-CVE risk/clean evaluation pairs."
    )
    parser.add_argument("output", help="Evaluation JSONL output")
    parser.add_argument("--limit", type=int, default=20, help="Vul4J records; writes 2x cases")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--dataset-url", default=VUL4J_DATASET_URL)
    parser.add_argument("--benchmark-version", default="main-2026-05-20")
    parser.add_argument("--dataset-name", default="codeevo-vul4j-derived")
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--split-salt", default="codeevo-vul4j-v1")
    parser.add_argument(
        "--cache-dir", default="",
        help="Response cache; defaults to OUTPUT.cache and supports rate-limit resume.",
    )
    parser.add_argument(
        "--locally-reproduced", action="store_true",
        help="Use only after running the emitted vul4j reproduce commands locally.",
    )
    args = parser.parse_args()
    if args.limit <= 0 or args.offset < 0:
        parser.error("--limit must be positive and --offset cannot be negative")

    configure_download_cache(args.cache_dir or (os.path.abspath(args.output) + ".cache"))
    all_rows = load_vul4j_rows(args.dataset_url)
    rows = select_vul4j_rows(all_rows, len(all_rows), args.offset)
    token = os.environ.get("GITHUB_TOKEN", "")
    status = "locally-reproduced" if args.locally_reproduced else "published-reproducible"
    cases = []
    skipped = []
    for row in rows:
        if len(cases) // 2 >= args.limit:
            break
        try:
            pair = build_vul4j_case_pair(
                row, args.benchmark_version, args.split_salt, token, status
            )
        except SourceRateLimitError:
            raise
        except (RuntimeError, ValueError) as exc:
            skipped.append({"vul_id": row.get("vul_id", ""), "reason": str(exc)})
            print("[skip] %s: %s" % (row.get("vul_id", ""), exc))
            continue
        for case in pair:
            validate_case(case)
        cases.extend(pair)
        print("[%d/%d] %s -> %d cases" % (
            len(cases) // 2, args.limit, row["vul_id"], len(pair)
        ))
    if len(cases) // 2 != args.limit:
        raise ValueError(
            "only %d of %d requested Vul4J records could be converted"
            % (len(cases) // 2, args.limit)
        )

    manifest, integrity = DatasetManifest.from_cases(
        cases, args.dataset_name, args.dataset_version,
        require_benchmark_provenance=True,
    )
    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    with open(output + ".manifest.json", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {**manifest.to_dict(), "integrity": integrity, "skipped": skipped}, handle,
            ensure_ascii=False, indent=2, sort_keys=True,
        )
        handle.write("\n")
    print("wrote %d benchmark-derived cases to %s" % (len(cases), output))
    print("manifest:", output + ".manifest.json")
