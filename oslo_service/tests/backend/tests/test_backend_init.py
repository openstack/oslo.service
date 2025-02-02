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
        """test that init_backend() can be called before get_backend()"""

        init_backend(BackendType.EVENTLET)

        backend = get_backend()
        self.assertEqual(backend.__class__.__name__, "EventletBackend")

    def test_dont_reinit_backend_from_default(self):
        """test that init_backend() can't be called after get_backend()"""

        get_backend()

        with self.assertRaisesRegex(
            exceptions.BackendAlreadySelected,
            "The 'eventlet' backend is already set up",
        ):
            init_backend(BackendType.EVENTLET)

    def test_dont_reinit_backend_explicit_init(self):
        """test that init_backend() can't be called twice"""

        init_backend(BackendType.EVENTLET)

        with self.assertRaisesRegex(
            exceptions.BackendAlreadySelected,
            "The 'eventlet' backend is already set up",
        ):
            init_backend(BackendType.EVENTLET)

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
