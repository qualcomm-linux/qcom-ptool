#!/usr/bin/env python3

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

import sys
import re
import getopt
import xml.etree.ElementTree as ET
from xml.dom import minidom
from collections import OrderedDict

def usage():
   print("\n\tUsage: %s -i <input> -o <output> -m [partition_name1=image_filename1,partition_name2=image_filename2,...]\n\tVersion 1.0\n" %(sys.argv[0]))
   sys.exit(1)

##################################################################
# defaults to be used
disk_params_defaults = OrderedDict({
   "type": "",
   "size": "",
   "SECTOR_SIZE_IN_BYTES": "512",
   "WRITE_PROTECT_BOUNDARY_IN_KB": "65536",
   "GROW_LAST_PARTITION_TO_FILL_DISK": "false",
   "ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY": "true",
   "PERFORMANCE_BOUNDARY_IN_KB": "4"
})

partition_entry_defaults = {
   "label": "",
   "size_in_kb": "",
   "type": "00000000-0000-0000-0000-000000000000",
   "bootable": "false",
   "readonly": "true",
   "filename": "",
   "sparse" : "false",
}

##################################################################
# store entries read from input file
disk_entry = None
partition_entries = []
# store partition image map passed from command line
partition_image_map = {}
input_file = None
output_xml = None

def disk_options(argv):
   disk_params = disk_params_defaults.copy()
   for (opt, arg) in argv:
      if opt in ['--type']:
         disk_params["type"] = arg
      elif opt in ['--size']:
         disk_params["size"] = arg
      elif opt in ['--sector-size-in-bytes']:
         disk_params["SECTOR_SIZE_IN_BYTES"] = arg
      elif opt in ['--write-protect-boundary']:
         disk_params["WRITE_PROTECT_BOUNDARY_IN_KB"] = arg
      elif opt in ['--grow-last-partition']:
         disk_params["GROW_LAST_PARTITION_TO_FILL_DISK"] = "true"
      elif opt in ['--align-partitions']:
         disk_params["ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY"] = "true"
         disk_params["PERFORMANCE_BOUNDARY_IN_KB"] = (int(arg)/1024)
   return disk_params

def partition_size_in_kb(size):
    if not re.search('[a-zA-Z]+', size):
        return int(size)/1024
    if re.search('([0-9])*(?=([Kk]([Bb])*))', size):
        return int(re.search('([0-9])*(?=([Kk]([Bb])*))', size).group(0))
    if re.search('([0-9])*(?=([Mm]([Bb])*))', size):
        return (int(re.search('([0-9])*(?=([Mm]([Bb])*))', size).group(0)) * 1024)
    if re.search('([0-9])*(?=([Gg]([Bb])*))', size):
        return (int(re.search('([0-9])*(?=([Gg]([Bb])*))', size).group(0)) * 1024 * 1024)

def partition_options(argv):
   partition_entry = partition_entry_defaults.copy()
   phys_part = 0
   for (opt, arg) in argv:
      if opt in ['--lun', '--phys-part']:
         phys_part = arg
      elif opt in ['--name']:
         partition_entry["label"] = arg
      elif opt in ['--size']:
         kbytes = partition_size_in_kb(arg)
         partition_entry["size_in_kb"] = str(kbytes)
      elif opt in ['--type-guid']:
         partition_entry["type"] = arg
      elif opt in ['--attributes']:
         attribute_bits = int(arg,16)
         if attribute_bits & (1<<2):
            partition_entry["bootable"] = "true"
         else:
            partition_entry["bootable"] = "false"
         if attribute_bits & (1<<60):
            partition_entry["readonly"] = "true"
         else:
            partition_entry["readonly"] = "false"
      elif opt in ['--filename']:
         partition_entry["filename"] = arg
      elif opt in ['--sparse']:
         partition_entry["sparse"] = arg
      if partition_entry["label"] in partition_image_map.keys():
         partition_entry["filename"] = partition_image_map[partition_entry["label"]]
   return phys_part, partition_entry

