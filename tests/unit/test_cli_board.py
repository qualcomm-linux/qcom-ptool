# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
CLI tests for platform-mode ``gen_partition`` and the ``show`` subcommand.
"""

from __future__ import annotations

import textwrap

import pytest

from qcom_ptool import gen_partition, show

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


def test_platform_mode_emits_one_xml_per_output(tmp_path):
    root = _tree(tmp_path)
    outs = [tmp_path / n for n in ("nvme.xml", "spinor.xml", "nor.xml")]
    args = [a for o in outs for a in ("-o", str(o))]
    rc = gen_partition.main(["gen_partition", "--platform", root + "/demo.yaml", *args])
    assert rc == 0
    assert 'label="efi"' in outs[0].read_text()
    assert 'label="cdt"' in outs[1].read_text()
    assert 'label="cdt_nor"' in outs[2].read_text()


def test_platform_mode_writes_name_and_storage_dirs(tmp_path):
    root = _tree(tmp_path)
    rc = gen_partition.main(["gen_partition", "--platform", root + "/demo.yaml", "-C", str(tmp_path)])
    assert rc == 0
    for out in ("demo/nvme0", "demo/spinor0", "demo-nor/spinor0"):
        assert (tmp_path / out / "partitions.xml").is_file()


def test_board_and_flavor_match_the_platform(tmp_path):
    root = _tree(tmp_path)
    rc = gen_partition.main(
        ["gen_partition", "--platform", root + "/demo.yaml", "-C", str(tmp_path / "p")]
    )
    assert rc == 0
    rc = gen_partition.main(
        [
            "gen_partition",
            "--board", root + "/boards/demo.yaml",
            "--flavor", root + "/flavors/demo.yaml",
            "-C", str(tmp_path / "bf"),
        ]
    )
    assert rc == 0
    for sid in ("nvme0", "spinor0"):
        platform_xml = tmp_path / "p" / "demo" / sid / "partitions.xml"
        explicit_xml = tmp_path / "bf" / sid / "partitions.xml"
        assert platform_xml.read_bytes() == explicit_xml.read_bytes()


def test_platform_mode_output_count_mismatch_returns_1(tmp_path):
    root = _tree(tmp_path)
    rc = gen_partition.main(
        ["gen_partition", "--platform", root + "/demo.yaml", "-o", str(tmp_path / "only.xml")]
    )
    assert rc == 1


def test_requires_exactly_one_source(tmp_path):
    root = _tree(tmp_path)
    # both -i and --platform -> usage() exits.
    with pytest.raises(SystemExit):
        gen_partition.main(
            ["gen_partition", "-i", "x.conf", "--platform", root + "/demo.yaml", "-o", "out.xml"]
        )


def test_board_takes_at_most_one_flavor(tmp_path):
    root = _tree(tmp_path)
    args = ["--flavor", root + "/flavors/demo.yaml", "--flavor", root + "/flavors/demo-nor.yaml"]
    with pytest.raises(SystemExit):
        gen_partition.main(["gen_partition", "--board", root + "/boards/demo.yaml", *args])


def test_self_contained_board_matches_the_platform(tmp_path):
    """One file holding the board and its layout emits what the platform does."""
    root = _tree(tmp_path)
    board = tmp_path / "out-of-tree.yaml"
    board.write_text(
        textwrap.dedent(_FILES["boards/demo.yaml"]).replace(
            "write-protect-boundary: 65536\n",
            "write-protect-boundary: 65536\n"
            "    grow-last-partition: true\n"
            "    partitions:\n"
            '      - {name: efi, size: "524288KB", type-guid: "%s", filename: efi.bin}\n'
            % GUID_A,
        )
    )
    assert gen_partition.main(["gen_partition", "--platform", root + "/demo.yaml", "-C", str(tmp_path / "p")]) == 0
    assert gen_partition.main(["gen_partition", "--board", str(board), "-C", str(tmp_path / "b")]) == 0
    assert sorted(p.name for p in (tmp_path / "b").iterdir()) == ["nvme0"]
    expected = (tmp_path / "p" / "demo" / "nvme0" / "partitions.xml").read_bytes()
    assert (tmp_path / "b" / "nvme0" / "partitions.xml").read_bytes() == expected


def test_legacy_single_storage_still_works(tmp_path):
    src = tmp_path / "single.yaml"
    src.write_text(
        textwrap.dedent(
            """
            disk:
              type: nvme
              size: 68719476736
            partitions:
              - name: efi
                size: "524288KB"
                type-guid: "%s"
                filename: efi.bin
            """ % GUID_A
        )
    )
    out = tmp_path / "out.xml"
    rc = gen_partition.main(["gen_partition", "-i", str(src), "-o", str(out)])
    assert rc == 0
    assert 'label="efi"' in out.read_text()


def test_show_prints_resolved_spec(tmp_path, capsys):
    root = _tree(tmp_path)
    rc = show.main(["show", "--platform", root + "/demo.yaml"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "name: demo" in out
    assert "nvme0" in out
    assert "spinor0" in out
    assert "cdt" in out


def test_show_board_and_flavor(tmp_path, capsys):
    root = _tree(tmp_path)
    rc = show.main(
        ["show", "--board", root + "/boards/demo.yaml", "--flavor", root + "/flavors/demo.yaml"]
    )
    assert rc == 0
    assert "efi.bin" in capsys.readouterr().out


def test_show_outputs_lists_platform_storages(tmp_path, capsys):
    root = _tree(tmp_path)
    rc = show.main(["show", "--outputs", root + "/demo.yaml"])
    assert rc == 0
    assert capsys.readouterr().out == "demo:demo/nvme0:demo/spinor0:demo-nor/spinor0\n"


def test_show_contents_lists_contents_outputs(tmp_path, capsys):
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
    rc = show.main(["show", "--contents", root + "/demo.yaml"])
    assert rc == 0
    assert capsys.readouterr().out == (
        "demo:demo/spinor0/contents.xml^demo/spinor0/partitions.xml"
        ":demo-nor/contents.xml^demo-nor/spinor0/partitions.xml\n"
    )


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
    assert show.main(["show", "--board", str(board)]) == 0
    out = capsys.readouterr().out
    assert "name: board" in out and "name: efi" in out and "chip: OUT" in out


def test_show_requires_a_source():
    with pytest.raises(SystemExit):
        show.main(["show"])
