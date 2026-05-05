# qcom-tool

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
qcom-ptool gen_partition -i platforms/<soc>/<variant>/partitions.conf -o partitions.xml
qcom-ptool gen_contents  -p partitions.xml -t contents.xml.in -o contents.xml
qcom-ptool ptool         -x partitions.xml
qcom-ptool msp           -r rawprogram0.xml -d /dev/sdX -p patch0.xml
```

Run `qcom-ptool <subcommand> -h` to see the options accepted by each
subcommand.

# Development

## Dependencies

At runtime, the scripts use only the Python standard library (Python 3.8+),
so no runtime dependencies need to be installed beyond the package itself.

For development, `make lint` invokes `ruff` and `mypy` directly from the
command line. On Debian/Ubuntu, install them as follows (ruff is not
packaged in apt on all releases/architectures, so we install it from
snap):

```sh
sudo snap install ruff
sudo apt install mypy
```

## Makefile targets

| Target        | Description                                                |
|---------------|------------------------------------------------------------|
| `all`         | Generate partition XML and GPT binaries for all platforms  |
| `lint`        | Run ruff (linter) and mypy (type checker) on the package   |
| `integration` | Build all platforms and verify generated files are present |
| `check`       | Run both `lint` and `integration`                          |
| `install`     | Install the package (`pip install .`)                      |
| `clean`       | Remove generated XML and binary files from platforms/      |

The Makefile invokes `qcom-ptool` from `PATH`. Install the package (or
`pip install -e .` from the repo root) before running `make all`.

### Quick start

```sh
# install the tool
pip install -e .

# install linters (Debian/Ubuntu)
sudo snap install ruff
sudo apt install mypy

# run linters
make lint

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
