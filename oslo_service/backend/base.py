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

from abc import ABC
from abc import abstractmethod
from typing import Any

from oslo_service.backend.exceptions import BackendComponentNotAvailable


class BaseBackend(ABC):
    """Base class for all backend implementations."""

    @abstractmethod
    def get_service_components(self) -> dict[str, Any]:
        """Return the backend components.

        This method should return a dictionary containing all the components
        required for the backend to function. For example:
        {
            "ServiceLauncher": Class or function,
            "ProcessLauncher": Class or function,
            "Service": Class or function,
            "LoopingCall": Class or function,
            ...
        }
        """
        pass


class ComponentRegistry:
    """A registry to manage access to backend components.

    This class ensures that attempting to access a missing component
    raises an explicit error, improving clarity and debugging. It acts
    as a centralized registry for backend components.
    """
    def __init__(self, components):
        """Initialize the registry with a dictionary of components.

        :param components: A dictionary containing backend components, where
                           the keys are component names and the values are
                           the respective implementations.
        """
        self._components = components

    def __getitem__(self, key):
        """Retrieve a component by its key from the registry.

        :param key: The name of the component to retrieve.
        :raises NotImplementedError: If the component is
                                     not registered or available.
        :return: The requested component instance.
        """
        if key not in self._components or self._components[key] is None:
            raise BackendComponentNotAvailable(
                f"Component '{key}' is not available in this backend.")
        return self._components[key]

    def __contains__(self, key):
        """Check if a component is registered and available.

        :param key: The name of the component to check.
        :return: True if the component is registered
                 and available, False otherwise.
        """
        return key in self._components and self._components[key] is not None
