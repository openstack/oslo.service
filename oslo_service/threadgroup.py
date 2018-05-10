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

import eventlet
from eventlet import greenpool

from oslo_service import loopingcall
from oslo_utils import timeutils

LOG = logging.getLogger(__name__)


def _on_thread_done(_greenthread, group, thread):
    """Callback function to be passed to GreenThread.link() when we spawn().

    Calls the :class:`ThreadGroup` to notify it to remove this thread from
    the associated group.
    """
    group.thread_done(thread)


class Thread(object):
    """Wrapper around a greenthread.

     Holds a reference to the :class:`ThreadGroup`. The Thread will notify
     the :class:`ThreadGroup` when it has done so it can be removed from
     the threads list.
    """
    def __init__(self, thread, group, link=True):
        self.thread = thread
        if link:
            self.thread.link(_on_thread_done, group, self)
        self._ident = id(thread)

    @property
    def ident(self):
        return self._ident

    def stop(self):
        self.thread.kill()

    def wait(self):
        return self.thread.wait()

    def link(self, func, *args, **kwargs):
        self.thread.link(func, *args, **kwargs)

    def cancel(self, *throw_args):
        self.thread.cancel(*throw_args)


class ThreadGroup(object):
    """The point of the ThreadGroup class is to:

    * keep track of timers and greenthreads (making it easier to stop them
      when need be).
    * provide an easy API to add timers.
    """
    def __init__(self, thread_pool_size=10):
        self.pool = greenpool.GreenPool(thread_pool_size)
        self.threads = []
        self.timers = []

    def add_dynamic_timer(self, callback, initial_delay=None,
                          periodic_interval_max=None, *args, **kwargs):
        timer = loopingcall.DynamicLoopingCall(callback, *args, **kwargs)
        timer.start(initial_delay=initial_delay,
                    periodic_interval_max=periodic_interval_max)
        self.timers.append(timer)
        return timer

    def add_timer(self, interval, callback, initial_delay=None,
                  *args, **kwargs):
        pulse = loopingcall.FixedIntervalLoopingCall(callback, *args, **kwargs)
        pulse.start(interval=interval,
                    initial_delay=initial_delay)
        self.timers.append(pulse)
        return pulse

    def add_thread(self, callback, *args, **kwargs):
        gt = self.pool.spawn(callback, *args, **kwargs)
        th = Thread(gt, self, link=False)
        self.threads.append(th)
        gt.link(_on_thread_done, self, th)
        return th

    def thread_done(self, thread):
        self.threads.remove(thread)

    def timer_done(self, timer):
        self.timers.remove(timer)

    def _perform_action_on_threads(self, action_func, on_error_func):
        current = threading.current_thread()
        # Iterate over a copy of self.threads so thread_done doesn't
        # modify the list while we're iterating
        for x in self.threads[:]:
            if x.ident == current.ident:
                # Don't perform actions on the current thread.
                continue
            try:
                action_func(x)
            except eventlet.greenlet.GreenletExit:  # nosec
                # greenlet exited successfully
                pass
            except Exception:
                on_error_func(x)

    def _stop_threads(self):
        self._perform_action_on_threads(
            lambda x: x.stop(),
            lambda x: LOG.exception('Error stopping thread.'))

    def stop_timers(self, wait=False):
        for timer in self.timers:
            timer.stop()
        if wait:
            self._wait_timers()
        self.timers = []

    def stop(self, graceful=False):
        """stop function has the option of graceful=True/False.

        * In case of graceful=True, wait for all threads to be finished.
          Never kill threads.
        * In case of graceful=False, kill threads immediately.
        """
        self.stop_timers(wait=graceful)
        if graceful:
            # In case of graceful=True, wait for all threads to be
            # finished, never kill threads
            self._wait_threads()
        else:
            # In case of graceful=False(Default), kill threads
            # immediately
            self._stop_threads()

    def _wait_timers(self):
        for x in self.timers:
            try:
                x.wait()
            except eventlet.greenlet.GreenletExit:  # nosec
                # greenlet exited successfully
                pass
            except Exception:
                LOG.exception('Error waiting on timer.')

    def _wait_threads(self):
        self._perform_action_on_threads(
            lambda x: x.wait(),
            lambda x: LOG.exception('Error waiting on thread.'))

    def wait(self):
        self._wait_timers()
        self._wait_threads()

    def _any_threads_alive(self):
        current = threading.current_thread()
        for x in self.threads[:]:
            if x.ident == current.ident:
                # Don't check current thread.
                continue
            if not x.thread.dead:
                return True
        return False

    def cancel(self, *throw_args, **kwargs):
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
