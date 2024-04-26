// SPDX-License-Identifier: MIT
// Copyright (c) 2017 Quyzi
// Copyright (c) 2024 Linaro Ltd.
use std::error::Error;
use std::fmt;
use std::io::Cursor;

use gpt::header::parse_uuid;
use gpt::partition_types::OperatingSystem;

/// The type
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Type {
    /// Type-GUID for a GPT partition.
    pub guid: uuid::Uuid,
    /// well-known OS label for this type-GUID.
    pub os: OperatingSystem,
}

/// A partition entry in a GPT partition table.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Partition {
    /// GUID of the partition type.
    pub part_type_guid: Type,
    /// UUID of the partition.
    pub part_guid: uuid::Uuid,
    /// First LBA of the partition.
    pub first_lba: u64,
    /// Last LBA of the partition.
    pub last_lba: u64,
    /// Partition flags.
    pub flags: u64,
    /// Partition name.
    pub name: String,
}

impl fmt::Display for Partition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Partition:\t\t{}\nPartition GUID:\t\t{}\nPartition Type:\t\t{}\n\
             Span:\t\t\t{} - {}\nFlags:\t\t\t{}",
            self.name,
            self.part_guid,
            self.part_type_guid.guid,
            self.first_lba,
            self.last_lba,
            self.flags,
        )
    }
}

fn get_utf16le(buf: &[u8]) -> Vec<u16> {
    let mut r = vec![];
    for c in buf.chunks(2) {
        let u = c[0] as u16 | ((c[1] as u16) << 8);
        if u != 0 {
            r.push(u);
        }
    }
    r
}

impl TryFrom<&[u8]> for Partition {
    type Error = Box<dyn Error>;

    fn try_from(buf: &[u8]) -> Result<Self, Self::Error> {
        Ok(Partition {
            part_type_guid: Type {
                guid: parse_uuid(&mut Cursor::new(&buf[0..]))?,
                os: OperatingSystem::None,
            },
            part_guid: parse_uuid(&mut Cursor::new(&buf[16..]))?,
            first_lba: u64::from_le_bytes(buf[32..40].try_into()?),
            last_lba: u64::from_le_bytes(buf[40..48].try_into()?),
            flags: u64::from_le_bytes(buf[48..56].try_into()?),
            name: String::from_utf16(&get_utf16le(&buf[56..128]))?,
        })
    }
}
