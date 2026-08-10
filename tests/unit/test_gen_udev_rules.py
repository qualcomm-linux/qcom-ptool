# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

from pathlib import Path

import pytest

from qcom_ptool import gen_udev_rules


REPO_ROOT = Path(__file__).resolve().parents[2]
LAYOUT = REPO_ROOT / "platforms" / "qcs6490-rb3gen2" / "ufs" / "partitions.conf"


def test_generate_rules_uses_layout_names() -> None:
    rules = gen_udev_rules.generate_rules([LAYOUT])

    assert 'ENV{PARTNAME}=="xbl_a"' in rules
    assert 'ENV{PARTNAME}=="cdt"' in rules
    assert "rootfs" not in rules
    assert 'ENV{PARTNAME}=="not-in-layout"' not in rules


def test_generate_rules_merges_layouts_and_deduplicates(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.conf"
    second = tmp_path / "second.conf"
    first.write_text(
        "--disk --type=ufs --size=1\n"
        "--partition --name=raw_a --size=1KB --type-guid=1\n"
        "--partition --name=rootfs --size=1KB --type-guid=2\n",
        encoding="utf-8",
    )
    second.write_text(
        "--disk --type=ufs --size=1\n"
        "--partition --name=raw_a --size=1KB --type-guid=1\n"
        "--partition --name=raw_b --size=1KB --type-guid=2\n",
        encoding="utf-8",
    )
    rules = gen_udev_rules.generate_rules([first, second])

    assert rules.count('ENV{PARTNAME}=="raw_a"') == 1
    assert 'ENV{PARTNAME}=="raw_b"' in rules
    assert 'ENV{PARTNAME}=="rootfs"' not in rules


def test_generate_rules_preserves_persistent_links() -> None:
    rules = gen_udev_rules.generate_rules([LAYOUT])

    assert 'ENV{PARTNAME}=="", GOTO="qcom_raw_links"' in rules
    assert 'ENV{UDEV_DISABLE_PERSISTENT_STORAGE_BLKID_FLAG}="1"' in rules
    assert "UDEV_DISABLE_PERSISTENT_STORAGE_RULES_FLAG" not in rules
    assert 'SYMLINK+="disk/by-partuuid/$env{PARTUUID}"' in rules
    assert 'SYMLINK+="disk/by-partlabel/$env{PARTNAME}"' in rules


def test_load_filesystem_names_rejects_unsafe_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = tmp_path / "names.list"
    policy.write_text('rootfs\nrootfs", RUN+="/bin/true\n', encoding="utf-8")
    monkeypatch.setattr(gen_udev_rules, "FILESYSTEM_NAMES_FILE", policy)

    with pytest.raises(ValueError, match="invalid name") as error:
        gen_udev_rules.load_filesystem_names()

    assert f"{policy}:2:" in str(error.value)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("xbl_a\nxbl_a\n", "duplicate name"),
        ("# comments only\n", "filesystem name list is empty"),
    ],
)
def test_load_filesystem_names_rejects_invalid_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    message: str,
) -> None:
    policy = tmp_path / "names.list"
    policy.write_text(content, encoding="utf-8")
    monkeypatch.setattr(gen_udev_rules, "FILESYSTEM_NAMES_FILE", policy)

    with pytest.raises(ValueError, match=message):
        gen_udev_rules.load_filesystem_names()


def test_main_writes_rules(tmp_path: Path) -> None:
    output = tmp_path / "rules.d" / "55-qcom.rules"

    assert gen_udev_rules.main(["-i", str(LAYOUT), "-o", str(output)]) == 0
    assert 'ENV{PARTNAME}=="cdt"' in output.read_text(encoding="utf-8")


def test_main_discovers_repo_layouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    output = tmp_path / "rules"

    assert gen_udev_rules.main(["-o", str(output)]) == 0
    assert 'ENV{PARTNAME}=="xbl_a"' in output.read_text(encoding="utf-8")


def test_generate_rules_rejects_missing_default_layouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="no partition layouts found"):
        gen_udev_rules.generate_rules()
