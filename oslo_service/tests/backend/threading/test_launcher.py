# Copyright (C) 2025 Red Hat, Inc.
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

from unittest import mock
from unittest import TestCase

import cotyledon
from oslo_config import cfg

from oslo_service.backend._threading import service


class DummyService(service.ServiceBase):
    def start(self):
        pass

    def stop(self, graceful=False):
        pass

    def wait(self):
        pass

    def reset(self):
        pass


class ProcessLauncherTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.conf = cfg.ConfigOpts()
        # Reset ServiceManager singleton between tests
        # This allows creating multiple ServiceManager instances in tests
        cotyledon.ServiceManager._process_runner_already_created = False

    def test_accepts_wait_interval_and_logs_warning(self):
        # Patch the actual logger used in the module
        with mock.patch('warnings.warn') as mock_warn:
            launcher = service.ProcessLauncher(self.conf, wait_interval=0.1)
            self.assertIsInstance(launcher, service.ProcessLauncher)

            # Ensure warning is logged
            mock_warn.assert_called_once()
            self.assertIn('wait_interval', mock_warn.call_args[0][0])

    def test_no_warning_without_wait_interval(self):
        with mock.patch('warnings.warn') as mock_warn:
            launcher = service.ProcessLauncher(self.conf)
            self.assertIsInstance(launcher, service.ProcessLauncher)
            mock_warn.assert_not_called()

    def test_allows_multiple_launch_service_calls(self):
        launcher = service.ProcessLauncher(self.conf)

        s1 = DummyService()
        s2 = DummyService()

        # Just check that both calls do not raise
        try:
            launcher.launch_service(s1)
            launcher.launch_service(s2)
        except Exception as e:
            self.fail(
                f"Multiple launch_service() calls raised an exception: {e}")


class LauncherTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.conf = cfg.ConfigOpts()
        # Reset ServiceManager singleton between tests
        # This allows creating multiple ServiceManager instances in tests
        cotyledon.ServiceManager._process_runner_already_created = False

    def test_graceful_shutdown_timeout_is_registered(self):
        launchers = [service.ProcessLauncher, service.ServiceLauncher]
        for launcher in launchers:
            conf = cfg.ConfigOpts()
            launcher(conf)
            timeout = 50
            conf.set_default("graceful_shutdown_timeout", timeout)
            self.assertEqual(conf.graceful_shutdown_timeout, timeout)

    @mock.patch('cotyledon.ServiceManager.add')
    @mock.patch('cotyledon.oslo_config_glue.link')
    def test_graceful_shutdown_timeout_is_set_in_cotyledon(
        self, mock_link, mock_add):
        launchers = [service.ProcessLauncher, service.ServiceLauncher]
        timeout = 20
        for launcher in launchers:
            with mock.patch.object(cotyledon.ServiceManager,
                                   '__init__', return_value=None) as mock_mgr:
                launcher_obj = launcher(self.conf)
                self.conf.set_default("graceful_shutdown_timeout", timeout)
                service1 = DummyService()
                launcher_obj.launch_service(service1)
                # Verify that ServiceManager was called with
                # graceful_shutdown_timeout and mp_context (for
                # spawn-safe support)
                mock_mgr.assert_called_once()
                call_kwargs = mock_mgr.call_args[1]
                self.assertEqual(
                    call_kwargs['graceful_shutdown_timeout'], timeout)
                self.assertIn('mp_context', call_kwargs)
