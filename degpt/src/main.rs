// SPDX-License-Identifier: MIT
// Copyright (c) 2024 Linaro Ltd.

use std::env;
use std::error::Error;
use std::fs;
use std::fs::File;
use std::io::Write;

use degpt::mygpt::*;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);

    let mut xml;
    if let Some(name) = args.next() {
        xml = File::create(name)?;
    } else {
        return Err(format!(
            "usage: {} partition.xml gpt_both*.bin",
            env::args().next().unwrap()
        )
        .into());
    }

    xml.write_all(
        concat!(
            "<?xml version=\"1.0\"?>\n",
            "<configuration>\n",
            "    <parser_instructions>\n",
            "        WRITE_PROTECT_BOUNDARY_IN_KB=0\n",
            "        SECTOR_SIZE_IN_BYTES = 4096\n",
            "        GROW_LAST_PARTITION_TO_FILL_DISK=true\n",
            "    </parser_instructions>\n",
            "\n",
        )
        .as_bytes(),
    )?;

    for gpt in args {
        let bytes = fs::read(&gpt)?;
        let hdr = Header::try_from(&bytes[0x1000..0x2000])?;

        println!("{gpt}");
        println!("{hdr:#}");

        xml.write_all("    <physical_partition>\n".as_bytes())?;
        for i in 0..hdr.num_parts {
            let offset = 0x2000 + i as usize * 0x80;
            let part = Partition::try_from(&bytes[offset..offset + 0x80])?;
            if part.part_guid.is_nil() {
                continue;
            }
            println!("{part:#}");
            let size = (part.last_lba + 1 - part.first_lba) * 4096 / 1024;
            let readonly: bool = part.flags & (1 << 60) != 0;
            xml.write_all(
                format!(
                    "        <partition label=\"{}\" size_in_kb=\"{}\" type=\"{}\" bootable=\"false\" readonly=\"{}\" filename=\"\" />\n",
                    part.name,
                    size,
                    part.part_type_guid.guid.to_string().to_uppercase(),
                    readonly,
                )
                .as_bytes(),
            )?;
        }

        xml.write_all("    </physical_partition>\n\n".as_bytes())?;
    }

    xml.write_all("</configuration>\n".as_bytes())?;

    Ok(())
}
