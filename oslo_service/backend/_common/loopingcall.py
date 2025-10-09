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

"""Common looping call functionality for both eventlet and threading
backends."""

import abc
import functools
import random
import sys
import time

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import reflection
from oslo_utils import timeutils

from oslo_service._i18n import _

LOG = logging.getLogger(__name__)


class LoopingCallDone(Exception):
    """Exception to break out and stop a LoopingCallBase.

    The poll-function passed to LoopingCallBase can raise this exception
    to break out of the loop normally. This is somewhat analogous to
    StopIteration.

    An optional return-value can be included as the argument to the
    exception; this return-value will be returned by
    LoopingCallBase.wait()
    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCallBase.wait() should return."""
        self.retvalue = retvalue


class LoopingCallTimeOut(Exception):
    """Exception for a timed out LoopingCall.

    The LoopingCall will raise this exception when a timeout is provided
    and it is exceeded.
    """
    pass


def _safe_wrapper(f, kind, func_name):
    """Wrapper that calls into wrapped function and logs errors as needed."""

    def func(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except LoopingCallDone:
            raise  # let the outer handler process this
        except Exception:
            LOG.error('%(kind)s %(func_name)r failed',
                      {'kind': kind, 'func_name': func_name},
                      exc_info=True)
            return 0

    return func


class LoopingCallBase(metaclass=abc.ABCMeta):
    """Base class for all looping call implementations."""

    _KIND = _("Unknown looping call")
    _RUN_ONLY_ONE_MESSAGE = _("A looping call can only run one function"
                              " at a time")

    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._thread = None
        self.done = None
        self._init_abort_mechanism()

    def _init_abort_mechanism(self):
        """Initialize the abort mechanism for the specific backend."""
        self._abort = self._get_abort_mechanism()

    @abc.abstractmethod
    def _get_abort_mechanism(self):
        """Return a new abort mechanism instance for the specific backend."""
        pass

    @property
    @abc.abstractmethod
    def _running(self):
        """Check if the looping call is currently running."""

    @abc.abstractmethod
    def stop(self):
        """Stop the looping call."""

    @abc.abstractmethod
    def wait(self):
        """Wait for the looping call to complete."""

    @abc.abstractmethod
    def _sleep(self, timeout):
        """Sleep for the given timeout."""

    @abc.abstractmethod
    def _create_done_event(self):
        """Create the appropriate done event for the backend."""

    @abc.abstractmethod
    def _spawn_loop(self, loop_func):
        """Spawn the loop function in the appropriate backend."""

    def _on_done(self, *args, **kwargs):
        """Callback when the loop is done."""
        self._thread = None

    def _start(self, idle_for, initial_delay=None, stop_on_exception=True):
        """Start the looping.

        :param idle_for: Callable that takes two positional arguments,
            returns how long to idle for. The first positional argument
            is the last result from the function being looped and the
            second positional argument is the time it took to calculate
            that result.
        :param initial_delay: How long to delay before starting the
            looping. Value is in seconds.
        :param stop_on_exception: Whether to stop if an exception
            occurs.
        :returns: Done event instance
        """
        if self._thread is not None:
            raise RuntimeError(self._RUN_ONLY_ONE_MESSAGE)

        self.done = self._create_done_event()
        self._clear_abort()

        def loop_func():
            self._run_loop(idle_for, initial_delay, stop_on_exception)

        self._thread = self._spawn_loop(loop_func)
        return self.done

    @abc.abstractmethod
    def _clear_abort(self):
        """Clear the abort flag."""

    def _run_loop(self, idle_for_func, initial_delay=None,
                  stop_on_exception=True):
        """Common loop implementation."""
        kind = self._KIND
        func_name = reflection.get_callable_name(self.f)
        func = (self.f if stop_on_exception
                else _safe_wrapper(self.f, kind, func_name))

        if initial_delay:
            self._sleep(initial_delay)

        try:
            watch = timeutils.StopWatch()
            while self._running:
                watch.restart()
                result = func(*self.args, **self.kw)
                watch.stop()
                if not self._running:
                    break
                idle = idle_for_func(result, self._elapsed(watch))
                LOG.trace('%(kind)s %(func_name)r sleeping '
                          'for %(idle).02f seconds',
                          {'func_name': func_name, 'idle': idle,
                           'kind': kind})
                self._sleep(idle)
        except LoopingCallDone as e:
            self._send_result(e.retvalue)
        except Exception:
            exc_info = sys.exc_info()
            try:
                LOG.error('%(kind)s %(func_name)r failed',
                          {'kind': kind, 'func_name': func_name},
                          exc_info=exc_info)
                self._send_exception(*exc_info)
            finally:
                del exc_info
            return
        else:
            self._send_result(True)

    @abc.abstractmethod
    def _send_result(self, result):
        """Send the result to the done event."""

    @abc.abstractmethod
    def _send_exception(self, exc_type, exc_value, tb):
        """Send an exception to the done event."""

    def _elapsed(self, watch):
        """Get elapsed time from watch."""
        return watch.elapsed()


class FixedIntervalLoopingCallBase(LoopingCallBase):
    """Base class for fixed interval looping calls."""

    _RUN_ONLY_ONE_MESSAGE = _("A fixed interval looping call can only run"
                              " one function at a time")
    _KIND = _('Fixed interval looping call')

    def start(self, interval, initial_delay=None, stop_on_exception=True):
        def _idle_for(result, elapsed):
            delay = round(elapsed - interval, 2)
            if delay > 0:
                func_name = reflection.get_callable_name(self.f)
                LOG.warning('Function %(func_name)r run outlasted '
                            'interval by %(delay).2f sec',
                            {'func_name': func_name, 'delay': delay})
            return -delay if delay < 0 else 0
        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class FixedIntervalWithTimeoutLoopingCallBase(LoopingCallBase):
    """Base class for fixed interval looping calls with timeout."""

    _RUN_ONLY_ONE_MESSAGE = _("A fixed interval looping call with timeout"
                              " checking and can only run one function at"
                              " at a time")
    _KIND = _('Fixed interval looping call with timeout checking.')

    def start(self, interval, initial_delay=None,
              stop_on_exception=True, timeout=0):
        start_time = time.time()

        def _idle_for(result, elapsed):
            delay = round(elapsed - interval, 2)
            if delay > 0:
                func_name = reflection.get_callable_name(self.f)
                LOG.warning('Function %(func_name)r run outlasted '
                            'interval by %(delay).2f sec',
                            {'func_name': func_name, 'delay': delay})
            elapsed_time = time.time() - start_time
            if timeout > 0 and elapsed_time > timeout:
                raise LoopingCallTimeOut(
                    _('Looping call timed out after %.02f seconds')
                    % elapsed_time)
            return -delay if delay < 0 else 0

        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class DynamicLoopingCallBase(LoopingCallBase):
    """Base class for dynamic looping calls."""

    _RUN_ONLY_ONE_MESSAGE = _("A dynamic interval looping call can only run"
                              " one function at a time")
    _TASK_MISSING_SLEEP_VALUE_MESSAGE = _(
        "A dynamic interval looping call should supply either an"
        " interval or periodic_interval_max"
    )
    _KIND = _('Dynamic interval looping call')

    def start(self, initial_delay=None, periodic_interval_max=None,
              stop_on_exception=True):
        def _idle_for(suggested_delay, elapsed):
            delay = suggested_delay
            if delay is None:
                if periodic_interval_max is not None:
                    delay = periodic_interval_max
                else:
                    raise RuntimeError(
                        self._TASK_MISSING_SLEEP_VALUE_MESSAGE)
            else:
                if periodic_interval_max is not None:
                    delay = min(delay, periodic_interval_max)
            return delay

        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class BackOffLoopingCallBase(LoopingCallBase):
    """Base class for backoff looping calls."""

    _RNG = random.SystemRandom()
    _KIND = _('Dynamic backoff interval looping call')
    _RUN_ONLY_ONE_MESSAGE = _("A dynamic backoff interval looping call can"
                              " only run one function at a time")

    def __init__(self, f=None, *args, **kw):
        super().__init__(f=f, *args, **kw)
        self._error_time = 0
        self._interval = 1

    def start(self, initial_delay=None, starting_interval=1, timeout=300,
              max_interval=300, jitter=0.75, min_interval=0.001):
        if self._thread is not None:
            raise RuntimeError(self._RUN_ONLY_ONE_MESSAGE)

        # Reset any prior state.
        self._error_time = 0
        self._interval = starting_interval

        def _idle_for(success, _elapsed):
            random_jitter = abs(self._RNG.gauss(jitter, 0.1))
            if success:
                # Reset error state now that it didn't error...
                self._interval = starting_interval
                self._error_time = 0
                return self._interval * random_jitter
            else:
                # Perform backoff, random jitter around the next interval
                # bounded by min_interval and max_interval.
                idle = max(self._interval * 2 * random_jitter, min_interval)
                idle = min(idle, max_interval)
                # Calculate the next interval based on the mean, so that the
                # backoff grows at the desired rate.
                self._interval = max(self._interval * 2 * jitter, min_interval)
                # Don't go over timeout, end early if necessary. If
                # timeout is 0, keep going.
                if timeout > 0 and self._error_time + idle > timeout:
                    raise LoopingCallTimeOut(
                        _('Looping call timed out after %.02f seconds')
                        % (self._error_time + idle))
                self._error_time += idle
                return idle

        return self._start(_idle_for, initial_delay=initial_delay)


class RetryDecorator:
    """Decorator for retrying a function upon suggested exceptions.

    The decorated function is retried for the given number of times, and
    the sleep time between the retries is incremented until max sleep
    time is reached. If the max retry count is set to -1, then the
    decorated function is invoked indefinitely until an exception is
    thrown, and the caught exception is not in the list of suggested
    exceptions.
    """

    def __init__(self, max_retry_count=-1, inc_sleep_time=10,
                 max_sleep_time=60, exceptions=()):
        """Configure the retry object using the input params.

        :param max_retry_count: maximum number of times the given
            function must be retried when one of the input 'exceptions'
            is caught. When set to -1, it will be retried indefinitely
            until an exception is thrown and the caught exception is not
            in param exceptions.
        :param inc_sleep_time: incremental time in seconds for sleep
            time between retries
        :param max_sleep_time: max sleep time in seconds beyond which
            the sleep time will not be incremented using param
            inc_sleep_time. On reaching this threshold, max_sleep_time
            will be used as the sleep time.
        :param exceptions: suggested exceptions for which the function
            must be retried, if no exceptions are provided (the default)
            then all exceptions will be reraised, and no retrying will
            be triggered.
        """
        self._max_retry_count = max_retry_count
        self._inc_sleep_time = inc_sleep_time
        self._max_sleep_time = max_sleep_time
        self._exceptions = exceptions
        self._retry_count = 0
        self._sleep_time = 0

    def __call__(self, f):
        func_name = reflection.get_callable_name(f)

        def _func(*args, **kwargs):
            result = None
            try:
                if self._retry_count:
                    LOG.debug("Invoking %(func_name)s; retry count is "
                              "%(retry_count)d.",
                              {'func_name': func_name,
                               'retry_count': self._retry_count})
                result = f(*args, **kwargs)
            except self._exceptions:
                with excutils.save_and_reraise_exception() as ctxt:
                    LOG.debug("Exception which is in the suggested list of "
                              "exceptions occurred while invoking function:"
                              " %s.",
                              func_name)
                    if (self._max_retry_count != -1 and
                            self._retry_count >= self._max_retry_count):
                        LOG.debug("Cannot retry %(func_name)s upon "
                                  "suggested exception "
                                  "since retry count (%(retry_count)d) "
                                  "reached max retry count "
                                  "(%(max_retry_count)d).",
                                  {'retry_count': self._retry_count,
                                   'max_retry_count': self._max_retry_count,
                                   'func_name': func_name})
                    else:
                        ctxt.reraise = False
                        self._retry_count += 1
                        self._sleep_time += self._inc_sleep_time
                        return self._sleep_time
            raise LoopingCallDone(result)

        @functools.wraps(f)
        def func(*args, **kwargs):
            loop = self._create_dynamic_looping_call(_func, *args, **kwargs)
            evt = loop.start(periodic_interval_max=self._max_sleep_time)
            LOG.debug("Waiting for function %s to return.", func_name)
            return evt.wait()

        return func

    @abc.abstractmethod
    def _create_dynamic_looping_call(self, func, *args, **kwargs):
        """Create a dynamic looping call instance for the specific backend."""
        pass
