# Copyright (C) 2026 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Functional regression tests for fork-safety in oslo.service.

These tests cover the regression class where oslo.service accidentally falls
back from spawn to fork while other threads are already running. Forking a
multi-threaded process is unsafe because the child inherits locked process
state but not the thread that owns or can release those locks. If fork
semantics are reintroduced here, these tests should either fail the explicit
spawn-context assertions or time out on the bounded worker/launcher waits.

The test targets must stay at module scope because multiprocessing spawn starts
fresh Python interpreters and imports callables by module path.

Run via: tox -e py313-threading

Note: When running outside tox (e.g., stestr run), you must manually set
OSLO_SERVICE_SKIP_EVENTLET=1 to disable eventlet monkey-patching.
"""

import logging
import multiprocessing
import os
import queue
import tempfile
import threading
import time
import unittest
import warnings

from oslo_config import cfg

from oslo_service import _multiprocessing
from oslo_service.backend.base import ServiceBase


def _eventlet_is_monkey_patched():
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import eventlet.patcher
    except ImportError:
        return False
    return (
        eventlet.patcher.is_monkey_patched('os') or
        eventlet.patcher.is_monkey_patched('thread')
    )


# Skip only when eventlet has actually monkey-patched the interpreter. Merely
# importing eventlet does not by itself break spawn-based multiprocessing.
EVENTLET_MONKEY_PATCHED = _eventlet_is_monkey_patched()

# Module-level logger
LOG = logging.getLogger(__name__)

_SERVICE_STARTED = 'service-started'
_SERVICE_STOPPED = 'service-stopped'
_LAUNCHER_DONE = 'launcher-done'
_ERROR = 'error'


def simple_worker(x):
    """Simple importable worker function for spawn pool tests."""
    return x * 2


def _cleanup_pool(pool, succeeded):
    if succeeded:
        pool.close()
    else:
        pool.terminate()
    _join_pool_with_timeout(pool)


def _join_pool_with_timeout(pool, timeout=10):
    """Join pool with timeout. Pool.join() has no timeout, so use a thread.

    :param pool: The pool to join
    :param timeout: Maximum seconds to wait (default 10)
    :raises AssertionError: If join doesn't complete within timeout
    """
    join_completed = threading.Event()

    def _do_join():
        pool.join()
        join_completed.set()

    joiner = threading.Thread(target=_do_join, daemon=True)
    joiner.start()

    if not join_completed.wait(timeout=timeout):
        raise AssertionError(
            f"pool.join() did not complete within {timeout}s - "
            "possible worker hang or deadlock"
        )


class MinimalLauncherService(ServiceBase):
    """Minimal picklable service for ServiceLauncher spawn regression tests."""

    def __init__(self, status_dir):
        super().__init__()
        self.status_dir = status_dir

    def start(self):
        with open(os.path.join(self.status_dir, _SERVICE_STARTED), 'w') as f:
            f.write(str(os.getpid()))

    def stop(self, graceful=False):
        pass

    def wait(self):
        time.sleep(0.2)
        with open(os.path.join(self.status_dir, _SERVICE_STOPPED), 'w') as f:
            f.write(str(os.getpid()))

    def reset(self):
        pass


def _wait_for_marker(path, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


def _run_minimal_service_launcher_with_active_thread(status_queue):
    """Launch a ServiceLauncher worker while another thread holds a lock.

    The important assertion is that ServiceLauncher selects the spawn context.
    If oslo.service regresses to fork, the child process would be
    created from a process with an active background thread. That can inherit
    locked state without the owning thread and is exactly the unsafe pattern
    this functional regression test guards against.

    Cotyledon's ServiceManager.run() handles signals most reliably from the
    main thread, so a control thread waits for worker markers and stops the
    launcher while the main thread runs launcher.wait().
    """
    from oslo_service.backend._threading import service as threading_service

    lock = threading.Lock()
    lock_acquired = threading.Event()
    release_lock = threading.Event()
    launcher = None
    controller = None
    controller_errors = []

    def background_task():
        with lock:
            lock_acquired.set()
            release_lock.wait(timeout=5)

    background = threading.Thread(target=background_task, daemon=True)
    background.start()

    try:
        if not lock_acquired.wait(timeout=2):
            raise RuntimeError("background thread did not acquire test lock")

        with tempfile.TemporaryDirectory() as status_dir:
            started_path = os.path.join(status_dir, _SERVICE_STARTED)
            stopped_path = os.path.join(status_dir, _SERVICE_STOPPED)

            conf = cfg.ConfigOpts()
            launcher = threading_service.ServiceLauncher(conf=conf)
            launcher.launch_service(
                MinimalLauncherService(status_dir), workers=1)

            if launcher._manager_context.get_start_method() != 'spawn':
                raise RuntimeError(
                    "ServiceLauncher fell back from spawn context; this "
                    "would reintroduce fork-with-active-threads semantics")

            def stop_after_worker_finishes():
                try:
                    if not _wait_for_marker(started_path, timeout=5):
                        raise RuntimeError(
                            "ServiceLauncher worker did not start")
                    status_queue.put((_SERVICE_STARTED, os.getpid()))

                    if not _wait_for_marker(stopped_path, timeout=5):
                        raise RuntimeError(
                            "ServiceLauncher worker did not stop")
                    status_queue.put((_SERVICE_STOPPED, os.getpid()))

                    launcher.stop()
                except Exception as exc:
                    controller_errors.append(exc)
                    status_queue.put((_ERROR, repr(exc)))
                    try:
                        launcher.stop()
                    except Exception:
                        LOG.exception("Failed to stop ServiceLauncher")

            controller = threading.Thread(target=stop_after_worker_finishes)
            controller.start()
            exit_code = launcher.wait()
            controller.join(timeout=5)
            if controller.is_alive():
                raise RuntimeError("ServiceLauncher controller did not exit")
            if controller_errors:
                raise controller_errors[0]
            if exit_code not in (0, None):
                raise RuntimeError(
                    f"ServiceLauncher exited with status {exit_code}")

            status_queue.put((_LAUNCHER_DONE, os.getpid()))
    except Exception as exc:
        status_queue.put((_ERROR, repr(exc)))
    finally:
        release_lock.set()
        if launcher is not None and controller is not None:
            controller.join(timeout=3)
        background.join(timeout=3)


@unittest.skipIf(EVENTLET_MONKEY_PATCHED,
                 "Spawn-safety tests cannot run with eventlet monkey-patching")
class TestForkSafetyRegression(unittest.TestCase):
    """Functional spawn/fork-safety regression coverage.

    Skipped only if eventlet has monkey-patched the interpreter.
    """

    def test_spawn_context_is_spawn(self):
        """Verify get_spawn_context returns spawn start method."""
        ctx = _multiprocessing.get_spawn_context()
        self.assertEqual('spawn', ctx.get_start_method())
        self.assertIsInstance(ctx, multiprocessing.context.SpawnContext)

    def test_spawn_pool_executes_simple_task(self):
        """Verify spawn pool can execute a simple task."""
        pool = _multiprocessing.get_spawn_pool(processes=1)
        succeeded = False
        try:
            result = pool.apply_async(simple_worker, (5,))
            value = result.get(timeout=5)
            self.assertEqual(10, value)
            succeeded = True
        finally:
            _cleanup_pool(pool, succeeded)

    def test_spawn_pool_completes_with_active_thread(self):
        """Spawn pool completes while a background thread is active.

        A fork-based implementation may inherit locks held by vanished threads;
        the bounded wait below should fail if fork semantics are reintroduced.
        """
        completed = threading.Event()
        results = []
        error = []

        def background_task():
            for _ in range(10):
                LOG.info("Background thread active")
                time.sleep(0.1)

        def run_pool_test():
            try:
                # Start background thread
                t = threading.Thread(target=background_task)
                t.daemon = True
                t.start()

                # Give thread time to start
                time.sleep(0.05)

                # Create and use spawn pool
                pool = _multiprocessing.get_spawn_pool(processes=2)
                succeeded = False
                try:
                    # Submit tasks
                    async_results = []
                    for i in range(5):
                        result = pool.apply_async(simple_worker, (i,))
                        async_results.append(result)

                    # Get results
                    for r in async_results:
                        results.append(r.get(timeout=3))
                    succeeded = True
                finally:
                    _cleanup_pool(pool, succeeded)

            except Exception as e:
                error.append(e)
            finally:
                completed.set()

        # Run test in thread with timeout
        runner = threading.Thread(target=run_pool_test)
        runner.start()
        success = completed.wait(timeout=10)
        runner.join(timeout=2)

        # Verify
        self.assertTrue(
            success,
            "Pool operations did not complete within 10s - possible deadlock!")
        self.assertEqual([], error, f"Errors occurred: {error}")
        self.assertEqual([0, 2, 4, 6, 8], results)

    def test_service_launcher_spawn_does_not_deadlock_with_active_thread(self):
        """ServiceLauncher starts a spawn worker with an active thread.

        This regression is not generic multiprocessing behavior.
        It is accidental fallback in oslo.service's launcher path. The child
        process fails fast if ServiceLauncher selects anything other than
        spawn, and all waits are bounded so fork-related hangs surface as test
        failures.
        """
        ctx = _multiprocessing.get_spawn_context()
        status_queue = ctx.Queue()
        proc = ctx.Process(
            target=_run_minimal_service_launcher_with_active_thread,
            args=(status_queue,))
        messages = []

        try:
            proc.start()
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    message = status_queue.get(timeout=0.2)
                    messages.append(message)
                    if message[0] in (_ERROR, _LAUNCHER_DONE):
                        break
                except queue.Empty:
                    if not proc.is_alive():
                        break

            proc.join(timeout=5)
            if proc.is_alive():
                self.fail(
                    "ServiceLauncher spawn test service did not "
                    f"exit cleanly: {messages}")
        finally:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=3)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=3)

            while True:
                try:
                    messages.append(status_queue.get_nowait())
                except queue.Empty:
                    break

            status_queue.cancel_join_thread()
            status_queue.close()

        self.assertEqual(
            0, proc.exitcode,
            f"ServiceLauncher test service failed: {messages}")
        self.assertNotIn(
            _ERROR, [message[0] for message in messages],
            f"ServiceLauncher regression error: {messages}")
        self.assertIn(_SERVICE_STARTED, [message[0] for message in messages])
        self.assertIn(_SERVICE_STOPPED, [message[0] for message in messages])
        self.assertIn(_LAUNCHER_DONE, [message[0] for message in messages])
