#!/usr/bin/env python3
# Copyright (c) 2025 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import getopt
import shutil
import sys

def usage():
   print("\n\tUsage: %s -i <input> -o <output>\n\tVersion 0.1\n" %(sys.argv[0]))
   sys.exit(1)

def generate_contents_xml (input_file, output_xml):
    # Copy the input file to the output file for now.
    try:
      shutil.copyfile(input_file, output_xml)
      print(f"File '{input_file}' has been copied to '{output_xml}'.")
    except FileNotFoundError:
      print(f"Error: The file '{input_file}' does not exist.")

###############################################################################
# main
if len(sys.argv) < 2:
   usage()

try:
    if sys.argv[1] == "-h" or sys.argv[1] == "--help":
      usage()
    try:
      opts, rem = getopt.getopt(sys.argv[1:], "i:o:")
      for (opt, arg) in opts:
        if opt in ["-i"]:
          input_file=arg
        elif opt in ["-o"]:
          output_xml=arg
        else:
          usage()
    except Exception as argerr:
      print (str(argerr))
      usage()
    f = open(input_file)
    line = f.readline()
except Exception as e:
    print("Error: ", e)
    sys.exit(1)

generate_contents_xml(input_file, output_xml)

sys.exit(0)
