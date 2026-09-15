# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Generate udev rules for Qualcomm raw partitions."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from qcom_ptool.loaders import load as load_spec

DATA_DIR = Path(__file__).with_name("data")
FILESYSTEM_NAMES_FILE = DATA_DIR / "filesystem-partition-names.list"
TEMPLATE_FILE = DATA_DIR / "55-qcom-raw-partitions-noblkid.rules.in"
RULES_PLACEHOLDER = "@QCOM_RAW_PARTITION_RULES@"
NAME_RE = re.compile(r"[A-Za-z0-9_.+-]+")
DEFAULT_LAYOUT_GLOB = "platforms/*/*/partitions.conf"


def load_filesystem_names() -> set[str]:
    """Load names of partitions that may contain filesystems."""
    names: set[str] = set()
    for line_number, line in enumerate(
        FILESYSTEM_NAMES_FILE.read_text(encoding="utf-8").splitlines(), start=1
    ):
        name = line.partition("#")[0].strip()
        if not name:
            continue
        if NAME_RE.fullmatch(name) is None:
            raise ValueError(
                f"{FILESYSTEM_NAMES_FILE}:{line_number}: invalid name: {name}"
            )
        if name in names:
            raise ValueError(
                f"{FILESYSTEM_NAMES_FILE}:{line_number}: duplicate name: {name}"
            )
        names.add(name)

    if not names:
        raise ValueError(f"filesystem name list is empty: {FILESYSTEM_NAMES_FILE}")
    return names


def load_partition_names(inputs: list[Path]) -> set[str]:
    """Load and merge partition names from all supplied layouts."""
    names: set[str] = set()
    for path in inputs:
        spec = load_spec(str(path))
        for partitions in spec["partitions"].values():
            for partition in partitions:
                name = partition["label"]
                if name and name != "last_parti":
                    if NAME_RE.fullmatch(name) is None:
                        raise ValueError(f"{path}: invalid partition name: {name}")
                    names.add(name)
    return names


def load_raw_partition_names(inputs: list[Path]) -> list[str]:
    """Return known raw partition names from the supplied layouts."""
    return sorted(load_partition_names(inputs) - load_filesystem_names())


def discover_inputs(inputs: list[Path] | None) -> list[Path]:
    """Use explicit layouts or discover all layouts in the current repo."""
    if inputs:
        return inputs

    discovered = sorted(Path.cwd().glob(DEFAULT_LAYOUT_GLOB))
    if not discovered:
        raise ValueError(
            "no partition layouts found; run from the qcom-ptool repository "
            "or provide one or more -i/--input paths"
        )
    return discovered


def render_rules(names: list[str]) -> str:
    """Render the udev rules template for the supplied partition names."""
    rules = "\n".join(
        f'ENV{{PARTNAME}}=="{name}", GOTO="qcom_raw_noblkid"'
        for name in names
    )
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    if template.count(RULES_PLACEHOLDER) != 1:
        raise ValueError("rules template must contain exactly one placeholder")
    return template.replace(RULES_PLACEHOLDER, rules)


def generate_rules(inputs: list[Path] | None = None) -> str:
    """Render rules for raw partitions in all supplied layouts."""
    return render_rules(load_raw_partition_names(discover_inputs(inputs)))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input",
        action="append",
        type=Path,
        help="partition layout to scan; may be repeated (defaults to platforms/*/*/partitions.conf)",
    )
    parser.add_argument("-o", "--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        content = generate_rules(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
