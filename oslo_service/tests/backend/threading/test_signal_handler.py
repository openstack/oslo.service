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
import time
from unittest import mock
from unittest import TestCase

import cotyledon
from oslo_config import cfg

from oslo_service.backend._threading import service
from oslo_service.tests.backend.threading import test_signal_handler as sg


class DummyProcessLauncher():

    def __init__(self, **kwargs):
        self.signal_handler = service.SignalHandler()
        self.signal_handler.add_handler('SIGTERM', self._graceful_shutdown)

    def launch_service(self, service):
        self.s1 = service

    def _graceful_shutdown(self, *args):
        self.signal_handler.clear()
        self.s1.stop()


class DummyService(service.ServiceBase):

    def __init__(self, service_sleep=0, **kwargs):
        super().__init__(**kwargs)
        self.service_sleep = service_sleep

    def start(self):
        pass

    def stop(self):
        time.sleep(self.service_sleep)
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
        # Reset ServiceManager singleton between tests
        # This allows creating multiple ServiceManager instances in tests
        cotyledon.ServiceManager._process_runner_already_created = False

    @mock.patch.object(sg.DummyService, 'stop')
    def test_signal_handler(self, mock_stop):
        launcher = DummyProcessLauncher()
        launcher.launch_service(self.s1)
        os.kill(os.getpid(), signal.SIGTERM)
        mock_stop.assert_called_once_with()

    @mock.patch.object(service.ProcessLauncher, '_graceful_shutdown')
    @mock.patch.object(service.ProcessLauncher, '_fast_exit')
    @mock.patch.object(service.ProcessLauncher, '_reload_service')
    @mock.patch.object(service.ProcessLauncher, '_on_alarm_exit')
    def test_added_signal_handler(self, mock_a, mock_r, mock_f, mock_g):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        launcher.launch_service(self.s1)
        signal_handler = launcher.signal_handler
        self.assertEqual(4, len(signal_handler._signal_handlers))
        signal_handler._handle_signal_cb(signal.SIGTERM, 'test')
        mock_g.assert_called_once_with(signal.SIGTERM, 'test')
        signal_handler._handle_signal_cb(signal.SIGINT, 'test1')
        mock_f.assert_called_once_with(signal.SIGINT, 'test1')
        signal_handler._handle_signal_cb(signal.SIGHUP, 'test2')
        mock_r.assert_called_once_with(signal.SIGHUP, 'test2')
        signal_handler._handle_signal_cb(signal.SIGALRM, 'test3')
        mock_a.assert_called_once_with(signal.SIGALRM, 'test3')

    @mock.patch.object(sg.DummyService, 'stop')
    def test_sigterm_signal_handler_call_service_stop(
            self, mock_stop):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        launcher.launch_service(self.s1)
        signal_handler = launcher.signal_handler
        with mock.patch('os._exit'):
            signal_handler._handle_signal_cb(signal.SIGTERM, 'test')
            mock_stop.assert_called_once_with()

    def test_second_sigterm_is_ignored(self):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        launcher.launch_service(self.s1)
        signal_handler = launcher.signal_handler
        self.assertEqual(4, len(signal_handler._signal_handlers))
        with mock.patch('os._exit'):
            signal_handler._handle_signal_cb(signal.SIGTERM, 'test')
            self.assertEqual(3, len(signal_handler._signal_handlers))
            signo = signal_handler._signals_by_name['SIGTERM']
            self.assertNotIn(signo, signal_handler._signal_handlers)

    @mock.patch.object(service.ProcessLauncher, '_on_alarm_exit')
    def test_sigterm_timeout_terminated_by_sigalrm(self, mock_alarm):
        conf = cfg.ConfigOpts()
        launcher = service.ProcessLauncher(conf, no_fork=True)
        service_sleep = 5
        # service.stop will sleep for service_sleep, to get timeout and
        # SIGALRM terminate the process, set lower time for signal.alarm
        conf.set_default("graceful_shutdown_timeout", service_sleep - 2)
        s1 = DummyService(service_sleep=service_sleep)
        launcher.launch_service(s1)
        signal_handler = launcher.signal_handler
        with mock.patch('os._exit'):
            signal_handler._handle_signal_cb(signal.SIGTERM, 'test')
            sig_alarm_no = signal_handler._signals_by_name['SIGALRM'].value
            mock_alarm.assert_called_once_with(sig_alarm_no, mock.ANY)

    @mock.patch.object(service.ProcessLauncher, '_on_alarm_exit')
    def test_sigterm_terminated_noramally_before_sigalrm(self, mock_alarm):
        conf = cfg.ConfigOpts()
        launcher = service.ProcessLauncher(conf, no_fork=True)
        service_sleep = 0
        # service.stop will sleep for service_sleep, to terminate it normally,
        # set higher time for signal.alarm and check it is not terminated
        # by the signal alarm.
        conf.set_default("graceful_shutdown_timeout", service_sleep + 2)
        s1 = DummyService(service_sleep=service_sleep)
        launcher.launch_service(s1)
        signal_handler = launcher.signal_handler
        with mock.patch('os._exit'):
            signal_handler._handle_signal_cb(signal.SIGTERM, 'test')
            mock_alarm.assert_not_called()

    def test_no_signal_handler_for_fork(self):
        launcher = service.ProcessLauncher(self.conf, no_fork=False)
        launcher.launch_service(self.s1)
        self.assertIsNone(launcher.signal_handler)
