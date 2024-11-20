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

import unittest
from unittest import mock

from oslo_service.backend.base import BaseBackend
from oslo_service.backend.base import ComponentRegistry
from oslo_service.backend.exceptions import BackendComponentNotAvailable


class TestBaseBackend(unittest.TestCase):
    def test_backend_with_valid_implementation(self):
        """Test that a valid backend subclass works correctly."""
        class ValidBackend(BaseBackend):
            def get_service_components(self):
                return {"ServiceLauncher": "mock_service_launcher"}

        backend = ValidBackend()
        components = backend.get_service_components()
        self.assertIn("ServiceLauncher", components)
        self.assertEqual(
            components["ServiceLauncher"], "mock_service_launcher")


class TestComponentRegistry(unittest.TestCase):
    def setUp(self):
        """Set up components for testing."""
        self.components = {
            "ServiceLauncher": "mock_service_launcher",
            "ProcessLauncher": "mock_process_launcher",
        }
        self.registry = ComponentRegistry(self.components)

    def test_get_existing_component(self):
        """Test getting an existing component."""
        self.assertEqual(
            self.registry["ServiceLauncher"], "mock_service_launcher")
        self.assertEqual(
            self.registry["ProcessLauncher"], "mock_process_launcher")

    def test_get_missing_component(self):
        """Test accessing a missing component raises NotImplementedError."""
        with self.assertRaises(BackendComponentNotAvailable) as context:
            _ = self.registry["LoopingCall"]
        self.assertIn(
            "Component 'LoopingCall' is not available",
            str(context.exception))

    def test_contains_existing_component(self):
        """Test checking if an existing component is in the proxy."""
        self.assertIn("ServiceLauncher", self.registry)
        self.assertIn("ProcessLauncher", self.registry)

    def test_contains_missing_component(self):
        """Test checking if a missing component is in the proxy."""
        self.assertNotIn("LoopingCall", self.registry)


class TestComponentRegistryIntegration(unittest.TestCase):
    def test_service_integration_with_backend(self):
        """Test registry usage."""
        # Mock backend components
        components = {
            "ServiceLauncher": mock.Mock(),
            "ProcessLauncher": None,  # Simulate an unimplemented component
        }
        registry = ComponentRegistry(components)

        # Validate successful retrieval of an available component
        self.assertIn("ServiceLauncher", registry)
        self.assertIsNotNone(registry["ServiceLauncher"])

        # Validate BackendNotAvailable exception for unavailable components
        with self.assertRaises(BackendComponentNotAvailable):
            registry["ProcessLauncher"]

        with self.assertRaises(BackendComponentNotAvailable):
            registry["NonExistentComponent"]
