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

import os
import unittest
from unittest import mock

import oslo_service.backend as backend_module
from oslo_service.backend import BackendType
from oslo_service.backend import exceptions
from oslo_service.backend import get_backend
from oslo_service.backend import init_backend


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        # Restore the suite's backend and default hook after each test.
        for name in (
            '_cached_backend',
            '_cached_backend_type',
            '_cached_components',
            '_backend_hook',
        ):
            patcher = mock.patch.object(backend_module, name, None)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.backend_type = (
            BackendType.THREADING
            if os.environ.get('OSLO_SERVICE_SKIP_EVENTLET')
            else BackendType.EVENTLET
        )
        self.other_backend_type = (
            BackendType.EVENTLET
            if self.backend_type == BackendType.THREADING
            else BackendType.THREADING
        )

    def use_default_hook(self):
        backend_module.register_backend_default_hook(lambda: self.backend_type)


class TestBackend(BackendTestCase):
    def test_default_backend(self):
        """The library default remains eventlet, independent of test mode."""
        backend = mock.Mock()

        def initialize(type_):
            backend_module._cached_backend = backend

        with mock.patch.object(
            backend_module, 'init_backend', side_effect=initialize
        ) as initialize_mock:
            self.assertIs(backend, get_backend())
        initialize_mock.assert_called_once_with(BackendType.EVENTLET)

    def test_init_backend_explicit(self):
        init_backend(self.backend_type)
        backend = get_backend()
        self.assertEqual(
            backend.__class__.__name__,
            f'{self.backend_type.value.capitalize()}Backend',
        )

    def test_dont_reinit_backend_from_default(self):
        self.use_default_hook()
        get_backend()
        with self.assertRaisesRegex(
            exceptions.BackendAlreadySelected,
            f"Backend already set to '{self.backend_type.value}'",
        ):
            init_backend(self.other_backend_type)

    def test_dont_reinit_backend_explicit_init(self):
        init_backend(self.backend_type)
        with self.assertRaisesRegex(
            exceptions.BackendAlreadySelected,
            f"Backend already set to '{self.backend_type.value}'",
        ):
            init_backend(self.other_backend_type)

    def test_reinit_backend_same_type_is_noop(self):
        init_backend(self.backend_type)
        backend = get_backend()
        init_backend(self.backend_type)
        self.assertIs(backend, get_backend())

    def test_cached_backend(self):
        self.use_default_hook()
        self.assertIs(get_backend(), get_backend())

    def test_cache_invalidation(self):
        self.use_default_hook()
        backend1 = get_backend()
        backend_module._reset_backend()
        self.use_default_hook()
        self.assertIsNot(backend1, get_backend())

    def test_backend_components(self):
        init_backend(self.backend_type)
        self.assertTrue(
            {'ServiceBase', 'ServiceLauncher'}.issubset(
                get_backend().get_service_components()
            )
        )

    def test_get_backend_type(self):
        self.assertIsNone(backend_module.get_backend_type())
        init_backend(self.backend_type)
        self.assertEqual(self.backend_type, backend_module.get_backend_type())


class TestBackendHook(BackendTestCase):
    def test_hook_sets_default_backend_when_not_explicitly_initialized(self):
        self.use_default_hook()
        result = get_backend()
        self.assertEqual(self.backend_type, backend_module.get_backend_type())
        self.assertIsNotNone(result.get_service_components())

    def test_hook_is_ignored_if_backend_already_initialized(self):
        init_backend(self.backend_type)
        backend_module.register_backend_default_hook(
            lambda: self.other_backend_type
        )
        get_backend()
        self.assertEqual(self.backend_type, backend_module.get_backend_type())

    def test_second_init_backend_raises_exception_even_with_hook(self):
        init_backend(self.backend_type)
        backend_module.register_backend_default_hook(
            lambda: self.other_backend_type
        )
        with self.assertRaises(exceptions.BackendAlreadySelected):
            init_backend(self.other_backend_type)
