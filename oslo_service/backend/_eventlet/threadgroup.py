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


import logging
import threading

from debtcollector import removals
import eventlet
from eventlet import greenlet
from eventlet import greenpool
from oslo_utils import timeutils

from oslo_service.backend._common import threadgroup
from oslo_service.backend._eventlet import loopingcall

LOG = logging.getLogger(__name__)


def _on_thread_done(_greenthread, group, thread):
    """Callback function to be passed to GreenThread.link() when we spawn().

    Calls the :class:`ThreadGroup` to notify it to remove this thread from
    the associated group.
    """
    group.thread_done(thread)


class Thread(threadgroup.ThreadBase):
    """Wrapper around a greenthread.

    Holds a reference to the :class:`ThreadGroup`. The Thread will notify
    the :class:`ThreadGroup` when it has done so it can be removed from
    the threads list.
    """
    def __init__(self, thread, group, link=True):
        super().__init__(thread, group)
        if link:
            self.thread.link(_on_thread_done, group, self)

    def stop(self):
        """Kill the thread by raising GreenletExit within it."""
        self.thread.kill()

    def wait(self):
        """Block until the thread completes."""
        return self.thread.wait()

    def link(self, func, *args, **kwargs):
        self.thread.link(func, *args, **kwargs)

    def cancel(self, *throw_args):
        self.thread.cancel(*throw_args)


class ThreadGroup(threadgroup.ThreadGroupBase):
    """A group of greenthreads and timers.

    The point of the ThreadGroup class is to:

    * keep track of timers and greenthreads (making it easier to stop them
      when need be).
    * provide an easy API to add timers.
    """

    def __init__(self, thread_pool_size=10):
        super().__init__(thread_pool_size)
        self.pool = greenpool.GreenPool(self.thread_pool_size)

    def _create_fixed_timer(self, callback, args, kwargs):
        """Create a fixed interval timer for eventlet backend."""
        return loopingcall.FixedIntervalLoopingCall(callback, *args, **kwargs)

    def _create_dynamic_timer(self, callback, args, kwargs):
        """Create a dynamic interval timer for eventlet backend."""
        return loopingcall.DynamicLoopingCall(callback, *args, **kwargs)

    def add_thread(self, callback, *args, **kwargs):
        """Spawn a new thread.

        This call will block until capacity is available in the thread pool.
        After that, it returns immediately (i.e. *before* the new thread is
        scheduled).

        :param callback: the function to run in the new thread.
        :param args: positional arguments to the callback function.
        :param kwargs: keyword arguments to the callback function.
        :returns: a :class:`Thread` object
        """
        gt = self.pool.spawn(callback, *args, **kwargs)
        th = Thread(gt, self, link=False)
        self.threads.append(th)
        gt.link(_on_thread_done, self, th)
        return th

    def thread_done(self, thread):
        """Remove a completed thread from the group.

        This method is automatically called on completion of a thread in
        the group, and should not be called explicitly.
        """
        self.threads.remove(thread)

    def _stop_threads(self):
        self._perform_action_on_threads(
            lambda x: x.stop(),
            lambda x: LOG.exception('Error stopping thread.'))

    def _wait_threads(self):
        """Wait for all threads to complete.

        Note: This implementation handles GreenletExit exceptions
        which are raised when a greenlet is killed.
        """
        def _safe_wait(thread):
            try:
                thread.wait()
            except greenlet.GreenletExit:
                # This is expected when killing a greenlet
                pass
            except Exception:
                LOG.exception('Error waiting on thread.')

        self._perform_action_on_threads(
            _safe_wait,
            lambda x: LOG.exception('Error waiting on thread.'))

    def _perform_action_on_threads(self, action_func, on_error_func,
                                   skip_current=True):
        """Helper to perform an action on all threads.

        :param action_func: Function to call on each thread
        :param on_error_func: Function to call if action raises exception
        :param skip_current: Skip the current thread if True
        """
        current = threading.current_thread()
        # Copy list to avoid modification during iteration
        for thread in self.threads[:]:
            if skip_current and thread.ident == current.ident:
                continue
            try:
                action_func(thread)
            except greenlet.GreenletExit:
                # greenlet exited successfully
                pass
            except Exception:
                on_error_func(thread)

    def _any_threads_alive(self):
        current = threading.current_thread()
        for x in self.threads[:]:
            if x.ident == current.ident:
                # Don't check current thread.
                continue
            if not x.thread.dead:
                return True
        return False

    @removals.remove(removal_version='?')
    def cancel(self, *throw_args, **kwargs):
        """Cancel unstarted threads in the group.

        .. warning::
            This method is deprecated and should not be used.
        """
        self._perform_action_on_threads(
            lambda x: x.cancel(*throw_args),
            lambda x: LOG.exception('Error canceling thread.'))

        timeout = kwargs.get('timeout', None)
        if timeout is None:
            return
        wait_time = kwargs.get('wait_time', 1)

        watch = timeutils.StopWatch(duration=timeout)
        watch.start()
        while self._any_threads_alive():
            if not watch.expired():
                eventlet.sleep(wait_time)
                continue
            LOG.debug("Cancel timeout reached, stopping threads.")
            self.stop()
