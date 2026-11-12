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
qcom-ptool build         [-o out/] platforms/<platform>.yaml
qcom-ptool build         [-o out/] -b <board.yaml> [-f <flavor.yaml>]
qcom-ptool show          --platform platforms/<platform>.yaml
qcom-ptool gen_partition --platform platforms/<platform>.yaml -C out/
qcom-ptool gen_contents  [-o out/] platforms/<platform>.yaml
qcom-ptool gen_udev_rules -o 55-qcom-raw-partitions-noblkid.rules
qcom-ptool msp           -r rawprogram0.xml -d /dev/sdX -p patch0.xml
```

## Boards, flavors and platforms

Partition layouts are described by three kinds of YAML file under
`platforms/`:

- **boards** (`platforms/boards/`) describe hardware: the storage devices
  of a board, with their type and geometry, and the SoC part of the
  `contents:` metadata (chip identity and boot-chain firmware).
- **flavors** (`platforms/flavors/`) are board-agnostic partition
  layouts, keyed by storage type (e.g. a UFS layout with its LUNs). A
  flavor may span several storages flashed together, may `extends:`
  another flavor to add or override partitions, and composes shared
  partition sets from `platforms/flavors/_common/`.
- **platforms** (`platforms/<platform>.yaml`) list the flashable
  configurations of a board, one flavor each, and carry the HLOS and
  flashing part of `contents:`. `make all` builds every configuration
  into `platforms/<name>/<storage-id>/`, where the name defaults to the
  platform file's:

  ```yaml
  board: boards/qrb2210-unoq.yaml
  contents:
    product-name: QRB2210.LE.0.0
    location: emmc            # a storage id (default: the first one) or /
  flavors:
    - flavors/qrb2210-emmc.yaml
    - flavor: flavors/qrb2210-abl-emmc.yaml
      name: qrb2210-unoq-abl
  ```

Each flavor storage lands on the board storage of the same type. A
configuration's `contents.xml` metadata is the platform's `contents:`
(or a flavor entry's own) laid over the board's: keys override, `common`
entries are appended. `location` places `contents.xml` in that storage's
directory, or with `/` in the configuration directory.

A platform file is only a shortcut: `qcom-ptool build -b <board.yaml> -f
<flavor.yaml>` builds any combination without one, and `qcom-ptool show`
prints the fully resolved configurations. References between files are
relative to the referencing file.

### Self-contained boards

A board may also describe a whole configuration in one file, e.g. a board
kept out of tree: its storages carry their partitions (with the keys a
flavor storage takes) and its `contents:` is complete. It builds without
a flavor into `<outdir>/<storage-id>/`:

```yaml
storage:
  - id: emmc
    type: emmc
    size: 76841669632
    sector-size: 512
    grow-last-partition: true
    partitions:
      - {name: efi, size: "524288KB", type-guid: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B", filename: efi.bin}
      - {name: rootfs, size: "4194304KB", type-guid: "B921B045-1DF0-41C3-AF44-4C6F280D3FAE", filename: rootfs.img}
contents:
  product-name: QRB2210.LE.0.0
  chip: QRB2210
```

```sh
qcom-ptool build -o out/ -b my-board.yaml
```

The output of `qcom-ptool show` for a configuration (without its `name`)
is such a board.

## udev rules

By default, the generator scans all `platforms/*.yaml` platforms (and any
remaining `platforms/*/*/partitions.conf` files). Repeatable `-i` options
can select specific layouts, self-contained boards included. It skips known filesystem
partition names and emits exact `PARTNAME` rules for the others. Unknown names
retain normal blkid probing. Matched partitions are marked with
`QCOM_RAW_PARTITION=1` so later udev rules can reuse the generated
classification. The rules use
`UDEV_DISABLE_PERSISTENT_STORAGE_BLKID_FLAG` on systemd v252 and newer.

Run `qcom-ptool <subcommand> -h` to see the options accepted by each
subcommand.

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
| `all`         | Generate partition XML, GPT binaries and contents.xml      |
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
