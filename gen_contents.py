#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import getopt
import os
import sys

from xml.etree import ElementTree as ET


def usage():
    print(("\n\tUsage: %s -t <template> -p <partitions_xml_path> -o <output> \n\tVersion 0.1\n" % (sys.argv[0])))
    sys.exit(1)


def ParseXML(XMLFile):
    try:
        tree = ET.parse(XMLFile)
        root = tree.getroot()
        return root
    except FileNotFoundError:
        print(f"Error: File '{XMLFile}' not found")
        return None
    except ET.ParseError as e:
        print(f"Error: Failed parsing '{XMLFile}': {e}")
        return None


def UpdateMetaData(TemplateRoot, PartitionRoot):
    ChipIdList = TemplateRoot.findall('product_info/chipid')
    DefaultStorageType = None
    for ChipId in ChipIdList:
        Flavor = ChipId.get('flavor')
        StorageType = ChipId.get('storage_type')
        print(f"Chipid Flavor: {Flavor} Storage Type: {StorageType}")
        if Flavor == "default":
            DefaultStorageType = ChipId.get('storage_type')

    PhyPartition = PartitionRoot.findall('physical_partition')
    Partitions = []
    for partition in PartitionRoot.findall('physical_partition/partition'):
        label = partition.get('label')
        filename = partition.get('filename')
        if label and filename:
            Partitions.append({'label': label, 'filename': filename})
    print(f"Partitions: {Partitions}")

    def _add_file_elements(parent_element, pathname, file_path_flavor=None):
        """Helper function to add file_name and file_path sub-elements."""
        file_name_text = os.path.basename(pathname)
        file_path_text = os.path.dirname(pathname)
        if not file_path_text:  # no directory, use explicit . as current dir
            file_path_text = "."

        new_file_name = ET.SubElement(parent_element, "file_name")
        new_file_name.text = file_name_text
        new_file_path = ET.SubElement(parent_element, "file_path")
        if file_path_flavor:
            new_file_path.set("flavor", file_path_flavor)
        new_file_path.text = file_path_text

    builds = TemplateRoot.findall('builds_flat/build')
    for build in builds:
        Name = build.find('name')
        print(f"Build Name: {Name.text}")
        if Name.text != "common":
            continue
        DownloadFile = build.find('download_file')
        if DownloadFile is not None:
            build.remove(DownloadFile)
            # Partition entires
            for Partition in Partitions:
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("fastboot_complete", Partition['label'])
                _add_file_elements(new_download_file, Partition['filename'])
            # GPT Main & GPT Backup entries
            for PhysicalPartitionNumber in range(0, len(PhyPartition)):
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("storage_type", DefaultStorageType)
                _add_file_elements(new_download_file, 'gpt_main%d.bin' % (PhysicalPartitionNumber))
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("storage_type", DefaultStorageType)
                _add_file_elements(new_download_file, 'gpt_backup%d.bin' % (PhysicalPartitionNumber))

        PartitionFile = build.find('partition_file')
        if PartitionFile is not None:
            build.remove(PartitionFile)
            # Rawprogram entries
            for PhysicalPartitionNumber in range(0, len(PhyPartition)):
                new_partition_file = ET.SubElement(build, "partition_file")
                new_partition_file.set("storage_type", DefaultStorageType)
                _add_file_elements(new_partition_file, 'rawprogram%d.xml' % (PhysicalPartitionNumber), "default")

        PartitionPatchFile = build.find('partition_patch_file')
        if PartitionPatchFile is not None:
            build.remove(PartitionPatchFile)
            # Patch entries
            for PhysicalPartitionNumber in range(0, len(PhyPartition)):
                new_partition_patch_file = ET.SubElement(build, "partition_patch_file")
                new_partition_patch_file.set("storage_type", DefaultStorageType)
                _add_file_elements(new_partition_patch_file, 'patch%d.xml' % (PhysicalPartitionNumber), "default")

###############################################################################
# main
###############################################################################


if len(sys.argv) < 3:
    usage()

try:
    if sys.argv[1] == "-h" or sys.argv[1] == "--help":
        usage()
    try:
        opts, rem = getopt.getopt(sys.argv[1:], "t:p:o:")
        for (opt, arg) in opts:
            if opt in ["-t"]:
                template = arg
            elif opt in ["-p"]:
                partition_xml = arg
            elif opt in ["-o"]:
                output_xml = arg
            else:
                usage()
    except Exception as argerr:
        print(str(argerr))
        usage()

    print("Selected Template:  " + template)
    xml_root = ParseXML(template)

    print("Selected Partition XML:  " + partition_xml)
    partition_root = ParseXML(partition_xml)

    UpdateMetaData(xml_root, partition_root)

    OutputTree = ET.ElementTree(xml_root)
    ET.indent(OutputTree, space="\t", level=0)
    OutputTree.write(output_xml, encoding="utf-8", xml_declaration=True)
except Exception as e:
    print(("Error: ", e))
    sys.exit(1)

sys.exit(0)
