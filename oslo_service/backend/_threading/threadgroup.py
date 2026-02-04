# Copyright (C) 2025 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import logging
import threading

from oslo_service.backend._common import threadgroup
from oslo_service.backend._threading import loopingcall

LOG = logging.getLogger(__name__)


class Thread(threadgroup.ThreadBase):
    """A simple wrapper around native threads.

    This class mimics the eventlet Thread interface (stop, wait, link,
    cancel) for compatibility with oslo.service consumers. The methods
    `stop`, `link`, and `cancel` are implemented as no-ops in the threading
    backend since native Python threads do not support these operations
    natively.
    """

    def stop(self):
        # Native threads cannot be forcefully stopped
        pass

    def wait(self):
        self.thread.join()

    def link(self, func, *args, **kwargs):
        # Native threads don't support linking
        pass

    def cancel(self, *throw_args):
        # Native threads cannot be cancelled
        pass


class ThreadGroup(threadgroup.ThreadGroupBase):
    """A group of threads and timers similar to eventlet's GreenPool."""

    def __init__(self, max_threads=1000):
        super().__init__(thread_pool_size=max_threads)
        self._lock = threading.Lock()

    def _create_fixed_timer(self, callback, args, kwargs):
        """Create a fixed interval timer for threading backend."""
        return loopingcall.FixedIntervalLoopingCall(callback, *args, **kwargs)

    def _create_dynamic_timer(self, callback, args, kwargs):
        """Create a dynamic interval timer for threading backend."""
        return loopingcall.DynamicLoopingCall(callback, *args, **kwargs)

    def add_thread(self, callback, *args, **kwargs):
        """Add a new thread to the group.

        :param callback: The function to run in the thread
        :param args: Positional arguments for the callback
        :param kwargs: Keyword arguments for the callback
        :returns: A Thread object wrapping the new thread
        :raises RuntimeError: If max_threads limit is reached
        """
        def run_and_cleanup(*cb_args, **cb_kwargs):
            try:
                callback(*cb_args, **cb_kwargs)
            finally:
                self.thread_done(threading.current_thread())

        with self._lock:
            if len(self.threads) >= self.thread_pool_size:
                raise RuntimeError("Maximum number of threads reached")

            t = threading.Thread(
                target=run_and_cleanup, args=args, kwargs=kwargs)
            t.args = args
            t.kw = kwargs

            self.threads.append(t)

        t.start()
        return Thread(t, group=self)

    def thread_done(self, thread):
        """Remove a completed thread from the group.

        This method is automatically called on completion of a thread in
        the group, and should not be called explicitly.
        """
        with self._lock:
            try:
                self.threads.remove(thread)
            except ValueError:
                pass

    def _stop_threads(self):
        """Stop all threads in the group.

        Note: Native threads cannot be forcefully stopped, so this is a no-op
        in the threading backend.
        """
        current = threading.current_thread()
        with self._lock:
            for t in self.threads:
                if t is not current and hasattr(t, "abort"):
                    t.abort.set()
            self.threads = [t for t in self.threads if t is current]

    def _wait_threads(self):
        """Wait for all threads to complete."""
        current = threading.current_thread()
        with self._lock:
            threads_copy = list(self.threads)
        for t in threads_copy:
            if t is not current:
                try:
                    t.join()
                except Exception:
                    LOG.exception('Error waiting on thread.')

    def _perform_action_on_threads(self, action_func, on_error_func,
                                   skip_current=True):
        """Helper to perform an action on all threads.

        :param action_func: Function to call on each thread
        :param on_error_func: Function to call if action raises exception
        :param skip_current: Skip the current thread if True
        """
        current = threading.current_thread()
        with self._lock:
            # Copy list to avoid modification during iteration
            for thread in self.threads[:]:
                if skip_current and thread is current:
                    continue
                try:
                    action_func(thread)
                except Exception:
                    on_error_func(thread)

    def waitall(self):
        """Block until all timers and threads in the group are complete."""
        with self._lock:
            threads_copy = list(self.threads)
            timers_copy = list(self.timers)

        for t in threads_copy:
            t.join()

        for timer in timers_copy:
            timer.wait()

    # NOTE(tkajinam): To keep interface consistent with eventlet version
    wait = waitall
