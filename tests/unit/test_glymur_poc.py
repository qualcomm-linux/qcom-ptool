# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Structural regression test for the migrated Glymur-CRD YAML board.

Byte-for-byte fidelity of the emitted artifacts is enforced by the pinned
manifest (tests/integration/checksums.sha256, checked by `make
check-checksums`). This test guards the board's shape at the unit level: it
resolves with the Debian HLOS variant and asserts the two storages, their
partition order, and that the rootfs size/filename come from the variant.
"""

from __future__ import annotations

import os

from qcom_ptool.board import board_to_specs, resolve_board

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BOARD = os.path.join(REPO, "platforms", "boards", "glymur-crd.yaml")


def test_glymur_resolves_two_storages_in_order():
    board = resolve_board(BOARD, hlos="qcom-deb-images")
    specs = board_to_specs(board)
    assert [sid for sid, _ in specs] == ["nvme0", "spinor0"]


def test_glymur_nvme_layout_and_variant_rootfs():
    board = resolve_board(BOARD, hlos="qcom-deb-images")
    nvme = dict(board_to_specs(board))["nvme0"]
    labels = [p["label"] for p in nvme["partitions"]["0"]]
    assert labels == ["efi", "rootfs"]
    rootfs = nvme["partitions"]["0"][1]
    # Supplied by variants/hlos/qcom-deb-images.yaml.
    assert rootfs["size_in_kb"] == "33554432"
    assert rootfs["filename"] == "rootfs.img"


def test_glymur_spinor_has_full_partition_list():
    board = resolve_board(BOARD, hlos="qcom-deb-images")
    spinor = dict(board_to_specs(board))["spinor0"]
    labels = [p["label"] for p in spinor["partitions"]["0"]]
    assert len(labels) == 65
    assert labels[0] == "cdt"
    assert labels[-1] == "dtb_b"
