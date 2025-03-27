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

import oslo_service.backend as backend_module
from oslo_service.backend import BackendType
from oslo_service.backend import exceptions
from oslo_service.backend import get_backend
from oslo_service.backend import init_backend


class TestBackend(unittest.TestCase):
    def setUp(self):
        backend_module._reset_backend()

    def tearDown(self):
        backend_module._reset_backend()

    def test_default_backend(self):
        """Test default backend is eventlet."""
        backend = get_backend()
        self.assertEqual(backend.__class__.__name__, "EventletBackend")

    def test_init_backend_explicit(self):
        """Test that init_backend() can be called before get_backend()."""
        init_backend(BackendType.EVENTLET)
        backend = get_backend()
        self.assertEqual(backend.__class__.__name__, "EventletBackend")

    def test_dont_reinit_backend_from_default(self):
        """Fail if init_backend() called after get_backend() with another."""
        get_backend()
        with self.assertRaisesRegex(
            exceptions.BackendAlreadySelected,
            "Backend already set to 'eventlet'",
        ):
            init_backend(BackendType.THREADING)

    def test_dont_reinit_backend_explicit_init(self):
        """Fail if init_backend() called twice with different backend."""
        init_backend(BackendType.EVENTLET)
        with self.assertRaisesRegex(
            exceptions.BackendAlreadySelected,
            "Backend already set to 'eventlet'",
        ):
            init_backend(BackendType.THREADING)

    def test_reinit_backend_same_type_is_noop(self):
        """init_backend() with same type is a no-op."""
        init_backend(BackendType.EVENTLET)
        try:
            init_backend(BackendType.EVENTLET)
        except exceptions.BackendAlreadySelected:
            self.fail(
                "init_backend() should be a no-op if same type is passed"
            )

    def test_cached_backend(self):
        """Test backend is cached after initial load."""
        backend1 = get_backend()
        backend2 = get_backend()
        self.assertIs(
            backend1, backend2, "Backend should be cached and reused.")

    def test_cache_invalidation(self):
        """Test that cache is invalidated correctly."""
        backend1 = get_backend()
        backend_module._reset_backend()
        backend2 = get_backend()
        self.assertNotEqual(
            backend1, backend2, "Cache invalidation should reload the backend."
        )

    def test_backend_components(self):
        """Test that components are cached when init_backend is called."""
        init_backend(BackendType.EVENTLET)
        backend = get_backend()
        self.assertTrue(
            {"ServiceBase", "ServiceLauncher"}.intersection(
                backend.get_service_components()
            )
        )

    def test_get_backend_type(self):
        """Ensure get_backend_type() returns the selected backend."""
        self.assertIsNone(backend_module.get_backend_type())
        init_backend(BackendType.THREADING)
        self.assertEqual(
            backend_module.get_backend_type(), BackendType.THREADING)


class TestBackendHook(unittest.TestCase):
    def setUp(self):
        super().setUp()
        backend_module._reset_backend()

    def test_hook_sets_default_backend_when_not_explicitly_initialized(self):
        backend_module.register_backend_default_hook(
            lambda: BackendType.THREADING)
        result = backend_module.get_backend()
        self.assertEqual(
            backend_module._cached_backend_type, BackendType.THREADING)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.get_service_components())

    def test_hook_is_ignored_if_backend_already_initialized(self):
        backend_module.init_backend(BackendType.EVENTLET)
        backend_module.register_backend_default_hook(
            lambda: BackendType.THREADING)
        self.assertEqual(
            backend_module._cached_backend_type, BackendType.EVENTLET)

    def test_second_init_backend_raises_exception_even_with_hook(self):
        backend_module.init_backend(BackendType.THREADING)
        backend_module.register_backend_default_hook(
            lambda: BackendType.EVENTLET)
        with self.assertRaises(exceptions.BackendAlreadySelected):
            backend_module.init_backend(BackendType.EVENTLET)
