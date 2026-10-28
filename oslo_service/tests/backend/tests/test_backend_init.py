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
import types
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


class TestBackendLoadingErrors(BackendTestCase):
    def setUp(self):
        super().setUp()
        self.backend = mock.Mock()
        self.components = {"ServiceBase": object()}
        self.backend.get_service_components.return_value = self.components
        self.backend_class = mock.Mock(return_value=self.backend)
        module = types.SimpleNamespace(
            EventletBackend=self.backend_class,
            ThreadingBackend=self.backend_class,
        )
        self.import_module = self.enterContext(
            mock.patch.object(
                backend_module.importlib, "import_module", return_value=module
            )
        )

    def assert_cache_empty(self):
        self.assertIsNone(backend_module._cached_backend)
        self.assertIsNone(backend_module._cached_backend_type)
        self.assertIsNone(backend_module._cached_components)

    def test_missing_backend_dependencies(self):
        for backend_type, dependency in (
            (BackendType.EVENTLET, "eventlet"),
            (BackendType.THREADING, "cotyledon"),
        ):
            with self.subTest(backend=backend_type):
                self.import_module.reset_mock()
                error = ModuleNotFoundError(
                    f"No module named {dependency!r}", name=dependency
                )
                self.import_module.side_effect = error

                with self.assertRaises(ImportError) as caught:
                    init_backend(backend_type)

                message = str(caught.exception)
                self.assertIn(
                    f"Cannot initialize {backend_type.value!r} backend",
                    message,
                )
                self.assertIn(
                    f"required module {dependency!r} is not installed", message
                )
                self.assertIn("Install the dependencies", message)
                self.assertNotIn("Unknown backend", message)
                self.assertIs(caught.exception.__cause__, error)
                self.import_module.assert_called_once_with(
                    f"oslo_service.backend._{backend_type.value}"
                )
                self.assert_cache_empty()

    def test_missing_backend_module(self):
        module_name = "oslo_service.backend._eventlet"
        error = ModuleNotFoundError(
            f"No module named {module_name!r}", name=module_name
        )
        self.import_module.side_effect = error

        with self.assertRaisesRegex(
            ValueError, "Unknown backend: 'eventlet'"
        ) as caught:
            init_backend(BackendType.EVENTLET)

        self.assertIs(caught.exception.__cause__, error)
        self.assert_cache_empty()

    def test_missing_backend_class(self):
        self.import_module.return_value = types.SimpleNamespace()

        with self.assertRaisesRegex(
            ImportError,
            "Backend class not found in module oslo_service.backend._eventlet",
        ) as caught:
            init_backend(BackendType.EVENTLET)

        self.assertIsInstance(caught.exception.__cause__, AttributeError)
        self.assert_cache_empty()

    def test_successful_initialization(self):
        for backend_type in BackendType:
            with self.subTest(backend=backend_type):
                backend_module._reset_backend()
                self.import_module.reset_mock()
                self.backend_class.reset_mock()

                init_backend(backend_type)

                self.assertIs(get_backend(), self.backend)
                self.assertIs(backend_module.get_backend_type(), backend_type)
                self.assertIs(
                    backend_module._cached_components, self.components
                )
                self.assertIs(
                    backend_module.get_component("ServiceBase"),
                    self.components["ServiceBase"],
                )
                self.import_module.assert_called_once_with(
                    f"oslo_service.backend._{backend_type.value}"
                )
                self.backend_class.assert_called_once_with()

    def test_default_backend_missing_dependency(self):
        error = ModuleNotFoundError(
            "No module named 'eventlet'", name="eventlet"
        )
        self.import_module.side_effect = error

        with mock.patch.object(
            backend_module, "DEFAULT_BACKEND_TYPE", BackendType.EVENTLET
        ):
            with self.assertRaisesRegex(
                ImportError,
                "Cannot initialize 'eventlet' backend: "
                "required module 'eventlet' is not installed",
            ) as caught:
                get_backend()

        self.assertIs(caught.exception.__cause__, error)
        self.import_module.assert_called_once_with(
            "oslo_service.backend._eventlet"
        )
        self.assert_cache_empty()

    def test_import_errors_are_preserved(self):
        for error in (
            RuntimeError("Backend import failed"),
            AttributeError("Backend import failed"),
            ImportError("Backend import failed"),
            ModuleNotFoundError("Backend import failed"),
        ):
            with self.subTest(error=type(error).__name__):
                self.import_module.side_effect = error

                with self.assertRaises(type(error)) as caught:
                    init_backend(BackendType.EVENTLET)

                self.assertIs(caught.exception, error)
                self.assert_cache_empty()

    def test_failed_import_allows_retry(self):
        self.import_module.side_effect = ModuleNotFoundError(
            "No module named 'eventlet'", name="eventlet"
        )

        with self.assertRaises(ImportError):
            init_backend(BackendType.EVENTLET)

        self.assert_cache_empty()
        self.import_module.side_effect = None
        init_backend(BackendType.EVENTLET)
        self.assertIs(get_backend(), self.backend)
        self.assertIs(backend_module.get_backend_type(), BackendType.EVENTLET)
        self.assertIs(backend_module._cached_components, self.components)

    def test_initialization_errors_preserve_cache_and_allow_retry(self):
        for stage, failing_mock in (
            ("constructor", self.backend_class),
            ("components", self.backend.get_service_components),
        ):
            for error_type in (RuntimeError, AttributeError, ImportError):
                with self.subTest(stage=stage, error=error_type.__name__):
                    backend_module._reset_backend()
                    error = error_type("Backend initialization failed")
                    failing_mock.side_effect = error

                    with self.assertRaises(error_type) as caught:
                        init_backend(BackendType.EVENTLET)

                    self.assertIs(caught.exception, error)
                    self.assert_cache_empty()
                    failing_mock.side_effect = None
                    init_backend(BackendType.EVENTLET)
                    self.assertIs(get_backend(), self.backend)
                    self.assertIs(
                        backend_module.get_backend_type(), BackendType.EVENTLET
                    )
                    self.assertIs(
                        backend_module._cached_components, self.components
                    )


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
