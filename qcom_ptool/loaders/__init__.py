# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Source-format loaders for partition specs.

Each loader exposes ``load(path, image_map=None) -> LoadedSpec`` so the rest
of the package never has to care which on-disk format produced the
:mod:`qcom_ptool.spec` representation it operates on. Adding a new format
(e.g. YAML) means dropping a new module here and registering its suffix in
the dispatcher below — no other module needs to change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from qcom_ptool.spec import LoadedSpec


class UnsupportedFormatError(ValueError):
    """Raised when no loader is registered for a given path's extension."""


def load(path: str, image_map: Mapping[str, str] | None = None) -> LoadedSpec:
    """Dispatch to the appropriate loader based on file extension.

    ``image_map`` overrides the ``--filename`` (or equivalent) for partitions
    whose name appears as a key. It's applied uniformly by every loader so
    the CLI ``-m`` flag works the same regardless of source format.
    """
    suffix = os.path.splitext(path)[1].lower()
    if suffix in ("", ".conf"):
        # Late import: keeps this dispatcher dependency-free until a format
        # is actually requested, which matters once optional formats (YAML)
        # land with their own third-party imports.
        from qcom_ptool.loaders import conf

        return conf.load(path, image_map=image_map)
    if suffix in (".yaml", ".yml"):
        # Late import so the .conf path never pays for PyYAML / jsonschema.
        from qcom_ptool.loaders import yaml as yaml_loader

        return yaml_loader.load(path, image_map=image_map)
    raise UnsupportedFormatError(f"No loader registered for suffix {suffix!r}")
