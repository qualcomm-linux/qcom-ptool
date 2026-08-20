# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

from pathlib import Path

import pytest

from qcom_ptool import gen_udev_rules


def write_layout(path: Path, labels: list[str]) -> None:
    partitions = "".join(
        f"--partition --name={label} --size=1KB "
        "--type-guid=00000000-0000-0000-0000-000000000000\n"
        for label in labels
    )
    path.write_text(
        "--disk --type=ufs --size=1048576\n" + partitions,
        encoding="utf-8",
    )


def test_generate_rules_filters_and_combines_layouts(tmp_path: Path) -> None:
    first = tmp_path / "first.conf"
    second = tmp_path / "second.conf"
    write_layout(first, ["rootfs", "xbl_a"])
    write_layout(second, ["xbl_a", "ALIGN_TO_128K_7"])

    rules = gen_udev_rules.generate_rules([first, second])

    assert 'ENV{PARTNAME}=="xbl_a"' in rules
    assert 'ENV{PARTNAME}=="ALIGN_TO_128K_7"' in rules
    assert rules.count('ENV{PARTNAME}=="xbl_a"') == 1
    assert "ALIGN_TO_128K_*" not in rules
    assert "rootfs" not in rules


def test_generate_rules_rejects_unsafe_approved_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gen_udev_rules,
        "collect_labels",
        lambda _: {'ALIGN_TO_128K_", RUN+="/bin/true'},
    )

    with pytest.raises(ValueError, match="invalid approved partition label"):
        gen_udev_rules.generate_rules([])


def test_load_patterns_rejects_unsafe_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = tmp_path / "patterns.list"
    policy.write_text('xbl_[ab]\nxbl_", RUN+="/bin/true\n', encoding="utf-8")
    monkeypatch.setattr(gen_udev_rules, "POLICY_FILE", policy)

    with pytest.raises(ValueError, match="invalid pattern") as error:
        gen_udev_rules.load_patterns()

    assert f"{policy}:2:" in str(error.value)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("xbl_a\nxbl_a\n", "duplicate pattern"),
        ("# comments only\n", "approved pattern list is empty"),
    ],
)
def test_load_patterns_rejects_invalid_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    message: str,
) -> None:
    policy = tmp_path / "patterns.list"
    policy.write_text(content, encoding="utf-8")
    monkeypatch.setattr(gen_udev_rules, "POLICY_FILE", policy)

    with pytest.raises(ValueError, match=message):
        gen_udev_rules.load_patterns()


def test_main_writes_rules(tmp_path: Path) -> None:
    layout = tmp_path / "partitions.conf"
    output = tmp_path / "rules.d" / "55-qcom.rules"
    write_layout(layout, ["cdt"])

    assert gen_udev_rules.main(["-i", str(layout), "-o", str(output)]) == 0
    assert 'ENV{PARTNAME}=="cdt"' in output.read_text(encoding="utf-8")


def test_main_skips_output_without_approved_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = tmp_path / "partitions.conf"
    output = tmp_path / "rules.d" / "55-qcom.rules"
    write_layout(layout, ["rootfs"])
    output.parent.mkdir(parents=True)
    output.write_text("stale", encoding="utf-8")

    assert gen_udev_rules.main(["-i", str(layout), "-o", str(output)]) == 0
    assert not output.exists()
    assert "no approved raw partitions" in capsys.readouterr().out
