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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools
import random
import sys
import threading
import time

import futurist
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import reflection
from oslo_utils import timeutils

from oslo_service._i18n import _

LOG = logging.getLogger(__name__)


class LoopingCallDone(Exception):
    """Exception to break out and stop a LoopingCallBase.

    The function passed to a looping call may raise this exception to
    break out of the loop normally. An optional return value may be
    provided; this value will be returned by LoopingCallBase.wait().
    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCallBase.wait() should return."""
        self.retvalue = retvalue


class LoopingCallTimeOut(Exception):
    """Exception raised when a LoopingCall times out."""
    pass


class FutureEvent:
    """A simple event object that can carry a result or an exception."""

    def __init__(self):
        self._event = threading.Event()
        self._result = None
        self._exc_info = None

    def send(self, result):
        self._result = result
        self._event.set()

    def send_exception(self, exc_type, exc_value, tb):
        self._exc_info = (exc_type, exc_value, tb)
        self._event.set()

    def wait(self, timeout=None):
        flag = self._event.wait(timeout)

        if not flag:
            raise RuntimeError("Timed out waiting for event")

        if self._exc_info:
            exc_type, exc_value, tb = self._exc_info
            raise exc_value.with_traceback(tb)
        return self._result


def _safe_wrapper(f, kind, func_name):
    """Wrapper that calls the wrapped function and logs errors as needed."""

    def func(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except LoopingCallDone:
            raise  # Let the outer handler process this
        except Exception:
            LOG.error('%(kind)s %(func_name)r failed',
                      {'kind': kind, 'func_name': func_name},
                      exc_info=True)
            return 0

    return func


class LoopingCallBase:
    _KIND = _("Unknown looping call")
    _RUN_ONLY_ONE_MESSAGE = _(
        "A looping call can only run one function at a time")

    def __init__(self, f=None, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.f = f
        self._future = None
        self.done = None
        self._abort = threading.Event()  # When set, the loop stops

    @property
    def _running(self):
        return not self._abort.is_set()

    def stop(self):
        if self._running:
            self._abort.set()

    def wait(self):
        """Wait for the looping call to complete and return its result."""
        return self.done.wait()

    def _on_done(self, future):
        self._future = None

    def _sleep(self, timeout):
        # Instead of eventlet.sleep, we wait on the abort event for timeout
        # seconds.
        self._abort.wait(timeout)

    def _start(self, idle_for, initial_delay=None, stop_on_exception=True):
        """Start the looping call.

        :param idle_for: Callable taking two arguments (last result,
            elapsed time) and returning how long to idle.
        :param initial_delay: Delay (in seconds) before starting the
            loop.
        :param stop_on_exception: Whether to stop on exception.
        :returns: A FutureEvent instance.
        """

        if self._future is not None:
            raise RuntimeError(self._RUN_ONLY_ONE_MESSAGE)

        self.done = FutureEvent()
        self._abort.clear()

        def _run_loop():
            kind = self._KIND
            func_name = reflection.get_callable_name(self.f)
            func = self.f if stop_on_exception else _safe_wrapper(self.f, kind,
                                                                  func_name)
            if initial_delay:
                self._sleep(initial_delay)
            try:
                watch = timeutils.StopWatch()

                while self._running:
                    watch.restart()
                    result = func(*self.args, **self.kwargs)
                    watch.stop()

                    if not self._running:
                        break

                    idle = idle_for(result, watch.elapsed())
                    LOG.debug(
                        '%(kind)s %(func_name)r sleeping for %(idle).02f'
                        ' seconds',
                        {'func_name': func_name, 'idle': idle, 'kind': kind})
                    self._sleep(idle)
            except LoopingCallDone as e:
                self.done.send(e.retvalue)
            except Exception:
                exc_info = sys.exc_info()
                try:
                    LOG.error('%(kind)s %(func_name)r failed',
                              {'kind': kind, 'func_name': func_name},
                              exc_info=exc_info)
                    self.done.send_exception(*exc_info)
                finally:
                    del exc_info
                return
            else:
                self.done.send(True)

        # Use futurist's ThreadPoolExecutor to run the loop in a background
        # thread.
        executor = futurist.ThreadPoolExecutor(max_workers=1)
        self._future = executor.submit(_run_loop)
        self._future.add_done_callback(self._on_done)
        return self.done

    # NOTE: _elapsed() is a thin wrapper for StopWatch.elapsed()
    def _elapsed(self, watch):
        return watch.elapsed()


class FixedIntervalLoopingCall(LoopingCallBase):
    """A fixed interval looping call."""
    _RUN_ONLY_ONE_MESSAGE = _(
        "A fixed interval looping call can only run one function at a time")
    _KIND = _('Fixed interval looping call')

    def start(self, interval, initial_delay=None, stop_on_exception=True):
        def _idle_for(result, elapsed):
            delay = round(elapsed - interval, 2)
            if delay > 0:
                func_name = reflection.get_callable_name(self.f)
                LOG.warning(
                    'Function %(func_name)r run outlasted interval by'
                    ' %(delay).2f sec',
                    {'func_name': func_name, 'delay': delay})
            return -delay if delay < 0 else 0

        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class FixedIntervalWithTimeoutLoopingCall(LoopingCallBase):
    """A fixed interval looping call with timeout checking."""
    _RUN_ONLY_ONE_MESSAGE = _(
        "A fixed interval looping call with timeout checking"
        " can only run one function at a time")
    _KIND = _('Fixed interval looping call with timeout checking.')

    def start(self, interval, initial_delay=None, stop_on_exception=True,
              timeout=0):
        start_time = time.time()

        def _idle_for(result, elapsed):
            delay = round(elapsed - interval, 2)
            if delay > 0:
                func_name = reflection.get_callable_name(self.f)
                LOG.warning(
                    'Function %(func_name)r run outlasted interval by'
                    ' %(delay).2f sec',
                    {'func_name': func_name, 'delay': delay})
            elapsed_time = time.time() - start_time
            if timeout > 0 and elapsed_time > timeout:
                raise LoopingCallTimeOut(
                    _('Looping call timed out after %.02f seconds')
                    % elapsed_time)

            return -delay if delay < 0 else 0

        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class DynamicLoopingCall(LoopingCallBase):
    """A looping call which sleeps until the next known event.

    The function called should return how long to sleep before being
    called again.
    """

    _RUN_ONLY_ONE_MESSAGE = _(
        "A dynamic interval looping call can only run one function at a time")
    _TASK_MISSING_SLEEP_VALUE_MESSAGE = _(
        "A dynamic interval looping call should supply either an interval or"
        " periodic_interval_max"
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
                    raise RuntimeError(self._TASK_MISSING_SLEEP_VALUE_MESSAGE)
            else:
                if periodic_interval_max is not None:
                    delay = min(delay, periodic_interval_max)
            return delay

        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class BackOffLoopingCall(LoopingCallBase):
    """Run a method in a loop with backoff on error.

    The provided function should return True (indicating success, which resets
    the backoff interval), False (indicating an error, triggering a backoff),
    or raise LoopingCallDone(retvalue=...) to quit the loop.
    """

    _RNG = random.SystemRandom()
    _KIND = _('Dynamic backoff interval looping call')
    _RUN_ONLY_ONE_MESSAGE = _(
        "A dynamic backoff interval looping call can only run one function at"
        " a time")

    def __init__(self, f=None, *args, **kwargs):
        super().__init__(f=f, *args, **kwargs)
        self._error_time = 0
        self._interval = 1

    def start(self, initial_delay=None, starting_interval=1, timeout=300,
              max_interval=300, jitter=0.75, min_interval=0.001):
        if self._future is not None:
            raise RuntimeError(self._RUN_ONLY_ONE_MESSAGE)
        # Reset state.
        self._error_time = 0
        self._interval = starting_interval

        def _idle_for(success, _elapsed):
            random_jitter = abs(self._RNG.gauss(jitter, 0.1))
            if success:
                # Reset error state on success.
                self._interval = starting_interval
                self._error_time = 0
                return self._interval * random_jitter
            else:
                # Back off on error with jitter.
                idle = max(self._interval * 2 * random_jitter, min_interval)
                idle = min(idle, max_interval)
                self._interval = max(self._interval * 2 * jitter, min_interval)
                if timeout > 0 and self._error_time + idle > timeout:
                    raise LoopingCallTimeOut(
                        _('Looping call timed out after %.02f seconds') % (
                            self._error_time + idle))
                self._error_time += idle
                return idle

        return self._start(_idle_for, initial_delay=initial_delay)


class RetryDecorator:
    """Decorator for retrying a function upon suggested exceptions.

    The decorated function is retried for the given number of times,
    with an incrementally increasing sleep time between retries. A max
    sleep time may be set. If max_retry_count is -1, the function is
    retried indefinitely until an exception is raised that is not in the
    suggested exceptions.
    """

    def __init__(self, max_retry_count=-1, inc_sleep_time=10,
                 max_sleep_time=60, exceptions=()):
        """Document parameters for retry behavior.

        :param max_retry_count: Maximum number of retries for exceptions in
                                'exceptions'. -1 means retry indefinitely.
        :param inc_sleep_time: Incremental sleep time (seconds) between
                               retries.
        :param max_sleep_time: Maximum sleep time (seconds).
        :param exceptions: A tuple of exception types to catch for retries.
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
            try:
                if self._retry_count:
                    LOG.debug(
                        "Invoking %(func_name)s; retry count is"
                        " %(retry_count)d.",
                        {'func_name': func_name,
                         'retry_count': self._retry_count})
                result = f(*args, **kwargs)
            except self._exceptions:
                with excutils.save_and_reraise_exception() as ctxt:
                    LOG.debug(
                        "Exception in %(func_name)s occurred which is in the"
                        " retry list.",
                        {'func_name': func_name})
                    if (self._max_retry_count != -1 and
                            self._retry_count >= self._max_retry_count):
                        LOG.debug(
                            "Cannot retry %(func_name)s because retry count"
                            " (%(retry_count)d) reached max"
                            " (%(max_retry_count)d).",
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
            loop = DynamicLoopingCall(_func, *args, **kwargs)
            evt = loop.start(periodic_interval_max=self._max_sleep_time)
            LOG.debug("Waiting for function %s to return.", func_name)

            return evt.wait()

        return func
