# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for the contents metadata emitter (qcom_ptool/contents_yaml.py).

The contract is byte-equivalence of the generated contents.xml: a flavor's
metadata builds the tree the equivalent contents.xml.in parsed into, and the
placeholder entries are position-independent - UpdateMetaData removes them
and appends the generated entries at the end of the build - so the pipeline
emits identical files from either source.
"""

from __future__ import annotations

import textwrap

import pytest

from qcom_ptool import gen_contents
from qcom_ptool.contents_yaml import (
    ContentsError,
    build_contents_root,
    contents_paths,
    default_storage,
)

GUID_A = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
GUID_B = "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"

# A compact template exercising every construct the repo's templates used:
# an extra product flavor, a second chipid, device programmers with and
# without attributes, literal downloads (sahara and flavored), and the
# three placeholder entries - deliberately interleaved between the real
# entries, as the sahara-family templates had them, to pin that their
# position never influences the output.
_TEMPLATE = """\
<?xml version="1.0" ?>
<contents>
  <product_flavors cmm_pf_var="PRODUCT_FLAVORS">
    <pf>
      <name>default</name>
      <component>
        <name>common</name>
        <flavor>default</flavor>
      </component>
      <component>
        <name>apps</name>
        <flavor>default</flavor>
      </component>
    </pf>
    <pf>
      <name>sail_nor</name>
      <component>
        <name>common</name>
        <flavor>sail_nor</flavor>
      </component>
    </pf>
  </product_flavors>
  <product_info>
    <product_name>Demo.LE.0.0</product_name>
    <hlos_type>LE</hlos_type>
    <chipid flavor="default" storage_type="ufs" flash_phase="1">DEMO</chipid>
    <chipid flavor="sail_nor" storage_type="spinor" flash_phase="2">DEMO</chipid>
    <additional_chipid>DEMO1,DEMO2</additional_chipid>
    <meta_type>FULL_STACK</meta_type>
    <build_type>K2L</build_type>
  </product_info>
  <builds_flat>
    <build>
      <name>apps</name>
      <role>apps</role>
      <chipset>DEMOCHIPSET</chipset>
      <windows_root_path>.\\</windows_root_path>
      <linux_root_path>./</linux_root_path>
      <image_dir>build</image_dir>
    </build>
    <build>
      <name>common</name>
      <role>common</role>
      <chipset>DEMOCHIPSET</chipset>
      <windows_root_path>.\\</windows_root_path>
      <linux_root_path>./</linux_root_path>
      <image_dir>common</image_dir>
      <device_programmer cmm_file_var="FIREHOSE_DDR_ELF">
        <file_name>qsahara_device_programmer.xml</file_name>
        <file_path>.</file_path>
      </device_programmer>
      <download_file>
        <fastboot_complete>{partition_name}</fastboot_complete>
        <file_name>{image_name}</file_name>
        <file_path>.</file_path>
      </download_file>
      <download_file qsahara_image_id="21">
        <file_name>xbl_sc.elf</file_name>
        <file_path>.</file_path>
      </download_file>
      <device_programmer firehose_type="lite">
        <file_name>prog_firehose_lite.elf</file_name>
        <file_path>.</file_path>
      </device_programmer>
      <partition_file>
        <storage_type>{storage_type}</storage_type>
        <file_name>{partition_file_name}</file_name>
        <file_path flavor="default">.</file_path>
      </partition_file>
      <partition_patch_file>
        <storage_type>{storage_type}</storage_type>
        <file_name>{partition_patch_file_name}</file_name>
        <file_path flavor="default">.</file_path>
      </partition_patch_file>
      <download_file storage_type="spinor" fastboot_complete="SAIL_HYP">
        <file_name>sailhyp.elf</file_name>
        <file_path flavor="sail_nor">./sail_nor</file_path>
      </download_file>
      <partition_file storage_type="spinor" flavor="sail_nor">
        <file_name>rawprogram0.xml</file_name>
        <file_path flavor="sail_nor">./sail_nor</file_path>
      </partition_file>
    </build>
  </builds_flat>
