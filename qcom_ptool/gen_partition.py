# Copyright (c) 2019, The Linux Foundation. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
#     * Neither the name of The Linux Foundation nor the names of its
#       contributors may be used to endorse or promote products derived
#       from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
# IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom

from qcom_ptool.spec import DiskParams, PartitionsByLun


def generate_multi_lun_xml(
    disk_params: DiskParams, partitions: PartitionsByLun, output_xml: str
) -> None:
    root = ET.Element("configuration")
    parser_instruction_text = ""

    for key, value in disk_params.items():
        if key != "size" and key != "type":
            parser_instruction_text += "\n\t" + str(key) + "=" + str(value) + "\n\t"

    ET.SubElement(root, "parser_instructions").text = parser_instruction_text

    for _phys_part, entries in sorted(partitions.items(), key=lambda item: int(item[0])):
        found = False
        for part_entry in entries:

            # if there is no partition in the LUN, skip the physical_partition in XML
            # only create the physical_partition once we have at least one partition
            if not found:
                phy_part = ET.SubElement(root, "physical_partition")
            ET.SubElement(phy_part, "partition", attrib=part_entry)
            found = True

    xmlstr = minidom.parseString(ET.tostring(root)).toprettyxml()
    with open(output_xml, "w") as f:
        f.write(xmlstr)


def generate_partition_xml(
    disk_params: DiskParams, partitions: PartitionsByLun, output_xml: str
) -> None:
    if disk_params["type"] not in ("emmc", "nvme", "spinor", "ufs"):
        raise ValueError("storage type %r is not supported" % disk_params["type"])
    generate_multi_lun_xml(disk_params, partitions, output_xml)
