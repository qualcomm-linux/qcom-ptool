# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the qcom-ptool CLI dispatcher."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from qcom_ptool import __version__
from qcom_ptool.cli import SUBCOMMANDS

REPO_ROOT = Path(__file__).resolve().parents[2]


def subprocess_env():
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not existing
        else os.pathsep.join((str(REPO_ROOT), existing))
    )
    return env


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "qcom_ptool.cli", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_version_flag():
    result = run_cli("--version")
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_help_lists_all_subcommands():
    result = run_cli("--help")
    assert result.returncode == 0
    for name in SUBCOMMANDS:
        assert name in result.stdout


def test_unknown_subcommand_rejected():
    result = run_cli("frobnicate")
    assert result.returncode == 2
    assert "frobnicate" in result.stderr


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_subcommand_dispatch(name, tmp_path):
    # Scripts exit non-zero without args; tmp_path because ptool writes files to CWD.
    result = subprocess.run(
        [sys.executable, "-m", "qcom_ptool.cli", name],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=subprocess_env(),
        timeout=10,
    )
    assert result.returncode != 0
    if name != "ptool":
        assert "usage" in (result.stdout + result.stderr).lower()
