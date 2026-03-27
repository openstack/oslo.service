# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

"""Unit Tests for periodic_task decorator and PeriodicTasks class."""

import pickle
import sys
import threading
import time
from unittest import mock

import testtools
from testtools import matchers

from oslo_service import _multiprocessing
from oslo_service import backend
from oslo_service.backend.exceptions import UnsupportedBackendError
from oslo_service import periodic_task
from oslo_service.tests import base


class AnException(Exception):
    pass


# Minimal picklable conf for tests that run the real spawn pool (no lambdas).
class _PicklableConf:
    run_external_periodic_tasks = False

    def register_opts(self, opts):
        pass


# Module-level classes for run_periodic_tasks_in_parallel tests: instances
# must be picklable (sent to spawn workers). Local classes in test methods
# are not picklable.
class _PicklableManagerOneTask(periodic_task.PeriodicTasks):
    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task1(self, context):
        pass


class _PicklableManagerTenTasks(periodic_task.PeriodicTasks):
    def __init__(self, conf):
        super().__init__(conf)
        self.results = []

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task0(self, context):
        self.results.append(0)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task1(self, context):
        self.results.append(1)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task2(self, context):
        self.results.append(2)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task3(self, context):
        self.results.append(3)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task4(self, context):
        self.results.append(4)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task5(self, context):
        self.results.append(5)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task6(self, context):
        self.results.append(6)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task7(self, context):
        self.results.append(7)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task8(self, context):
        self.results.append(8)

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def task9(self, context):
        self.results.append(9)