</contents>
"""

_META = {
    "product-name": "Demo.LE.0.0",
    "hlos-type": "LE",
    "chip": "DEMO",
    "chipset": "DEMOCHIPSET",
    "additional-chipids": ["DEMO1", "DEMO2"],
    "apps-image-dir": "build",
    "chipids": [{"flavor": "sail_nor", "storage": "spinor", "flash-phase": 2}],
    "product-flavors": [{"name": "sail_nor", "components": ["common"]}],
    "common": [
        {
            "device-programmer": {
                "file": "qsahara_device_programmer.xml",
                "attributes": {"cmm_file_var": "FIREHOSE_DDR_ELF"},
            }
        },
        {
            "download": {
                "file": "xbl_sc.elf",
                "attributes": {"qsahara_image_id": "21"},
            }
        },
        {
            "device-programmer": {
                "file": "prog_firehose_lite.elf",
                "attributes": {"firehose_type": "lite"},
            }
        },
        {
            "download": {
                "file": "sailhyp.elf",
                "path": "./sail_nor",
                "path-flavor": "sail_nor",
                "attributes": {"storage_type": "spinor", "fastboot_complete": "SAIL_HYP"},
            }
        },
        {
            "partition": {
                "file": "rawprogram0.xml",
                "path": "./sail_nor",
                "path-flavor": "sail_nor",
                "attributes": {"storage_type": "spinor", "flavor": "sail_nor"},
            }
        },
    ],
}

_PARTITIONS_XML = """\
<?xml version="1.0" ?>
<configuration>
  <parser_instructions>WRITE_PROTECT_BOUNDARY_IN_KB=0</parser_instructions>
  <physical_partition>
    <partition label="efi" filename="efi.bin" size_in_kb="1.0" type="%s"/>
    <partition label="empty" size_in_kb="1.0" type="%s"/>
  </physical_partition>
</configuration>
""" % (GUID_A, GUID_B)


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


_SOC_KEYS = ("chip", "chipset", "additional-chipids")


def _split_meta():
    """_META split the way the repo splits it: SoC part / HLOS and flashing part."""
    firmware = [e for e in _META["common"] if "path-flavor" not in next(iter(e.values()))]
    flashing = [e for e in _META["common"] if e not in firmware]
    soc = {k: _META[k] for k in _SOC_KEYS}
    soc["common"] = firmware
    platform = {k: v for k, v in _META.items() if k not in _SOC_KEYS and k != "common"}
    platform["common"] = flashing
    return soc, platform


_UFS = """
  - id: ufs
    type: ufs
    size: 1073741824
    sector-size: 4096
    write-protect-boundary: 0
