# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Tests for ``qcom-ptool build``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from qcom_ptool import build
from qcom_ptool.board import resolve_platform

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = REPO_ROOT / "platforms"


def _artifacts(outdir: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(outdir)): p.read_bytes()
        for p in sorted(outdir.rglob("*"))
        if p.is_file()
    }


def test_platform_builds_every_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("PTOOL_SEED", "qcom-ptool-test")
    rc = build.main(["build", "-o", str(tmp_path), str(PLATFORMS / "iq-615-evk.yaml")])
    assert rc == 0
    for out in ("iq-615-evk/ufs", "iq-615-evk-emmc/emmc"):
        for name in ("partitions.xml", "gpt_main0.bin", "rawprogram0.xml", "patch0.xml"):
            assert (tmp_path / out / name).is_file()


def test_board_and_flavors_match_the_platform(tmp_path, monkeypatch):
    monkeypatch.setenv("PTOOL_SEED", "qcom-ptool-test")
    assert build.main(
        ["build", "-o", str(tmp_path / "p"), str(PLATFORMS / "qcs6490-rb3gen2.yaml")]
    ) == 0
    assert build.main(
        [
            "build",
            "-o", str(tmp_path / "bf"),
            "-b", str(PLATFORMS / "boards" / "qcs6490-rb3gen2.yaml"),
            "-f", str(PLATFORMS / "flavors" / "kodiak-ufs.yaml"),
        ]
    ) == 0
    platform = _artifacts(tmp_path / "p" / "qcs6490-rb3gen2")
    # Only the platform completes the board's contents metadata.
    assert platform.pop("ufs/contents.xml")
    assert platform == _artifacts(tmp_path / "bf")


def _manifest() -> dict[str, str]:
    lines = (REPO_ROOT / "tests" / "integration" / "checksums.sha256").read_text().splitlines()
    return {path: digest for digest, path in (line.split() for line in lines)}


@pytest.mark.parametrize("platform", ["glymur-crd", "iq-8275-evk"])
def test_platform_build_matches_the_manifest(tmp_path, monkeypatch, platform):
    """Byte-identical to the make pipeline, contents.xml included."""
    monkeypatch.setenv("PTOOL_SEED", "qcom-ptool-ci")
    assert build.main(["build", "-o", str(tmp_path), str(PLATFORMS / (platform + ".yaml"))]) == 0
    manifest = _manifest()
    built = {
        "platforms/" + path: hashlib.sha256(data).hexdigest()
        for path, data in _artifacts(tmp_path).items()
    }
    assert any(path.endswith("/contents.xml") for path in built)
    assert built == {path: manifest[path] for path in built}


def test_self_contained_board_matches_the_platform(tmp_path, monkeypatch):
    """A resolved configuration, saved as one out-of-tree board file, builds
    the same artifacts as its platform."""
    monkeypatch.setenv("PTOOL_SEED", "qcom-ptool-test")
    (config,) = resolve_platform(str(PLATFORMS / "glymur-crd.yaml"))
    board = tmp_path / "glymur-crd.yaml"
    document = {"storage": config["storage"], "contents": config["contents"]}
    board.write_text(yaml.safe_dump(document, sort_keys=False))
    assert build.main(["build", "-o", str(tmp_path / "b"), "-b", str(board)]) == 0
    assert build.main(["build", "-o", str(tmp_path / "p"), str(PLATFORMS / "glymur-crd.yaml")]) == 0
    built = _artifacts(tmp_path / "b")
    assert "spinor/contents.xml" in built
    assert built == _artifacts(tmp_path / "p" / "glymur-crd")


def test_flavor_on_another_board(tmp_path, monkeypatch):
    """Flavors are board-agnostic: any board with a UFS storage takes one."""
    monkeypatch.setenv("PTOOL_SEED", "qcom-ptool-test")
    rc = build.main(
        [
            "build",
            "-o", str(tmp_path),
            "-b", str(PLATFORMS / "boards" / "qcs8550-rb5gen2.yaml"),
            "-f", str(PLATFORMS / "flavors" / "kodiak-ufs.yaml"),
        ]
    )
    assert rc == 0
    assert (tmp_path / "ufs" / "gpt_main0.bin").is_file()


def test_unresolvable_input_returns_1(tmp_path):
    rc = build.main(
        [
            "build",
            "-o", str(tmp_path),
            "-b", str(PLATFORMS / "boards" / "qcs6490-rb3gen2.yaml"),
            "-f", str(PLATFORMS / "flavors" / "talos-emmc.yaml"),
        ]
    )
    assert rc == 1


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["-b", "board.yaml", "-f", "a.yaml", "-f", "b.yaml"],
        ["-f", "flavor.yaml", "platform.yaml"],
        ["-b", "board.yaml", "-f", "flavor.yaml", "platform.yaml"],
    ],
)
def test_bad_arguments_print_usage(args):
    with pytest.raises(SystemExit):
        build.main(["build", *args])
