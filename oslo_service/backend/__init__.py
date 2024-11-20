# Copyright (C) 2024 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import enum
import importlib
import logging
from typing import Any
from typing import TYPE_CHECKING

from . import exceptions

if TYPE_CHECKING:
    from .base import BaseBackend

LOG = logging.getLogger(__name__)


class BackendType(enum.Enum):
    EVENTLET = "eventlet"
    THREADING = "threading"


DEFAULT_BACKEND_TYPE = BackendType.EVENTLET

_cached_backend_type: BackendType | None = None  # backend type
_cached_backend: BaseBackend | None = None  # current backend
_cached_components: dict[str, Any] | None = None  # backend components


def _reset_backend() -> None:
    """used by test functions to reset the selected backend"""

    global _cached_backend, _cached_components, _cached_backend_type
    _cached_backend_type = _cached_backend = _cached_components = None


def init_backend(type_: BackendType) -> None:
    """establish which backend will be used when get_backend() is called"""

    global _cached_backend, _cached_components, _cached_backend_type

    if _cached_backend_type is not None:
        raise exceptions.BackendAlreadySelected(
            f"The {_cached_backend_type.value!r} backend is already set up"
        )

    backend_name = type_.value

    LOG.info(f"Loading backend: {backend_name}")
    try:
        module_name = f"oslo_service.backend.{backend_name}"
        module = importlib.import_module(module_name)
        backend_class = getattr(module, f"{backend_name.capitalize()}Backend")

        new_backend: BaseBackend
        _cached_backend = new_backend = backend_class()

    except ModuleNotFoundError:
        LOG.error(f"Backend module {module_name} not found.")
        raise ValueError(f"Unknown backend: {backend_name!r}")
    except AttributeError:
        LOG.error(f"Backend class not found in module {module_name}.")
        raise ImportError(f"Backend class not found in module {module_name}")

    _cached_backend_type = type_
    _cached_components = new_backend.get_service_components()
    LOG.info(f"Backend {type_.value!r} successfully loaded and cached.")


def get_backend() -> BaseBackend:
    """Load backend dynamically based on the default constant."""

    global _cached_backend
    if _cached_backend is None:
        init_backend(DEFAULT_BACKEND_TYPE)

    assert _cached_backend is not None  # nosec B101 : this is for typing

    return _cached_backend


def get_component(name: str) -> Any:
    """Retrieve a specific component from the backend."""
    global _cached_components

    if _cached_components is None:
        get_backend()

    assert _cached_components is not None  # nosec B101 : this is for typing

    if name not in _cached_components:
        raise KeyError(f"Component {name!r} not found in backend.")
    return _cached_components[name]
