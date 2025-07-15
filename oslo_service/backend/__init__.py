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
from typing import Callable
from typing import TYPE_CHECKING

from . import exceptions

if TYPE_CHECKING:
    from .base import BaseBackend

LOG = logging.getLogger(__name__)


class BackendType(enum.Enum):
    EVENTLET = "eventlet"
    THREADING = "threading"


DEFAULT_BACKEND_TYPE = BackendType.EVENTLET

_cached_backend_type: BackendType | None = None
_cached_backend: BaseBackend | None = None
_cached_components: dict[str, Any] | None = None

# optional override hook
_backend_hook: Callable[[], BackendType] | None = None

__all__ = [
    "get_component",
    "init_backend",
    "BackendType",
    "register_backend_default_hook",
    "get_backend_type",
    "get_backend"
]


def register_backend_default_hook(hook: Callable[[], BackendType]) -> None:
    """Register a hook that decides the default backend type.

    This is used when no init_backend() call has been made, and
    get_backend() is called. The hook will be invoked to determine
    the backend type to use *only if* no backend has been selected yet.

    Example:

        def my_hook():
            return BackendType.THREADING

        register_backend_default_hook(my_hook)

    :param hook: A callable that returns a BackendType
    """
    global _backend_hook
    _backend_hook = hook


def _reset_backend() -> None:
    """Used by test functions to reset the selected backend."""

    global _cached_backend, _cached_components
    global _cached_backend_type, _backend_hook

    _cached_backend_type = _cached_backend = _cached_components = None
    _backend_hook = None


def init_backend(type_: BackendType) -> None:
    """Establish which backend will be used when get_backend() is called."""

    global _cached_backend, _cached_components, _cached_backend_type

    if _cached_backend_type is not None:
        if _cached_backend_type != type_:
            raise exceptions.BackendAlreadySelected(
                f"Backend already set to {_cached_backend_type.value!r},"
                f" cannot reinitialize with {type_.value!r}"
            )

        return  # already initialized with same value; no-op

    backend_name = type_.value
    LOG.info(f"Loading backend: {backend_name}")

    try:
        module_name = f"oslo_service.backend._{backend_name}"
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
    """Load backend dynamically based on the default constant or hook."""

    global _cached_backend
    if _cached_backend is None:
        type_ = DEFAULT_BACKEND_TYPE

        if _backend_hook is not None:
            try:
                type_ = _backend_hook()
                LOG.info(f"Backend hook selected: {type_.value}")
            except Exception:
                LOG.exception(
                    "Backend hook raised an exception."
                    " Falling back to default.")

        init_backend(type_)

    assert _cached_backend is not None  # nosec B101 : this is for typing

    return _cached_backend


def get_backend_type() -> BackendType | None:
    """Return the type of the current backend, or None if not set."""
    return _cached_backend_type


def get_component(name: str) -> Any:
    """Retrieve a specific component from the backend."""
    global _cached_components

    if _cached_components is None:
        get_backend()

    assert _cached_components is not None  # nosec B101 : this is for typing

    if name not in _cached_components:
        raise KeyError(f"Component {name!r} not found in backend.")

    return _cached_components[name]
