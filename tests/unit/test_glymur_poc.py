# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Proof-of-concept parity check for the Glymur-CRD YAML migration.

The resolved YAML board (with the Debian HLOS variant) must reduce to exactly
the same LoadedSpec as the legacy per-storage .conf files, which guarantees
byte-identical partitions.xml and GPT output. This test guards against silent
drift while both source forms coexist during the migration.
"""

from __future__ import annotations

import os

from qcom_ptool.board import board_to_specs, resolve_board
from qcom_ptool.loaders import load as load_spec

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BOARD = os.path.join(REPO, "platforms", "boards", "glymur-crd.yaml")
NVME_CONF = os.path.join(REPO, "platforms", "glymur-crd", "nvme", "partitions.conf")
SPINOR_CONF = os.path.join(REPO, "platforms", "glymur-crd", "spinor", "partitions.conf")


def test_glymur_yaml_reduces_to_the_conf_specs():
    board = resolve_board(BOARD, hlos="qcom-deb-images")
    specs = dict(board_to_specs(board))
    assert specs["nvme0"] == load_spec(NVME_CONF)
    assert specs["spinor0"] == load_spec(SPINOR_CONF)


def test_glymur_storage_order_is_preserved():
    board = resolve_board(BOARD, hlos="qcom-deb-images")
    assert [sid for sid, _ in board_to_specs(board)] == ["nvme0", "spinor0"]
