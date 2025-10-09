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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Common thread group functionality for both eventlet and threading
backends."""

import abc
import logging
import threading
import warnings

LOG = logging.getLogger(__name__)


class ThreadBase(metaclass=abc.ABCMeta):
    """Base class for thread wrappers.

    This provides a common interface for both eventlet and threading
    implementations of Thread objects.
    """

    def __init__(self, thread, group=None):
        self.thread = thread
        self._ident = getattr(thread, 'ident', id(thread))
        self.group = group

    @property
    def ident(self):
        """Return a unique identifier for the thread."""
        return self._ident

    @abc.abstractmethod
    def stop(self):
        """Stop the thread if possible.

        Note: Not all implementations support stopping threads.
        Threading backend implements this as a no-op.
        """

    @abc.abstractmethod
    def wait(self):
        """Wait for thread completion."""

    @abc.abstractmethod
    def link(self, func, *args, **kwargs):
        """Link a callback to thread completion.

        Note: Not all implementations support linking callbacks.
        Threading backend implements this as a no-op.
        """

    @abc.abstractmethod
    def cancel(self, *throw_args):
        """Cancel thread if possible.

        Note: Not all implementations support cancellation.
        Threading backend implements this as a no-op.
        """


class TimerMixin:
    """Common timer management functionality.

    This mixin provides common methods for managing timer objects
    in thread groups.
    """

    def add_timer_args(self, interval, callback, args=None, kwargs=None,
                       initial_delay=None, stop_on_exception=True):
        """Add a timer with fixed interval.

        :param interval: The interval in seconds between calls
        :param callback: The function to call
        :param args: Positional args for the callback
        :param kwargs: Keyword args for the callback
        :param initial_delay: Seconds to wait before first call
        :param stop_on_exception: Whether to stop on callback exception
        """
        args = args or []
        kwargs = kwargs or {}
        pulse = self._create_fixed_timer(callback, args, kwargs)
        pulse.start(interval=interval,
                    initial_delay=initial_delay,
                    stop_on_exception=stop_on_exception)
        with self._lock:
            self.timers.append(pulse)
        return pulse

    def add_timer(self, interval, callback, initial_delay=None,
                  *args, **kwargs):
        """Legacy method for adding a timer.

        .. warning::
            Passing arguments to the callback function is deprecated. Use
            add_timer_args() instead.
        """
        if args or kwargs:
            warnings.warn(
                "Calling add_timer() with arguments is deprecated. Use "
                "add_timer_args() instead.",
                DeprecationWarning
            )
        return self.add_timer_args(
            interval, callback, list(args), kwargs,
            initial_delay=initial_delay)

    def add_dynamic_timer_args(self, callback, args=None, kwargs=None,
                               initial_delay=None, periodic_interval_max=None,
                               stop_on_exception=True):
        """Add a timer that controls its own interval.

        :param callback: The function to call
        :param args: Positional args for the callback
        :param kwargs: Keyword args for the callback
        :param initial_delay: Seconds to wait before first call
        :param periodic_interval_max: Maximum interval between calls
        :param stop_on_exception: Whether to stop on callback exception
        """
        args = args or []
        kwargs = kwargs or {}
        timer = self._create_dynamic_timer(callback, args, kwargs)
        timer.start(initial_delay=initial_delay,
                    periodic_interval_max=periodic_interval_max,
                    stop_on_exception=stop_on_exception)
        with self._lock:
            self.timers.append(timer)
        return timer

    def add_dynamic_timer(self, callback, initial_delay=None,
                          periodic_interval_max=None, *args, **kwargs):
        """Legacy method for adding a dynamic timer.

        .. warning::
            Passing arguments to the callback function is deprecated. Use
            add_dynamic_timer_args() instead.
        """
        if args or kwargs:
            warnings.warn(
                "Calling add_dynamic_timer() with arguments is deprecated. "
                "Use add_dynamic_timer_args() instead.",
                DeprecationWarning
            )
        return self.add_dynamic_timer_args(
            callback, list(args), kwargs,
            initial_delay=initial_delay,
            periodic_interval_max=periodic_interval_max)

    @abc.abstractmethod
    def _create_fixed_timer(self, callback, args, kwargs):
        """Create a fixed interval timer instance.

        Must be implemented by concrete classes to return the appropriate
        FixedIntervalLoopingCall instance for their backend.
        """

    @abc.abstractmethod
    def _create_dynamic_timer(self, callback, args, kwargs):
        """Create a dynamic interval timer instance.

        Must be implemented by concrete classes to return the appropriate
        DynamicLoopingCall instance for their backend.
        """


class ThreadGroupBase(TimerMixin):
    """Base class for thread group implementations.

    This provides common functionality for managing threads and timers
    that is shared between the eventlet and threading backends.
    """

    def __init__(self, thread_pool_size=10):
        self.threads = []
        self.timers = []
        self._lock = threading.Lock()
        self.thread_pool_size = thread_pool_size

    def timer_done(self, timer):
        """Remove a timer from the group."""
        with self._lock:
            try:
                self.timers.remove(timer)
            except ValueError:
                pass

    def stop_timers(self, wait=False):
        """Stop all timers in the group.

        :param wait: If True, wait for timer callbacks to complete
        """
        with self._lock:
            for timer in self.timers:
                timer.stop()
            if wait:
                self._wait_timers()
            self.timers = []

    def _wait_timers(self):
        """Wait for all timers to complete."""
        for timer in self.timers:
            try:
                timer.wait()
            except Exception:
                LOG.exception('Error waiting on timer.')

    def stop(self, graceful=False):
        """Stop all timers and threads.

        :param graceful: If True, wait for completion before returning
        """
        self.stop_timers(wait=graceful)
        if graceful:
            self._wait_threads()
        else:
            self._stop_threads()

    @abc.abstractmethod
    def _stop_threads(self):
        """Stop all threads in the group.

        Implementation depends on the backend's thread implementation.
        """

    @abc.abstractmethod
    def _wait_threads(self):
        """Wait for all threads to complete.

        Implementation depends on the backend's thread implementation.
        """

    @abc.abstractmethod
    def _perform_action_on_threads(self, action_func, on_error_func,
                                   skip_current=True):
        """Helper to perform an action on all threads.

        :param action_func: Function to call on each thread
        :param on_error_func: Function to call if action raises exception
        :param skip_current: Skip the current thread if True
        """
        pass

    def wait(self):
        """Wait for all timers and threads in the group to complete.

        .. note::
            Before calling this method, any timers should be stopped first by
            calling stop_timers, stop, or cancel with a timeout argument.
            Otherwise this will block forever.

        .. note::
            Calling stop_timers removes the timers from the group, so a
            subsequent call to this method will not wait for any in-progress
            timer calls to complete.

        Any exceptions raised by the threads will be logged but suppressed.

        .. note::
            This call guarantees only that the threads themselves have
            completed, **not** that any cleanup functions added via
            Thread.link have completed.
        """
        self._wait_timers()
        self._wait_threads()
