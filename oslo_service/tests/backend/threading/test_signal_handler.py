# Copyright (C) 2026 Red Hat, Inc.
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
import signal
from unittest import mock
from unittest import TestCase

from oslo_config import cfg

from oslo_service.backend._threading import service
from oslo_service.tests.backend.threading import test_signal_handler as sg


class DummyProcessLauncher(service.ProcessLauncher):

    def __init__(self, conf, **kwargs):
        self.signal_handler = service.SignalHandler()
        self.signal_handler.add_handler('SIGTERM', self._graceful_shutdown)
        super().__init__(conf, **kwargs)

    def launch_service(self, service):
        self.s1 = service

    def _graceful_shutdown(self, *args):
        self.signal_handler.clear()
        self.s1.stop()


class DummyService(service.ServiceBase):
    def start(self):
        pass

    def stop(self):
        pass

    def wait(self):
        pass

    def reset(self):
        pass


class SignalHandlerTestCase(TestCase):

    def setUp(self):
        super().setUp()
        self.conf = cfg.ConfigOpts()
        self.s1 = DummyService()

    @mock.patch.object(sg.DummyService, 'stop')
    def test_signal_handler(self, mock_stop):
        launcher = DummyProcessLauncher(self.conf)
        launcher.launch_service(self.s1)
        os.kill(os.getpid(), signal.SIGTERM)
        mock_stop.assert_called_once_with()
