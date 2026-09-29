# qcom-ptool

qcom-ptool contains various device partitioning utilities like ptool.py, gen_partitions.py and various sample partition configuration files needed for Qualcomm SoCs. Qualcomm Linux currently supports two reference Linux based OSes (Yocto with [meta-qcom](https://github.com/qualcomm-linux/meta-qcom) and Debian with [qcom-deb-images](https://github.com/qualcomm-linux/qcom-deb-images)) which uses this tool to generate partition table layouts. The partition GUIDs, names and size budgets are picked to support boot flows as follows:

- (preferred) "edk2/UEFI": PBL => XBL => edk2/UEFI => high-level OS (Linux)
- (legacy) "U-Boot/UEFI": PBL => XBL => ABL => U-Boot/UEFI => high-level OS (Linux)

# Installation

The project is packaged as a standard Python distribution and installs a
single `qcom-ptool` command with subcommands for each utility:

```sh
pip install .
```

Once installed, the tool is invoked as:

```sh
qcom-ptool gen_partition --board platforms/boards/<board>.yaml -C platforms/<board>
qcom-ptool gen_partition -i platforms/<soc>/<variant>/partitions.conf -o partitions.xml
qcom-ptool gen_contents  -p partitions.xml -t contents.xml.in -o contents.xml
qcom-ptool gen_udev_rules -o 55-qcom-raw-partitions-noblkid.rules
qcom-ptool ptool         -x partitions.xml
qcom-ptool msp           -r rawprogram0.xml -d /dev/sdX -p patch0.xml
```

By default, the generator scans all `platforms/*/*/partitions.conf` files.
Repeatable `-i` options can select specific layouts. It skips known filesystem
partition names and emits exact `PARTNAME` rules for the others. Unknown names
retain normal blkid probing. The rules use
`UDEV_DISABLE_PERSISTENT_STORAGE_BLKID_FLAG` on systemd v252 and newer.

Run `qcom-ptool <subcommand> -h` to see the options accepted by each
subcommand.

# Board definitions (YAML)

Partition layouts are being migrated from the legacy line-format
`partitions.conf` to structured YAML board files (see
[issue #124](https://github.com/qualcomm-linux/qcom-ptool/issues/124)).
A board file under `platforms/boards/<board>.yaml` describes one
flashable configuration: its storages and their partitions. Both
formats produce byte-identical output while they coexist.

```yaml
platform:
  name: example-board

storage:
  - id: ufs                      # output directory: platforms/<board>/<id>/
    type: ufs                    # emmc | nand | nvme | spinor | ufs
    size: 137438953472           # device size in bytes
    sector-size: 4096
    write-protect-boundary: 0
    grow-last-partition: true
    includes: [_common/example-soc-ufs.yaml]   # shared partition groups
    partitions:
      - {name: efi, lun: 0, size: "524288KB",
         type-guid: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B", filename: efi.bin}
      - {name: boot_a, lun: 1, size: "3584KB",
         type-guid: "DEA0BA2C-CBDD-4805-B4F9-F428251C3E98", filename: boot.img,
         active: true, priority: 2, tries-remaining: 6}
```

Partition fields mirror the legacy options: `name`, `lun`/`phys-part`,
`size`, `type-guid`, `filename`, `attributes`, `sparse`, plus the named
GPT attribute fields (`bootable`, `readonly`, `active`, `successful`,
`unbootable`, `priority`, `tries-remaining`, `unique-guid`). Sizes and
GUIDs must be quoted strings so YAML never misparses them; input is
validated against the JSON Schemas in `qcom_ptool/schema/`.

Partition order is load-bearing: it determines the GPT layout, and the
resolver never reorders or removes entries.

Three composition mechanisms keep board files small:

- `includes:` (storage level) concatenates shared partition fragments
  from `platforms/_common/` in listed order, before the storage's own
  `partitions:`. Fragments are include-only and cannot be built alone.
- `extends:` (board level) inherits a single base board. Entries are
  deep-merged by stable identity - storage `id`, partition
  `(lun, name)` - so an override can change one field and inherit the
  rest; unmatched entries are appended. Identity itself cannot be
  changed and nothing can be deleted.
- Variant overlays (`--hlos <name>`, `--boot-fw <name>`) load
  `platforms/variants/<axis>/<name>.yaml` and merge last, by the same
  rules.

Useful commands:

```sh
# print the fully resolved layout (all composition applied)
qcom-ptool show --board platforms/boards/<board>.yaml

# emit one partitions.xml per storage into platforms/<board>/<id>/
qcom-ptool gen_partition --board platforms/boards/<board>.yaml -C platforms/<board>
```

Adding a board needs no Makefile changes: `make` discovers
`platforms/boards/*.yaml` and reads each board's storage ids from the
file itself.

# Development

## Dependencies

At runtime the tool targets Python 3.8+ and depends on two third-party
libraries, `PyYAML` and `jsonschema`, used to load and validate the YAML
partition source. Both are declared in `pyproject.toml` and pulled in
automatically by `pip install .`.

For development, `make lint` invokes `ruff` and `mypy` and `make unit-test`
runs the `pytest` suite under `tests/unit/`. On Debian/Ubuntu, install
them as follows (ruff is not packaged in apt on all releases/architectures,
so we install it from snap):

```sh
sudo snap install ruff
sudo apt install mypy python3-pytest
```

## Makefile targets

| Target        | Description                                                |
|---------------|------------------------------------------------------------|
| `all`         | Generate partition XML and GPT binaries for all platforms  |
| `lint`        | Run ruff (linter) and mypy (type checker) on the package   |
| `unit-test`   | Run the pytest suite under `tests/unit/`                   |
| `integration` | Build all platforms and verify generated files are present |
| `check`       | Run `lint`, `unit-test`, and `integration`                 |
| `install`     | Install the package (`pip install .`)                      |
| `clean`       | Remove generated XML and binary files from platforms/      |

The Makefile invokes `qcom-ptool` from `PATH`. Install the package (or
`pip install -e .` from the repo root) before running `make all`.

### Quick start

```sh
# install the tool
pip install -e .

# install linters and test runner (Debian/Ubuntu)
sudo snap install ruff
sudo apt install mypy python3-pytest

# run linters and unit tests
make lint
make unit-test

# build all platforms and run tests
make check
```

## Code contributions

See [CONTRIBUTING.md file](CONTRIBUTING.md) for instructions on how to send
code contributions to this project. You can also [report an issue on
GitHub](../../issues).

# Maintainer(s)

See [CODEOWNERS](.github/CODEOWNERS).

# License

This project is licensed under the [BSD-3-clause
License](https://spdx.org/licenses/BSD-3-Clause.html). See
[LICENSE](LICENSE) for the full license text.
