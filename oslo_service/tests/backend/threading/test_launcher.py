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
