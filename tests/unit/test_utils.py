# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Unit tests for qcom_ptool.utils."""

import binascii
import pytest

from qcom_ptool.utils import CalcCRC32, EnsureDirectoryExists, reflect


class TestReflect:
    def test_reflect_single_bit_8(self):
        assert reflect(0b00000001, 8) == 0b10000000
        assert reflect(0b10000000, 8) == 0b00000001

    def test_reflect_is_involution(self):
        # Reflecting twice must return the original value.
        for value in (0x00, 0x01, 0x5A, 0xA5, 0xFF, 0x12345678):
            nbits = 8 if value <= 0xFF else 32
            assert reflect(reflect(value, nbits), nbits) == value

    def test_reflect_32(self):
        assert reflect(0x00000001, 32) == 0x80000000
        assert reflect(0x12345678, 32) == 0x1E6A2C48


class TestCalcCRC32:
    """CalcCRC32 implements standard CRC-32 (IEEE 802.3, reflected),
    so binascii.crc32 is used as an independent reference."""

    def test_known_check_value(self):
        # "123456789" -> 0xCBF43926 is the canonical CRC-32 check value.
        data = b"123456789"
        assert CalcCRC32(data, len(data)) == 0xCBF43926

    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"\x00",
            b"\xff" * 16,
            bytes(range(256)),
            b"qcom-ptool",
        ],
        ids=["empty", "single-nul", "all-ones", "all-bytes", "ascii"],
    )
    def test_matches_binascii_crc32(self, data):
        assert CalcCRC32(data, len(data)) == binascii.crc32(data) & 0xFFFFFFFF

    def test_partial_length(self):
        # Only the first Len bytes participate in the checksum.
        data = b"123456789XXXX"
        assert CalcCRC32(data, 9) == 0xCBF43926

    def test_accepts_list_input(self):
        # GPT code paths pass mutable sequences, not only bytes.
        data = list(b"123456789")
        assert CalcCRC32(data, len(data)) == 0xCBF43926


class TestEnsureDirectoryExists:
    def test_creates_missing_parents(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "file.bin"
        EnsureDirectoryExists(str(target))
        assert (tmp_path / "a" / "b" / "c").is_dir()
        assert not target.exists()  # only the directory is created

    def test_existing_directory_is_noop(self, tmp_path):
        target = tmp_path / "file.bin"
        EnsureDirectoryExists(str(target))
        EnsureDirectoryExists(str(target))  # second call must not raise
        assert tmp_path.is_dir()