class PeriodicTasksTestCase(base.ServiceBaseTestCase):
    """Test cases for PeriodicTasks."""

    @mock.patch('oslo_service.periodic_task.now')
    def test_called_thrice(self, mock_now):

        time = 340
        mock_now.return_value = time

        # Class inside test def to mock 'now' in
        # the periodic task decorator
        class AService(periodic_task.PeriodicTasks):
            def __init__(self, conf):
                super().__init__(conf)
                self.called = {'doit': 0, 'urg': 0, 'ticks': 0, 'tocks': 0}

            @periodic_task.periodic_task
            def doit(self, context):
                self.called['doit'] += 1

            @periodic_task.periodic_task
            def crashit(self, context):
                self.called['urg'] += 1
                raise AnException('urg')

            @periodic_task.periodic_task(
                spacing=10 + periodic_task.DEFAULT_INTERVAL,
                run_immediately=True)
            def doit_with_ticks(self, context):
                self.called['ticks'] += 1

            @periodic_task.periodic_task(
                spacing=10 + periodic_task.DEFAULT_INTERVAL)
            def doit_with_tocks(self, context):
                self.called['tocks'] += 1

        external_called = {'ext1': 0, 'ext2': 0}

        @periodic_task.periodic_task
        def ext1(self, context):
            external_called['ext1'] += 1

        @periodic_task.periodic_task(
            spacing=10 + periodic_task.DEFAULT_INTERVAL)
        def ext2(self, context):
            external_called['ext2'] += 1

        serv = AService(self.conf)
        serv.add_periodic_task(ext1)
        serv.add_periodic_task(ext2)
        serv.run_periodic_tasks(None)
        # Time: 340
        self.assertEqual(0, serv.called['doit'])
        self.assertEqual(0, serv.called['urg'])
        # New last run will be 350
        self.assertEqual(1, serv.called['ticks'])
        self.assertEqual(0, serv.called['tocks'])
        self.assertEqual(0, external_called['ext1'])
        self.assertEqual(0, external_called['ext2'])

        time = time + periodic_task.DEFAULT_INTERVAL
        mock_now.return_value = time
        serv.run_periodic_tasks(None)

        # Time:400
        # New Last run: 420
        self.assertEqual(1, serv.called['doit'])
        self.assertEqual(1, serv.called['urg'])
        # Closest multiple of 70 is 420
        self.assertEqual(1, serv.called['ticks'])
        self.assertEqual(0, serv.called['tocks'])
        self.assertEqual(1, external_called['ext1'])
        self.assertEqual(0, external_called['ext2'])

        time = time + periodic_task.DEFAULT_INTERVAL / 2
        mock_now.return_value = time
        serv.run_periodic_tasks(None)
        self.assertEqual(1, serv.called['doit'])
        self.assertEqual(1, serv.called['urg'])
        self.assertEqual(2, serv.called['ticks'])
        self.assertEqual(1, serv.called['tocks'])
        self.assertEqual(1, external_called['ext1'])
        self.assertEqual(1, external_called['ext2'])

        time = time + periodic_task.DEFAULT_INTERVAL
        mock_now.return_value = time
        serv.run_periodic_tasks(None)
        self.assertEqual(2, serv.called['doit'])
        self.assertEqual(2, serv.called['urg'])
        self.assertEqual(3, serv.called['ticks'])
        self.assertEqual(2, serv.called['tocks'])
        self.assertEqual(2, external_called['ext1'])
        self.assertEqual(2, external_called['ext2'])

    @mock.patch('oslo_service.periodic_task.now')
    def test_called_correct(self, mock_now):

        time = 360444
        mock_now.return_value = time

        test_spacing = 9

        # Class inside test def to mock 'now' in
        # the periodic task decorator
        class AService(periodic_task.PeriodicTasks):
            def __init__(self, conf):
                super().__init__(conf)
                self.called = {'ticks': 0}

            @periodic_task.periodic_task(spacing=test_spacing)
            def tick(self, context):
                self.called['ticks'] += 1

        serv = AService(self.conf)
        for i in range(200):
            serv.run_periodic_tasks(None)
            self.assertEqual(int(i / test_spacing), serv.called['ticks'])
            time += 1
            mock_now.return_value = time

    @mock.patch('oslo_service.periodic_task.now')
    def test_raises(self, mock_now):
        time = 230000
        mock_now.return_value = time

        class AService(periodic_task.PeriodicTasks):
            def __init__(self, conf):
                super().__init__(conf)
                self.called = {'urg': 0, }

            @periodic_task.periodic_task
            def crashit(self, context):
                self.called['urg'] += 1
                raise AnException('urg')

        serv = AService(self.conf)
        now = serv._periodic_last_run['crashit']

        mock_now.return_value = now + periodic_task.DEFAULT_INTERVAL
        self.assertRaises(AnException,
                          serv.run_periodic_tasks,
                          None, raise_on_error=True)

    def test_name(self):
        class AService(periodic_task.PeriodicTasks):
            def __init__(self, conf):
                super().__init__(conf)

            @periodic_task.periodic_task(name='better-name')
            def tick(self, context):
                pass

            @periodic_task.periodic_task
            def tack(self, context):
                pass

        @periodic_task.periodic_task(name='another-name')
        def foo(self, context):
            pass

        serv = AService(self.conf)
        serv.add_periodic_task(foo)
        self.assertIn('better-name', serv._periodic_last_run)
        self.assertIn('another-name', serv._periodic_last_run)
        self.assertIn('tack', serv._periodic_last_run)


class ManagerMetaTestCase(base.ServiceBaseTestCase):
    """Tests for the meta class which manages creation of periodic tasks."""

    def test_meta(self):
        class Manager(periodic_task.PeriodicTasks):

            @periodic_task.periodic_task
            def foo(self):
                return 'foo'

            @periodic_task.periodic_task(spacing=4)
            def bar(self):
                return 'bar'

            @periodic_task.periodic_task(enabled=False)
            def baz(self):
                return 'baz'

        m = Manager(self.conf)
        self.assertThat(m._periodic_tasks, matchers.HasLength(2))
        self.assertEqual(periodic_task.DEFAULT_INTERVAL,
                         m._periodic_spacing['foo'])
        self.assertEqual(4, m._periodic_spacing['bar'])
        self.assertThat(
            m._periodic_spacing, matchers.Not(matchers.Contains('baz')))

        @periodic_task.periodic_task
        def external():
            return 42

        m.add_periodic_task(external)
        self.assertThat(m._periodic_tasks, matchers.HasLength(3))
        self.assertEqual(periodic_task.DEFAULT_INTERVAL,
                         m._periodic_spacing['external'])