def parse_partition_entries(partition_entries):
   partitions_params = {}

   for partition_entry in partition_entries:
      opts_list = list(partition_entry.split(' '))
      if opts_list[0] == "--partition":
         try:
            options, remainders = getopt.gnu_getopt(opts_list[1:], '',
                                 ['lun=', 'phys-part=', 'name=', 'size=','type-guid=',
                                  'filename=', 'attributes=', 'sparse='])
            phys_part, partition = partition_options(options)
            partitions_params.setdefault(phys_part, []).append(partition)
         except Exception as e:
            print (str(e))
            usage()

   return partitions_params

def parse_disk_entry(disk_entry):
   opts_list = list(disk_entry.split(' '))
   if opts_list[0] == "--disk":
      try:
         options, remainders = getopt.gnu_getopt(opts_list[1:], '',
                                 ['type=', 'size=','sector-size-in-bytes=', 'write-protect-boundary=',
                                  'grow-last-partition', 'align-partitions='])
         return disk_options(options)
      except Exception as e:
         print (str(e))
         usage()

def generate_multi_lun_xml (disk_params, partitions, output_xml):
   root = ET.Element("configuration")
   parser_instruction_text = ""

   for key, value in disk_params.items():
      if not key == 'size' and not key == 'type':
         parser_instruction_text += '\n\t' + str(key) + '=' + str(value) + '\n\t'

   parser_inst = ET.SubElement(root,"parser_instructions").text = (
      parser_instruction_text
   )

   for phys_part, entries in sorted(partitions.items(), key=lambda item: int(item[0])):
      found = False
      for part_entry in entries:

         # if there is no partition in the LUN, skip the physical_partition in XML
         # only create the physical_partition once we have at least one partition
         if not found:
            phy_part = ET.SubElement(root, "physical_partition")
         part = ET.SubElement(phy_part, "partition", attrib=part_entry)
         found = True

   xmlstr = minidom.parseString(ET.tostring(root)).toprettyxml()
   with open(output_xml, "w") as f:
      f.write(xmlstr)

def generate_partition_xml (disk_params, partitions, output_xml):
   print("Generating %s XML %s" %(disk_params["type"].upper(), output_xml))
   
   if disk_params["type"] in ("emmc", "nvme", "spinor", "ufs"):
      generate_multi_lun_xml(disk_params, partitions, output_xml)
   else:
      print("%s XML generation is curently not supported." %(disk_params["type"].upper()))

###############################################################################
# main
disk_entry_err_msg = "contains more than one --disk entries"

if len(sys.argv) < 3:
   usage()

try:
   if sys.argv[1] == "-h" or sys.argv[1] == "--help":
      usage()
   try:
      opts, rem = getopt.getopt(sys.argv[1:], "i:o:m:")
      for (opt, arg) in opts:
        if opt in ["-i"]:
          input_file=arg
        elif opt in ["-o"]:
          output_xml=arg
        elif opt in ["-m"]:
          for mapping in arg.split(','):
            tags=mapping.split("=")
            if len(tags) > 1:
              partition_image_map[tags[0]]=tags[1]
        else:
          usage()

   except Exception as argerr:
      print (str(argerr))
      usage()
   f = open(input_file)
   line = f.readline()
   while line:
      if not re.search(r'^\s*#', line) and not re.search(r'^\s*$', line):
         line = line.strip()
         if re.search("^--disk", line):
            if disk_entry == None:
               disk_entry = line
            else:
               print("%s %s" %(sys.argv[1], disk_entry_err_msg))
               print("%s\n%s" %(disk_entry, line))
               sys.exit(1)
         elif re.search("^--partition", line):
            partition_entries.append(line)
         else:
            print("Ignoring %s" %(line))
      line = f.readline()
   f.close()
except Exception as e:
   print("Error: ", e)
   sys.exit(1)

disk_params = parse_disk_entry(disk_entry)
partitions = parse_partition_entries(partition_entries)
generate_partition_xml(disk_params, partitions, output_xml)

sys.exit(0)
