# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""End-to-end checks of the GPT attribute bits ptool writes."""

import struct
import subprocess
import sys

import pytest

SECTOR = 512
GUID = "97D7B011-54DA-4835-B3C4-917AD6E73D74"


def _gpt_attributes(tmp_path, partition_fields):
    """Run gen_partition + ptool; return {label: attributes} from gpt_main0.bin."""
    spec = tmp_path / "p.yaml"
    xml = tmp_path / "p.xml"
    lines = [
        "disk:",
        "  type: emmc",
        "  size: 16777216",
        "  sector-size: %d" % SECTOR,
        "partitions:",
    ]
    for label, fields in partition_fields.items():
        lines += [
            "  - name: %s" % label,
            "    size: 64KB",
            '    type-guid: "%s"' % GUID,
            "    readonly: false",
        ]
        lines += ["    %s" % field for field in fields]
    spec.write_text("\n".join(lines) + "\n")
    for args in (
        ["qcom_ptool.gen_partition", "-i", str(spec), "-o", str(xml)],
        ["qcom_ptool.ptool", "-x", str(xml)],
    ):
        result = subprocess.run(
            [sys.executable, "-m", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    gpt = (tmp_path / "gpt_main0.bin").read_bytes()
    header = gpt[SECTOR : 2 * SECTOR]
    entries_lba, count, size = struct.unpack_from("<QII", header, 72)
    found = {}
    for i in range(count):
        entry = gpt[entries_lba * SECTOR + i * size :][:size]
        if entry[:16] == bytes(16):
            continue
        (attributes,) = struct.unpack_from("<Q", entry, 48)
        label = entry[56:128].decode("utf-16-le").rstrip("\0")
        found[label] = attributes
    return found


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        # EVE's layout: gptprio priority=2 + successful (bits 49 and 56)
        (["gptprio-priority: 2", "gptprio-successful: true"], 0x0102000000000000),
        (["gptprio-tries-left: 15"], 0x00F0000000000000),
        (
            ["gptprio-priority: 15", "gptprio-tries-left: 15", "gptprio-successful: true"],
            0x01FF000000000000,
        ),
        # raw bits pass through unchanged
        (['attributes: "0102000000000000"'], 0x0102000000000000),
        # a named gptprio field replaces the raw bits it covers
        (['attributes: "01F0000000000000"', "gptprio-tries-left: 3"], 0x0130000000000000),
        (['attributes: "0100000000000000"', "gptprio-successful: false"], 0),
        # existing qbootctl fields are unchanged
        (["priority: 3", "active: true", "successful: true"], 0x0047000000000000),
    ],
)
def test_gpt_attribute_bits(tmp_path, fields, expected):
    assert _gpt_attributes(tmp_path, {"rootfs": fields})["rootfs"] == expected