class ManagerTestCase(base.ServiceBaseTestCase):
    """Tests the periodic tasks portion of the manager class."""
    def setUp(self):
        super().setUp()

    def test_periodic_tasks_with_idle(self):
        class Manager(periodic_task.PeriodicTasks):

            @periodic_task.periodic_task(spacing=200)
            def bar(self):
                return 'bar'

        m = Manager(self.conf)
        self.assertThat(m._periodic_tasks, matchers.HasLength(1))
        self.assertEqual(200, m._periodic_spacing['bar'])

        # Now a single pass of the periodic tasks
        idle = m.run_periodic_tasks(None)
        self.assertAlmostEqual(60, idle, 1)

    def test_periodic_tasks_constant(self):
        class Manager(periodic_task.PeriodicTasks):

            @periodic_task.periodic_task(spacing=0)
            def bar(self):
                return 'bar'

        m = Manager(self.conf)
        idle = m.run_periodic_tasks(None)
        self.assertAlmostEqual(60, idle, 1)

    @mock.patch('oslo_service.periodic_task.now')
    def test_periodic_tasks_idle_calculation(self, mock_now):
        fake_time = 32503680000.0
        mock_now.return_value = fake_time

        class Manager(periodic_task.PeriodicTasks):

            @periodic_task.periodic_task(spacing=10)
            def bar(self, context):
                return 'bar'

        m = Manager(self.conf)

        # Ensure initial values are correct
        self.assertEqual(1, len(m._periodic_tasks))
        task_name, task = m._periodic_tasks[0]

        # Test task values
        self.assertEqual('bar', task_name)
        self.assertEqual(10, task._periodic_spacing)
        self.assertTrue(task._periodic_enabled)
        self.assertFalse(task._periodic_external_ok)
        self.assertFalse(task._periodic_immediate)
        self.assertAlmostEqual(32503680000.0,
                               task._periodic_last_run)

        # Test the manager's representation of those values
        self.assertEqual(10, m._periodic_spacing[task_name])
        self.assertAlmostEqual(32503680000.0,
                               m._periodic_last_run[task_name])

        mock_now.return_value = fake_time + 5
        idle = m.run_periodic_tasks(None)
        self.assertAlmostEqual(5, idle, 1)
        self.assertAlmostEqual(32503680000.0,
                               m._periodic_last_run[task_name])

        mock_now.return_value = fake_time + 10
        idle = m.run_periodic_tasks(None)
        self.assertAlmostEqual(10, idle, 1)
        self.assertAlmostEqual(32503680010.0,
                               m._periodic_last_run[task_name])

    @mock.patch('oslo_service.periodic_task.now')
    def test_periodic_tasks_immediate_runs_now(self, mock_now):
        fake_time = 32503680000.0
        mock_now.return_value = fake_time

        class Manager(periodic_task.PeriodicTasks):

            @periodic_task.periodic_task(spacing=10, run_immediately=True)
            def bar(self, context):
                return 'bar'

        m = Manager(self.conf)

        # Ensure initial values are correct
        self.assertEqual(1, len(m._periodic_tasks))
        task_name, task = m._periodic_tasks[0]

        # Test task values
        self.assertEqual('bar', task_name)
        self.assertEqual(10, task._periodic_spacing)
        self.assertTrue(task._periodic_enabled)
        self.assertFalse(task._periodic_external_ok)
        self.assertTrue(task._periodic_immediate)
        self.assertIsNone(task._periodic_last_run)

        # Test the manager's representation of those values
        self.assertEqual(10, m._periodic_spacing[task_name])
        self.assertIsNone(m._periodic_last_run[task_name])

        idle = m.run_periodic_tasks(None)
        self.assertAlmostEqual(32503680000.0,
                               m._periodic_last_run[task_name])
        self.assertAlmostEqual(10, idle, 1)

        mock_now.return_value = fake_time + 5
        idle = m.run_periodic_tasks(None)
        self.assertAlmostEqual(5, idle, 1)

    def test_periodic_tasks_disabled(self):
        class Manager(periodic_task.PeriodicTasks):

            @periodic_task.periodic_task(spacing=-1)
            def bar(self):
                return 'bar'

        m = Manager(self.conf)
        idle = m.run_periodic_tasks(None)
        self.assertAlmostEqual(60, idle, 1)

    def test_external_running_here(self):
        self.config(run_external_periodic_tasks=True)

        class Manager(periodic_task.PeriodicTasks):

            @periodic_task.periodic_task(spacing=200, external_process_ok=True)
            def bar(self):
                return 'bar'

        m = Manager(self.conf)
        self.assertThat(m._periodic_tasks, matchers.HasLength(1))

    @mock.patch('oslo_service.periodic_task.now')
    @mock.patch('random.random')
    def test_nearest_boundary(self, mock_random, mock_now):
        mock_now.return_value = 19
        mock_random.return_value = 0
        self.assertEqual(17, periodic_task._nearest_boundary(10, 7))
        mock_now.return_value = 28
        self.assertEqual(27, periodic_task._nearest_boundary(13, 7))
        mock_now.return_value = 1841
        self.assertEqual(1837, periodic_task._nearest_boundary(781, 88))
        mock_now.return_value = 1835
        self.assertEqual(mock_now.return_value,
                         periodic_task._nearest_boundary(None, 88))

        # Add 5% jitter
        mock_random.return_value = 1.0
        mock_now.return_value = 1300
        self.assertEqual(1200 + 10, periodic_task._nearest_boundary(1000, 200))
        # Add 2.5% jitter
        mock_random.return_value = 0.5
        mock_now.return_value = 1300
        self.assertEqual(1200 + 5, periodic_task._nearest_boundary(1000, 200))

    @mock.patch('oslo_service.periodic_task.backend.get_backend_type',
                return_value=backend.BackendType.THREADING)
    @mock.patch('oslo_service.periodic_task.now')
    def test_run_periodic_tasks_in_parallel_no_due_tasks_returns_idle(
            self, mock_now, mock_get_backend):
        """When no tasks are due, parallel runner returns idle."""
        mock_now.return_value = 1000.0

        class Manager(periodic_task.PeriodicTasks):
            @periodic_task.periodic_task(spacing=10, run_immediately=False)
            def task1(self, context):
                pass

        m = Manager(self.conf)
        with mock.patch.object(
                _multiprocessing, 'get_spawn_pool') as mock_get_pool:
            idle = m.run_periodic_tasks_in_parallel(None)
        mock_get_pool.assert_not_called()
        self.assertAlmostEqual(idle, 10, 1)

    @mock.patch('oslo_service.periodic_task.backend.get_backend_type',
                return_value=backend.BackendType.THREADING)
    @mock.patch('oslo_service.periodic_task.now')
    @mock.patch('oslo_service.periodic_task.ForkingPickler')
    def test_run_periodic_tasks_in_parallel_uses_get_spawn_pool(
            self, mock_fp, mock_now, mock_get_backend):
        """Verify run_periodic_tasks_in_parallel uses get_spawn_pool."""
        mock_now.return_value = 1000.0
        mock_fp.dumps.return_value = b''

        m = _PicklableManagerOneTask(self.conf)
        mock_pool_instance = mock.Mock()
        mock_pool_instance.apply_async.return_value.get.return_value = 'task1'
        mock_pool_instance.apply_async.return_value.ready.return_value = True
        with mock.patch.object(
                _multiprocessing, 'get_spawn_pool') as mock_get_pool:
            mock_get_pool.return_value = mock_pool_instance
            m.run_periodic_tasks_in_parallel(None)
        mock_get_pool.assert_called_once_with(processes=None)
        self.assertEqual(mock_pool_instance.apply_async.call_count, 1)
        mock_pool_instance.close.assert_called_once()
        mock_pool_instance.join.assert_called_once()

    def test_collect_async_task_results_drains_ready_out_of_submit_order(self):
        """Collect async results as they become ready, not in submit order.

        A task submitted later may finish first and is collected before
        earlier ones that are still pending.
        """
        r0 = mock.Mock()
        r0.ready.side_effect = [False, True]
        r0.get.return_value = None
        r1 = mock.Mock()
        r1.ready.return_value = True
        r1.get.return_value = None
        order = []

        def mark0(*a, **k):
            order.append('r0')

        def mark1(*a, **k):
            order.append('r1')

        r0.get.side_effect = mark0
        r1.get.side_effect = mark1
        with mock.patch('oslo_service.periodic_task.time.sleep') as mock_sleep:
            periodic_task._collect_async_task_results(
                [('t0', r0), ('t1', r1)], raise_on_error=False)
        self.assertEqual(['r1', 'r0'], order)
        mock_sleep.assert_called_once()

    @testtools.skipIf(
        'eventlet' in sys.modules,
        "Requires real OS threads; skip when eventlet is loaded "
        "(monkey-patches threading)")
    @mock.patch('oslo_service.periodic_task.backend.get_backend_type',
                return_value=backend.BackendType.THREADING)
    @mock.patch('oslo_service.periodic_task.now')
    def test_run_periodic_tasks_in_parallel_no_deadlock_when_thread_holds_lock(
            self, mock_now, mock_get_backend):
        """Schedule 10 tasks while a thread holds a lock; children exit clean.

        With fork, child processes would inherit the lock state and could
        deadlock. With spawn (get_spawn_pool), children are fresh processes
        and complete. Timeout completion proves no deadlock.
        """
        mock_now.return_value = 1000.0
        lock = threading.Lock()
        lock_holder_done = threading.Event()

        def hold_lock():
            lock.acquire()
            try:
                lock_holder_done.wait(timeout=30)
            finally:
                lock.release()

        m = _PicklableManagerTenTasks(_PicklableConf())
        self.assertEqual(10, len(m._periodic_tasks))

        lock_holder = threading.Thread(target=hold_lock)
        lock_holder.start()
        # Give the thread time to acquire the lock
        time.sleep(0.1)

        done = threading.Event()
        exc = []

        def run_parallel():
            try:
                m.run_periodic_tasks_in_parallel(None, processes=4)
            except Exception as e:
                exc.append(e)
            finally:
                done.set()

        runner = threading.Thread(target=run_parallel)
        runner.start()
        completed = done.wait(timeout=15)
        lock_holder_done.set()
        lock_holder.join(timeout=10)
        runner.join(timeout=10)

        self.assertTrue(
            completed,
            "run_periodic_tasks_in_parallel did not complete within 15s "
            "(possible fork deadlock)")
        self.assertEqual([], exc)

    @mock.patch('oslo_service.periodic_task.backend.get_backend_type',
                return_value=backend.BackendType.THREADING)
    def test_run_periodic_tasks_in_parallel_raises_when_context_not_picklable(
            self, mock_get_backend):
        """Raises with clear error when context is not picklable with spawn."""
        m = _PicklableManagerOneTask(self.conf)
        # Lambdas are not picklable with ForkingPickler
        non_picklable_context = lambda: None
        last_run_before = m._periodic_last_run['task1']
        self.assertRaises(
            (pickle.PicklingError, TypeError, AttributeError),
            m.run_periodic_tasks_in_parallel,
            non_picklable_context)
        self.assertEqual(last_run_before, m._periodic_last_run['task1'])

    @mock.patch('oslo_service.periodic_task.backend.get_backend_type',
                return_value=backend.BackendType.EVENTLET)
    def test_run_periodic_tasks_in_parallel_raises_with_eventlet_backend(
            self, mock_get_backend):
        """Raises when eventlet backend is active."""
        class Manager(periodic_task.PeriodicTasks):
            @periodic_task.periodic_task(spacing=10)
            def task1(self, context):
                pass

        m = Manager(self.conf)
        self.assertRaises(
            UnsupportedBackendError,
            m.run_periodic_tasks_in_parallel,
            None)
