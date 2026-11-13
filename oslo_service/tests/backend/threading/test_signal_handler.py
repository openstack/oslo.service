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

import signal
import time
from unittest import mock
from unittest import TestCase

import cotyledon
from oslo_config import cfg

from oslo_service.backend._threading import service
from oslo_service.tests.backend.threading import test_signal_handler as sg


class DummyProcessLauncher:
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


class LateSighupProcessLauncher(service.ProcessLauncher):
    """Gets SIGHUPs just before _wait_no_fork() clears _waiting.

    Python runs a signal handler between any two bytecodes, so a SIGHUP can
    land in the finally that clears the flag.
    """

    late_sighups = 0

    @property
    def _waiting(self):
        return self.__dict__.get('_waiting_flag', False)

    @_waiting.setter
    def _waiting(self, value):
        if not value and self._waiting and self.late_sighups:
            self.late_sighups -= 1
            self.signal_handler._handle_signal_cb(signal.SIGHUP, None)
        self.__dict__['_waiting_flag'] = value


class SignalHandlerTestCase(TestCase):
    def setUp(self):
        super().setUp()
        signal_handler = service.SignalHandler()
        signal_handler.clear()
        self.addCleanup(signal_handler.clear)
        # _graceful_shutdown() arms a real process-wide SIGALRM. Tests mock
        # os._exit(), so a successful shutdown does not terminate the test
        # worker and the pending alarm could kill an unrelated later test.
        self.addCleanup(signal.alarm, 0)
        self.conf = cfg.ConfigOpts()
        self.s1 = DummyService()
        # Reset ServiceManager singleton between tests
        # This allows creating multiple ServiceManager instances in tests
        cotyledon.ServiceManager._process_runner_already_created = False

    @mock.patch.object(sg.DummyService, 'stop')
    def test_signal_handler(self, mock_stop):
        launcher = DummyProcessLauncher()
        launcher.launch_service(self.s1)
        launcher.signal_handler._handle_signal_cb(signal.SIGTERM, None)
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
    def test_sigterm_signal_handler_call_service_stop(self, mock_stop):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        launcher.launch_service(self.s1)
        signal_handler = launcher.signal_handler
        with mock.patch('os._exit') as mock_exit:
            signal_handler._handle_signal_cb(signal.SIGTERM, 'test')
            mock_stop.assert_called_once_with()
            mock_exit.assert_called_once_with(0)

    def test_failed_start_stops_the_service_and_exits(self):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        with (
            mock.patch.object(self.s1, 'start', side_effect=RuntimeError),
            mock.patch.object(self.s1, 'stop') as mock_stop,
            mock.patch('os._exit', side_effect=SystemExit) as mock_exit,
        ):
            self.assertRaises(SystemExit, launcher.launch_service, self.s1)
        mock_stop.assert_called_once_with()
        mock_exit.assert_called_once_with(1)

    def test_second_sigterm_is_ignored(self):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        launcher.launch_service(self.s1)
        signal_handler = launcher.signal_handler
        self.assertEqual(4, len(signal_handler._signal_handlers))
        with mock.patch('os._exit'):
            signal_handler._handle_signal_cb(signal.SIGTERM, 'test')
            # SIGHUP is ignored too.
            self.assertEqual(2, len(signal_handler._signal_handlers))
            for name in ('SIGTERM', 'SIGHUP'):
                signo = signal_handler._signals_by_name[name]
                self.assertNotIn(signo, signal_handler._signal_handlers)

    def _launch_with_sighup(self, launcher):
        """Launch the service, which gets a SIGHUP in its first wait()."""
        waits = []

        def wait():
            waits.append(True)
            if len(waits) == 1:
                launcher.signal_handler._handle_signal_cb(signal.SIGHUP, None)

        with mock.patch.object(self.s1, 'wait', side_effect=wait):
            launcher.launch_service(self.s1)
        return len(waits)

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_sighup_mutates_the_configuration(self, mock_daemon):
        launcher = service.ProcessLauncher(
            self.conf, no_fork=True, restart_method='mutate'
        )
        with (
            mock.patch.object(self.conf, 'mutate_config_files') as mutate,
            mock.patch.object(self.s1, 'start') as start,
            mock.patch.object(self.s1, 'stop') as stop,
            mock.patch.object(self.s1, 'reset') as reset,
        ):
            # The launcher waits for the service again.
            self.assertEqual(2, self._launch_with_sighup(launcher))
        mutate.assert_called_once_with()
        reset.assert_called_once_with()
        start.assert_called_once_with()
        stop.assert_not_called()
        # The next signals are handled too.
        self.assertEqual(4, len(launcher.signal_handler._signal_handlers))

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_sighup_reloads_the_configuration_and_restarts(self, mock_daemon):
        launcher = service.ProcessLauncher(
            self.conf, no_fork=True, restart_method='reload'
        )
        calls = mock.Mock()
        with (
            mock.patch.object(self.conf, 'reload_config_files', calls.reload),
            mock.patch.object(self.s1, 'start', calls.start),
            mock.patch.object(self.s1, 'stop', calls.stop),
            mock.patch.object(self.s1, 'reset', calls.reset),
        ):
            self.assertEqual(2, self._launch_with_sighup(launcher))
        self.assertEqual(
            ['start', 'reload', 'stop', 'reset', 'start'],
            [call[0] for call in calls.mock_calls],
        )

    @mock.patch.object(service.common_service, 'is_daemon', return_value=False)
    def test_sighup_ends_a_foreground_process(self, mock_daemon):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        with (
            mock.patch.object(self.s1, 'stop') as stop,
            mock.patch.object(self.s1, 'reset') as reset,
            mock.patch('os._exit') as exit_,
        ):
            self.assertEqual(1, self._launch_with_sighup(launcher))
        stop.assert_called_once_with()
        exit_.assert_called_once_with(0)
        reset.assert_not_called()

    def test_failed_start_exits_when_stop_fails(self):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        with (
            mock.patch.object(self.s1, 'start', side_effect=RuntimeError),
            mock.patch.object(self.s1, 'stop', side_effect=AttributeError),
            mock.patch('os._exit', side_effect=SystemExit) as exit_,
        ):
            self.assertRaises(SystemExit, launcher.launch_service, self.s1)
        exit_.assert_called_once_with(1)

    def test_sigterm_exits_when_stop_fails(self):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        launcher.launch_service(self.s1)
        with (
            mock.patch.object(self.s1, 'stop', side_effect=AttributeError),
            mock.patch('os._exit') as exit_,
        ):
            launcher.signal_handler._handle_signal_cb(signal.SIGTERM, None)
        exit_.assert_called_once_with(1)

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_failed_reset_stops_the_service_and_exits(self, mock_daemon):
        launcher = service.ProcessLauncher(
            self.conf, no_fork=True, restart_method='mutate'
        )
        with (
            mock.patch.object(self.conf, 'mutate_config_files'),
            mock.patch.object(self.s1, 'reset', side_effect=RuntimeError),
            mock.patch.object(self.s1, 'stop') as stop,
            mock.patch('os._exit', side_effect=SystemExit) as exit_,
        ):
            self.assertRaises(SystemExit, self._launch_with_sighup, launcher)
        stop.assert_called_once_with()
        exit_.assert_called_once_with(1)

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_failed_restart_stops_the_service_and_exits(self, mock_daemon):
        launcher = service.ProcessLauncher(
            self.conf, no_fork=True, restart_method='reload'
        )
        with (
            mock.patch.object(self.conf, 'reload_config_files'),
            mock.patch.object(
                self.s1, 'start', side_effect=[None, RuntimeError]
            ),
            mock.patch.object(self.s1, 'stop') as stop,
            mock.patch('os._exit', side_effect=SystemExit) as exit_,
        ):
            self.assertRaises(SystemExit, self._launch_with_sighup, launcher)
        # Once to restart the service, once to shut down.
        self.assertEqual(2, stop.call_count)
        exit_.assert_called_once_with(1)

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_sighup_during_start_reloads_after_start(self, mock_daemon):
        launcher = service.ProcessLauncher(
            self.conf, no_fork=True, restart_method='mutate'
        )
        calls = mock.Mock()

        def start():
            calls.start()
            launcher.signal_handler._handle_signal_cb(signal.SIGHUP, None)
            calls.start_done()

        with (
            mock.patch.object(self.conf, 'mutate_config_files', calls.mutate),
            mock.patch.object(self.s1, 'start', side_effect=start),
            mock.patch.object(self.s1, 'reset', calls.reset),
            mock.patch.object(self.s1, 'wait', calls.wait),
        ):
            launcher.launch_service(self.s1)
        self.assertEqual(
            ['start', 'start_done', 'mutate', 'reset', 'wait'],
            [call[0] for call in calls.mock_calls],
        )

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_sighups_during_restart_reload_once_more(self, mock_daemon):
        launcher = service.ProcessLauncher(
            self.conf, no_fork=True, restart_method='mutate'
        )
        resets = []

        def reset():
            resets.append(True)
            if len(resets) == 1:
                # Several SIGHUPs during one restart give one more reload,
                # not one reload each.
                for _ in range(3):
                    launcher.signal_handler._handle_signal_cb(
                        signal.SIGHUP, None
                    )

        with (
            mock.patch.object(self.conf, 'mutate_config_files'),
            mock.patch.object(self.s1, 'reset', side_effect=reset),
        ):
            # The launcher waits for the service again after both reloads.
            self.assertEqual(2, self._launch_with_sighup(launcher))
        self.assertEqual(2, len(resets))

    def test_sighup_during_failed_start_does_not_reload(self):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)

        def start():
            launcher.signal_handler._handle_signal_cb(signal.SIGHUP, None)
            raise RuntimeError()

        with (
            mock.patch.object(self.s1, 'start', side_effect=start),
            mock.patch.object(self.s1, 'reset') as reset,
            mock.patch('os._exit', side_effect=SystemExit) as exit_,
        ):
            self.assertRaises(SystemExit, launcher.launch_service, self.s1)
        exit_.assert_called_once_with(1)
        reset.assert_not_called()

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_sighup_during_shutdown_is_ignored(self, mock_daemon):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)

        def wait():
            launcher.signal_handler._handle_signal_cb(signal.SIGTERM, None)

        def stop():
            launcher.signal_handler._handle_signal_cb(signal.SIGHUP, None)

        with (
            mock.patch.object(self.s1, 'wait', side_effect=wait),
            mock.patch.object(self.s1, 'stop', side_effect=stop),
            mock.patch.object(self.s1, 'reset') as reset,
            mock.patch('os._exit', side_effect=SystemExit) as exit_,
        ):
            self.assertRaises(SystemExit, launcher.launch_service, self.s1)
        exit_.assert_called_once_with(0)
        reset.assert_not_called()

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_sighup_while_a_sighup_unwinds(self, mock_daemon):
        launcher = LateSighupProcessLauncher(
            self.conf, no_fork=True, restart_method='mutate'
        )
        launcher.late_sighups = 1
        with (
            mock.patch.object(self.conf, 'mutate_config_files'),
            mock.patch.object(self.s1, 'reset') as reset,
        ):
            # The launcher waits for the service again after one reload.
            self.assertEqual(2, self._launch_with_sighup(launcher))
        reset.assert_called_once_with()

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_sighup_while_a_pending_reload_starts(self, mock_daemon):
        launcher = LateSighupProcessLauncher(
            self.conf, no_fork=True, restart_method='mutate'
        )

        def start():
            launcher.signal_handler._handle_signal_cb(signal.SIGHUP, None)
            launcher.late_sighups = 1

        with (
            mock.patch.object(self.conf, 'mutate_config_files'),
            mock.patch.object(self.s1, 'start', side_effect=start),
            mock.patch.object(self.s1, 'reset') as reset,
            mock.patch.object(self.s1, 'wait') as wait,
        ):
            launcher.launch_service(self.s1)
        reset.assert_called_once_with()
        wait.assert_called_once_with()

    @mock.patch.object(service.common_service, 'is_daemon', return_value=True)
    def test_other_signal_exit_leaves_the_wait(self, mock_daemon):
        launcher = service.ProcessLauncher(self.conf, no_fork=True)
        signal_exit = service.common_service.SignalExit(signal.SIGINT)
        with (
            mock.patch.object(
                self.s1, 'wait', side_effect=[signal_exit, None]
            ),
            mock.patch.object(launcher, 'restart') as restart,
            self.assertRaises(service.common_service.SignalExit) as caught,
        ):
            launcher.launch_service(self.s1)
        self.assertIs(signal_exit, caught.exception)
        restart.assert_not_called()

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
