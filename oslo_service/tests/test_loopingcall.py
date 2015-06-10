# Copyright 2012 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock
from oslotest import base as test_base

from oslo_service import loopingcall


class LoopingCallTestCase(test_base.BaseTestCase):

    def setUp(self):
        super(LoopingCallTestCase, self).setUp()
        self.num_runs = 0

    def test_return_true(self):
        def _raise_it():
            raise loopingcall.LoopingCallDone(True)

        timer = loopingcall.FixedIntervalLoopingCall(_raise_it)
        self.assertTrue(timer.start(interval=0.5).wait())

    def test_return_false(self):
        def _raise_it():
            raise loopingcall.LoopingCallDone(False)

        timer = loopingcall.FixedIntervalLoopingCall(_raise_it)
        self.assertFalse(timer.start(interval=0.5).wait())

    def test_terminate_on_exception(self):
        def _raise_it():
            raise RuntimeError()

        timer = loopingcall.FixedIntervalLoopingCall(_raise_it)
        self.assertRaises(RuntimeError, timer.start(interval=0.5).wait)

    def _wait_for_zero(self):
        """Called at an interval until num_runs == 0."""
        if self.num_runs == 0:
            raise loopingcall.LoopingCallDone(False)
        else:
            self.num_runs = self.num_runs - 1

    def test_repeat(self):
        self.num_runs = 2

        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_zero)
        self.assertFalse(timer.start(interval=0.5).wait())

    def assertAlmostEqual(self, expected, actual, precision=7, message=None):
        self.assertEqual(0, round(actual - expected, precision), message)

    @mock.patch('eventlet.greenthread.sleep')
    @mock.patch('oslo_utils.timeutils.now')
    def test_interval_adjustment(self, time_mock, sleep_mock):
        """Ensure the interval is adjusted to account for task duration."""
        self.num_runs = 3

        now = 1234567890
        second = 1
        smidgen = 0.01

        time_mock.side_effect = [now,  # restart
                                 now + second - smidgen,  # end
                                 now,  # restart
                                 now + second + second,  # end
                                 now,  # restart
                                 now + second + smidgen,  # end
                                 now]  # restart
        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_zero)
        timer.start(interval=1.01).wait()

        expected_calls = [0.02, 0.00, 0.00]
        for i, call in enumerate(sleep_mock.call_args_list):
            expected = expected_calls[i]
            args, kwargs = call
            actual = args[0]
            message = ('Call #%d, expected: %s, actual: %s' %
                       (i, expected, actual))
            self.assertAlmostEqual(expected, actual, message=message)


class DynamicLoopingCallTestCase(test_base.BaseTestCase):
    def setUp(self):
        super(DynamicLoopingCallTestCase, self).setUp()
        self.num_runs = 0

    def test_return_true(self):
        def _raise_it():
            raise loopingcall.LoopingCallDone(True)

        timer = loopingcall.DynamicLoopingCall(_raise_it)
        self.assertTrue(timer.start().wait())

    def test_return_false(self):
        def _raise_it():
            raise loopingcall.LoopingCallDone(False)

        timer = loopingcall.DynamicLoopingCall(_raise_it)
        self.assertFalse(timer.start().wait())

    def test_terminate_on_exception(self):
        def _raise_it():
            raise RuntimeError()

        timer = loopingcall.DynamicLoopingCall(_raise_it)
        self.assertRaises(RuntimeError, timer.start().wait)

    def _wait_for_zero(self):
        """Called at an interval until num_runs == 0."""
        if self.num_runs == 0:
            raise loopingcall.LoopingCallDone(False)
        else:
            self.num_runs = self.num_runs - 1
            sleep_for = self.num_runs * 10 + 1  # dynamic duration
            return sleep_for

    def test_repeat(self):
        self.num_runs = 2

        timer = loopingcall.DynamicLoopingCall(self._wait_for_zero)
        self.assertFalse(timer.start().wait())

    @mock.patch('eventlet.greenthread.sleep')
    def test_interval_adjustment(self, sleep_mock):
        self.num_runs = 2

        timer = loopingcall.DynamicLoopingCall(self._wait_for_zero)
        timer.start(periodic_interval_max=5).wait()

        sleep_mock.assert_has_calls([mock.call(5), mock.call(1)])

    @mock.patch('eventlet.greenthread.sleep')
    def test_initial_delay(self, sleep_mock):
        self.num_runs = 1

        timer = loopingcall.DynamicLoopingCall(self._wait_for_zero)
        timer.start(initial_delay=3).wait()

        sleep_mock.assert_has_calls([mock.call(3), mock.call(1)])
