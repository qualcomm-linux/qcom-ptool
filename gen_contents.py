#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import getopt
import sys

from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement

def usage():
    print(("\n\tUsage: %s -t <template> -p <partitions_xml_path> -o <output> \n\tVersion 0.1\n" %(sys.argv[0])))
    sys.exit(1)

def ParseXML(XMLFile):
    try:
        tree = ET.parse(XMLFile)
        root = tree.getroot()
        return root
    except FileNotFoundError:
        print(f"Error: The file '{XMLFile}' not found")
        return None
    except ET.ParseError as e:
        print(f"Error parsing '{XMLFile}': {e}")
        return None

def UpdateMetaData(TemplateRoot, PartitionRoot):
    ChipIdList = TemplateRoot.findall('product_info/chipid')
    DefaultStorageType = None
    SailnorStorageType = None
    for ChipId in ChipIdList:
        Flavor = ChipId.get('flavor')
        StorageType = ChipId.get('storage_type')
        print(f"Chipid Flavor: {Flavor} Storage Type: {StorageType}")
        if Flavor == "default":
            DefaultStorageType = ChipId.get('storage_type')
        if Flavor == "sail_nor":
            SailnorStorageType = ChipId.get('storage_type')

    PhyPartition = PartitionRoot.findall('physical_partition')
    PartitionsSet = set()
    Partitions = PartitionRoot.findall('physical_partition/partition')
    for partition in Partitions:
        label = partition.get('label')
        filename = partition.get('filename')
        if label and filename:
            PartitionsSet.add((label, filename))
    print(f"PartitionsSet: {PartitionsSet}")

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
            for Partition in PartitionsSet:
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("fastboot_complete", Partition[0])
                new_file_name = ET.SubElement(new_download_file, "file_name")
                new_file_name.text = Partition[1]
                new_file_path = ET.SubElement(new_download_file, "file_path")
                new_file_path.text = "."
            # GPT Main & GPT Backup entires
            for PhysicalPartitionNumber in range(0,len(PhyPartition)):
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("storage_type", DefaultStorageType)
                new_file_name = ET.SubElement(new_download_file, "file_name")
                new_file_name.text = 'gpt_main%d.xml' % (PhysicalPartitionNumber)
                new_file_path = ET.SubElement(new_download_file, "file_path")
                new_file_path.text = "."
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("storage_type", DefaultStorageType)
                new_file_name = ET.SubElement(new_download_file, "file_name")
                new_file_name.text = 'gpt_backup%d.xml' % (PhysicalPartitionNumber)
                new_file_path = ET.SubElement(new_download_file, "file_path")
                new_file_path.text = "."

        PartitionFile = build.find('partition_file')
        if PartitionFile is not None:
            build.remove(PartitionFile)
            # Rawprogram entires
            for PhysicalPartitionNumber in range(0,len(PhyPartition)):
                new_partition_file = ET.SubElement(build, "partition_file")
                new_partition_file.set("storage_type", DefaultStorageType)
                new_file_name = ET.SubElement(new_partition_file, "file_name")
                new_file_name.text = 'rawprogram%d.xml' % (PhysicalPartitionNumber)
                new_file_path = ET.SubElement(new_partition_file, "file_path")
                new_file_path.set("flavor", "default")
                new_file_path.text = "."

        PartitionPatchFile = build.find('partition_patch_file')
        if PartitionPatchFile is not None:
            build.remove(PartitionPatchFile)
            # Patch entires
            for PhysicalPartitionNumber in range(0,len(PhyPartition)):
                new_partition_patch_file = ET.SubElement(build, "partition_patch_file")
                new_partition_patch_file.set("storage_type", DefaultStorageType)
                new_file_name = ET.SubElement(new_partition_patch_file, "file_name")
                new_file_name.text = 'patch%d.xml' % (PhysicalPartitionNumber)
                new_file_path = ET.SubElement(new_partition_patch_file, "file_path")
                new_file_path.set("flavor", "default")
                new_file_path.text = "."

        # sail_nor is assumed to be a single parition.
        if SailnorStorageType is not None:
            new_download_file = ET.SubElement(build, "download_file")
            new_download_file.set("storage_type", SailnorStorageType)
            new_download_file.set("fastboot_complete", "SAIL_HYP")
            new_file_name = ET.SubElement(new_download_file, "file_name")
            new_file_name.text = "sailfreertos.elf"
            new_file_path = ET.SubElement(new_download_file, "file_path")
            new_file_path.set("flavor", "sail_nor")
            new_file_path.text = "./sail_nor"
            new_download_file = ET.SubElement(build, "download_file")
            new_download_file.set("storage_type", SailnorStorageType)
            new_download_file.set("flavor", "sail_nor")
            new_file_name = ET.SubElement(new_download_file, "file_name")
            new_file_name.text = "gpt_main0.bin"
            new_file_path = ET.SubElement(new_download_file, "file_path")
            new_file_path.set("flavor", "sail_nor")
            new_file_path.text = "./sail_nor"
            new_download_file = ET.SubElement(build, "download_file")
            new_download_file.set("storage_type", SailnorStorageType)
            new_download_file.set("flavor", "sail_nor")
            new_file_name = ET.SubElement(new_download_file, "file_name")
            new_file_name.text = "gpt_backup0.bin"
            new_file_path = ET.SubElement(new_download_file, "file_path")
            new_file_path.set("flavor", "sail_nor")
            new_file_path.text = "./sail_nor"
            new_partition_file = ET.SubElement(build, "partition_file")
            new_partition_file.set("storage_type", SailnorStorageType)
            new_partition_file.set("flavor", "sail_nor")
            new_file_name = ET.SubElement(new_partition_file, "file_name")
            new_file_name.text = 'rawprogram0.xml'
            new_file_path = ET.SubElement(new_partition_file, "file_path")
            new_file_path.set("flavor", "sail_nor")
            new_file_path.text = "./sail_nor"
            new_partition_patch_file = ET.SubElement(build, "partition_patch_file")
            new_partition_patch_file.set("storage_type", SailnorStorageType)
            new_partition_patch_file.set("flavor", "sail_nor")
            new_file_name = ET.SubElement(new_partition_patch_file, "file_name")
            new_file_name.text = 'patch0.xml'
            new_file_path = ET.SubElement(new_partition_patch_file, "file_path")
            new_file_path.set("flavor", "sail_nor")
            new_file_path.text = "./sail_nor"

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
                template=arg
            elif opt in ["-p"]:
                partition_xml=arg
            elif opt in ["-o"]:
                output_xml=arg
            else:
                usage()
    except Exception as argerr:
        print(str(argerr))
        usage()

    print(f"Selected Template:  " + template)
    xml_root = ParseXML(template)

    print(f"Selected Parition XML:  " + partition_xml)
    partition_root = ParseXML(partition_xml)

    UpdateMetaData(xml_root, partition_root)

    OutputTree = ET.ElementTree(xml_root)
    ET.indent(OutputTree, space="\t", level=0)
    OutputTree.write(output_xml, encoding="utf-8", xml_declaration=True)
except Exception as e:
    print(("Error: ", e))
    sys.exit(1)

sys.exit(0)
