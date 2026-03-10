#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
import sys


def EnsureDirectoryExists(filename):
    dir = os.path.dirname(filename)
    try:
        os.stat(dir)
    except OSError:
        os.makedirs(dir)


def PrintBigWarning(sz, log_func=print):
    log_func("\t                          _             ")
    log_func("\t                         (_)            ")
    log_func("\t__      ____ _ _ __ _ __  _ _ __   __ _ ")
    log_func("\t\\ \\ /\\ / / _` | '__| '_ \\| | '_ \\ / _` |")
    log_func("\t \\ V  V / (_| | |  | | | | | | | | (_| |")
    log_func("\t  \\_/\\_/ \\__,_|_|  |_| |_|_|_| |_|\\__, |")
    log_func("\t                                   __/ |")
    log_func("\t                                  |___/ \n")
    if len(sz) > 0:
        log_func(sz)


def PrintBigError(sz, log_func=print):
    log_func("\t _________________ ___________ ")
    log_func("\t|  ___| ___ \\ ___ \\  _  | ___ \\")
    log_func("\t| |__ | |_/ / |_/ / | | | |_/ /")
    log_func("\t|  __||    /|    /| | | |    / ")
    log_func("\t| |___| |\\ \\| |\\ \\\\ \\_/ / |\\ \\ ")
    log_func("\t\\____/\\_| \\_\\_| \\_|\\___/\\_| \\_|\n")
    if len(sz) > 0:
        log_func(sz)
        sys.exit(1)


def reflect(data, nBits):
    reflection = 0x00000000
    for bit in range(nBits):
        if data & 0x01:
            reflection |= (1 << ((nBits - 1) - bit))
        data = data >> 1
    return reflection


def CalcCRC32(array, Len):
    k        = 8            # length of unit (i.e. byte)
    MSB      = 0
    gx       = 0x04C11DB7  # IEEE 32bit polynomial
    regs     = 0xFFFFFFFF  # init to all ones
    regsMask = 0xFFFFFFFF  # ensure only 32 bit answer

    for i in range(int(Len)):
        DataByte = array[i]
        DataByte = reflect(DataByte, 8)

        for j in range(k):
            MSB  = DataByte >> (k - 1)  ## get MSB
            MSB &= 1                    ## ensure just 1 bit

            regsMSB = (regs >> 31) & 1

            regs = regs << 1            ## shift regs for CRC-CCITT

            if regsMSB ^ MSB:           ## MSB is a 1
                regs = regs ^ gx        ## XOR with generator poly

            regs = regs & regsMask      ## Mask off excess upper bits

            DataByte <<= 1              ## get to next bit

    regs          = regs & regsMask
    ReflectedRegs = reflect(regs, 32) ^ 0xFFFFFFFF

    return ReflectedRegs
