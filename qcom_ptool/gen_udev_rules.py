# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Generate udev rules for reviewed raw partitions in selected layouts."""

from __future__ import annotations

import argparse
import fnmatch
import getopt
import re
import sys
from pathlib import Path

from qcom_ptool.loaders import load as load_spec

DATA_DIR = Path(__file__).with_name("data")
POLICY_FILE = DATA_DIR / "approved-raw-partition-patterns.list"
TEMPLATE_FILE = DATA_DIR / "55-qcom-raw-partitions-noblkid.rules.in"
RULES_PLACEHOLDER = "@QCOM_RAW_PARTITION_RULES@"
LABEL_RE = re.compile(r"[A-Za-z0-9_.+-]+")
PATTERN_RE = re.compile(r"[A-Za-z0-9_.+*?\[\]-]+")


def load_patterns() -> list[str]:
    """Return non-comment entries from the packaged policy file."""
    patterns: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        POLICY_FILE.read_text(encoding="utf-8").splitlines(), start=1
    ):
        pattern = line.partition("#")[0].strip()
        if not pattern:
            continue
        if PATTERN_RE.fullmatch(pattern) is None:
            raise ValueError(f"{POLICY_FILE}:{line_number}: invalid pattern: {pattern}")
        if pattern in seen:
            raise ValueError(f"{POLICY_FILE}:{line_number}: duplicate pattern: {pattern}")
        patterns.append(pattern)
        seen.add(pattern)

    if not patterns:
        raise ValueError(f"approved pattern list is empty: {POLICY_FILE}")
    return patterns


def collect_labels(input_paths: list[Path]) -> set[str]:
    """Return partition labels defined by the selected layouts."""
    labels: set[str] = set()
    for path in input_paths:
        spec = load_spec(str(path))
        labels.update(
            entry["label"]
            for entries in spec["partitions"].values()
            for entry in entries
        )
    return labels


def generate_rules(input_paths: list[Path]) -> str:
    """Render udev rules for approved labels present in the layouts."""
    patterns = load_patterns()
    approved_labels = {
        label
        for label in collect_labels(input_paths)
        if any(fnmatch.fnmatchcase(label, pattern) for pattern in patterns)
    }
    invalid_labels = sorted(
        label for label in approved_labels if LABEL_RE.fullmatch(label) is None
    )
    if invalid_labels:
        raise ValueError(f"invalid approved partition label: {invalid_labels[0]!r}")

    labels = sorted(approved_labels)
    if not labels:
        return ""

    rules = "\n".join(
        f'ENV{{PARTNAME}}=="{label}", GOTO="qcom_raw_noblkid"'
        for label in labels
    )
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    if template.count(RULES_PLACEHOLDER) != 1:
        raise ValueError("rules template must contain exactly one placeholder")
    return template.replace(RULES_PLACEHOLDER, rules)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input",
        action="append",
        required=True,
        type=Path,
        dest="inputs",
        help="partition layout to include; repeat for additional storage",
    )
    parser.add_argument("-o", "--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        content = generate_rules(args.inputs)
        if not content:
            args.output.unlink(missing_ok=True)
            print("skipped: selected layouts contain no approved raw partitions")
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    except (OSError, ValueError, getopt.GetoptError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
