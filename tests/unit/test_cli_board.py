# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
CLI tests for the ``show`` subcommand: the same targets as ``build``.
"""

from __future__ import annotations

import textwrap

import pytest

from qcom_ptool import cli

GUID_A = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
GUID_B = "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"

_FILES = {
    "boards/demo.yaml": """
        storage:
          - id: nvme0
            type: nvme
            size: 68719476736
            sector-size: 512
            write-protect-boundary: 65536
          - id: spinor0
            type: spinor
            size: 67108864
            sector-size: 4096
            write-protect-boundary: 0
    """,
    "flavors/demo.yaml": """
        storage:
          - type: nvme
            grow-last-partition: true
            partitions:
              - {name: efi, size: "524288KB", type-guid: "%s", filename: efi.bin}
          - type: spinor
            partitions:
              - {name: cdt, size: "4KB", type-guid: "%s", filename: cdt.bin}
    """ % (GUID_A, GUID_B),
    "flavors/demo-nor.yaml": """
        storage:
          - type: spinor
            partitions:
              - {name: cdt_nor, size: "4KB", type-guid: "%s"}
    """ % GUID_B,
    "demo.yaml": """
        board: boards/demo.yaml
        flavors:
          - flavors/demo.yaml
          - flavor: flavors/demo-nor.yaml
            name: demo-nor
    """,
}


def _tree(tmp_path) -> str:
    root = tmp_path / "platforms"
    for rel, text in _FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
    return str(root)


def test_show_prints_resolved_spec(tmp_path, capsys):
    root = _tree(tmp_path)
    rc = cli.main(["show", root + "/demo.yaml"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "name: demo" in out
    assert "nvme0" in out
    assert "spinor0" in out
    assert "cdt" in out


def test_show_board_and_flavor(tmp_path, capsys):
    root = _tree(tmp_path)
    rc = cli.main(
        ["show", "-b", root + "/boards/demo.yaml", "-f", root + "/flavors/demo.yaml"]
    )
    assert rc == 0
    assert "efi.bin" in capsys.readouterr().out


def test_show_o_lists_platform_storages(tmp_path, capsys):
    root = _tree(tmp_path)
    rc = cli.main(["show", "-o", "out", root + "/demo.yaml"])
    assert rc == 0
    assert capsys.readouterr().out == "out/demo/nvme0/\nout/demo/spinor0/\nout/demo-nor/spinor0/\n"


def test_show_o_board_writes_storages_at_the_top(tmp_path, capsys):
    root = _tree(tmp_path)
    args = ["-b", root + "/boards/demo.yaml", "-f", root + "/flavors/demo.yaml"]
    assert cli.main(["show", "-o", "out", *args]) == 0
    assert capsys.readouterr().out == "out/nvme0/\nout/spinor0/\n"


def test_show_o_lists_contents(tmp_path, capsys):
    root = _tree(tmp_path)
    board = tmp_path / "platforms" / "boards" / "demo.yaml"
    board.write_text(board.read_text() + "contents: {chip: DEMO}\n")
    (tmp_path / "platforms" / "demo.yaml").write_text(
        textwrap.dedent(
            """
            board: boards/demo.yaml
            contents: {product-name: Demo.LE.0.0, location: spinor0}
            flavors:
              - flavors/demo.yaml
              - flavor: flavors/demo-nor.yaml
                name: demo-nor
                contents: {product-name: Demo.LE.0.0, location: /}
            """
        )
    )
    rc = cli.main(["show", "-o", "out", root + "/demo.yaml"])
    assert rc == 0
    assert capsys.readouterr().out.splitlines() == [
        "out/demo/nvme0/",
        "out/demo/spinor0/",
        "out/demo/spinor0/contents.xml",
        "out/demo-nor/spinor0/",
        "out/demo-nor/contents.xml",
    ]


def test_show_self_contained_board(tmp_path, capsys):
    board = tmp_path / "board.yaml"
    board.write_text(
        textwrap.dedent(
            """
            storage:
              - id: emmc
                type: emmc
                size: 1073741824
                partitions:
                  - {name: efi, size: "4KB", type-guid: "%s"}
            contents: {product-name: Out.LE.0.0, chip: OUT}
            """
            % GUID_A
        )
    )
    assert cli.main(["show", "-b", str(board)]) == 0
    out = capsys.readouterr().out
    assert "name: board" in out and "name: efi" in out and "chip: OUT" in out


def test_show_requires_a_source():
    with pytest.raises(SystemExit):
        cli.main(["show"])


@pytest.mark.parametrize(
    "args",
    [
        ["-b", "board.yaml", "-f", "a.yaml", "-f", "b.yaml"],
        ["-f", "flavor.yaml", "platform.yaml"],
        ["-b", "board.yaml", "platform.yaml"],
    ],
)
def test_show_takes_the_build_arguments(args):
    with pytest.raises(SystemExit):
        cli.main(["show", *args])