"""


def _expected(tmp_path, storage_dir):
    """The template pipeline's output next to ``storage_dir``'s partitions."""
    template = _write(tmp_path, "tpl/contents.xml.in", _TEMPLATE)
    expected = storage_dir / "expected.xml"
    gen_contents.generate_from_template(
        str(template), str(storage_dir / "partitions.xml"), str(expected), ""
    )
    return expected.read_bytes()


def test_platform_pipeline_matches_template_pipeline(tmp_path):
    """The real contract: identical contents.xml from metadata or template,
    although the template interleaves its placeholder entries differently.
    The board's SoC part and the platform's part merge back into _META."""
    soc, hlos = _split_meta()
    _write(tmp_path, "boards/demo.yaml", "storage:%s\ncontents: %r\n" % (_UFS, soc))
    _write(
        tmp_path,
        "flavors/demo-ufs.yaml",
        """
        storage:
          - type: ufs
            grow-last-partition: true
            partitions:
              - {name: efi, size: "1KB", type-guid: "%s", filename: efi.bin}
        """
        % GUID_A,
    )
    platform = _write(
        tmp_path,
        "demo.yaml",
        "board: boards/demo.yaml\ncontents: %r\nflavors: [flavors/demo-ufs.yaml]\n" % hlos,
    )
    out = tmp_path / "out"
    _write(tmp_path, "out/demo/ufs/partitions.xml", _PARTITIONS_XML)

    assert gen_contents.generate_from_file(str(platform), None, str(out), "") == 0
    # Contents land next to the default storage's partitions by default.
    built = (out / "demo" / "ufs" / "contents.xml").read_bytes()
    assert built == _expected(tmp_path, out / "demo" / "ufs")


def test_self_contained_board_pipeline_matches_template_pipeline(tmp_path):
    """An out-of-tree board: layout and complete contents in one file."""
    board = _write(
        tmp_path,
        "board.yaml",
        "storage:%s    grow-last-partition: true\n"
        "    partitions:\n"
        '      - {name: efi, size: "1KB", type-guid: "%s", filename: efi.bin}\n'
        "contents: %r\n" % (_UFS, GUID_A, _META),
    )
    out = tmp_path / "out"
    _write(tmp_path, "out/ufs/partitions.xml", _PARTITIONS_XML)

    assert gen_contents.generate_from_file(str(board), None, str(out), "") == 0
    built = (out / "ufs" / "contents.xml").read_bytes()
    assert built == _expected(tmp_path, out / "ufs")


def test_built_tree_matches_front_placeholder_template(tmp_path):
    """Tree-level equivalence for the canonical placeholder position."""
    meta = {
        "product-name": "Mini.LE.0.0",
        "chip": "MINI",
        "common": [{"device-programmer": {"file": "prog_firehose_ddr.elf"}}],
    }
    template = _write(
        tmp_path,
        "mini.xml.in",
        """\
        <?xml version="1.0" ?>
        <contents>
          <product_flavors cmm_pf_var="PRODUCT_FLAVORS">
            <pf>
              <name>default</name>
              <component>
                <name>common</name>
                <flavor>default</flavor>
              </component>
              <component>
                <name>apps</name>
                <flavor>default</flavor>
              </component>
            </pf>
          </product_flavors>
          <product_info>
            <product_name>Mini.LE.0.0</product_name>
            <chipid flavor="default" storage_type="emmc" flash_phase="1">MINI</chipid>
            <meta_type>FULL_STACK</meta_type>
            <build_type>K2L</build_type>
          </product_info>
          <builds_flat>
            <build>
              <name>apps</name>
              <role>apps</role>
              <chipset>MINI</chipset>
              <windows_root_path>.\\</windows_root_path>
              <linux_root_path>./</linux_root_path>
              <image_dir>apps_proc</image_dir>
            </build>
            <build>
              <name>common</name>
              <role>common</role>
              <chipset>MINI</chipset>
              <windows_root_path>.\\</windows_root_path>
              <linux_root_path>./</linux_root_path>
              <image_dir>common</image_dir>
              <download_file>
                <fastboot_complete>{partition_name}</fastboot_complete>
                <file_name>{image_name}</file_name>
                <file_path>.</file_path>
              </download_file>
              <partition_file>
                <storage_type>{storage_type}</storage_type>
                <file_name>{partition_file_name}</file_name>
                <file_path flavor="default">.</file_path>
              </partition_file>
              <partition_patch_file>
                <storage_type>{storage_type}</storage_type>
                <file_name>{partition_patch_file_name}</file_name>
                <file_path flavor="default">.</file_path>
              </partition_patch_file>
              <device_programmer>
                <file_name>prog_firehose_ddr.elf</file_name>
                <file_path>.</file_path>
              </device_programmer>
            </build>
          </builds_flat>
        </contents>
        """,
    )
    from_template = tmp_path / "from-template.xml"
    gen_contents.WriteContents(gen_contents.ParseXML(str(template)), str(from_template))

    from_meta = tmp_path / "from-meta.xml"
    gen_contents.WriteContents(build_contents_root(meta, "emmc"), str(from_meta))

    assert from_meta.read_bytes() == from_template.read_bytes()


def test_contents_paths_location():
    config = {
        "name": "demo",
        "storage": [{"id": "emmc"}, {"id": "spinor"}],
        "contents": {"product-name": "x", "chip": "X"},
    }
    # Default: the first storage, even with a second storage's chipid.
    config["contents"]["chipids"] = [{"flavor": "sail_nor", "storage": "spinor", "flash-phase": 2}]
    assert contents_paths(config) == ("emmc/contents.xml", "emmc/partitions.xml")

    config["contents"]["location"] = "spinor"
    assert contents_paths(config) == ("spinor/contents.xml", "spinor/partitions.xml")
    assert default_storage(config) == "spinor"

    config["contents"]["location"] = "/"
    assert contents_paths(config) == ("contents.xml", "emmc/partitions.xml")
    assert default_storage(config) == "emmc"

    config["contents"]["location"] = "nvme"
    with pytest.raises(ContentsError):
        contents_paths(config)

    assert contents_paths({"name": "demo", "storage": [{"id": "ufs"}], "contents": None}) is None
