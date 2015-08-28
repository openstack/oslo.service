# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

import sys

from eventlet import event
from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import reflection
from oslo_utils import timeutils
import six

from oslo_service._i18n import _LE, _LW, _

LOG = logging.getLogger(__name__)


class LoopingCallDone(Exception):
    """Exception to break out and stop a LoopingCallBase.

    The poll-function passed to LoopingCallBase can raise this exception to
    break out of the loop normally. This is somewhat analogous to
    StopIteration.

    An optional return-value can be included as the argument to the exception;
    this return-value will be returned by LoopingCallBase.wait()

    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCallBase.wait() should return."""
        self.retvalue = retvalue


def _safe_wrapper(f, kind, func_name):
    """Wrapper that calls into wrapped function and logs errors as needed."""

    def func(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except LoopingCallDone:
            raise  # let the outer handler process this
        except Exception:
            LOG.error(_LE('%(kind)s %(func_name)r failed'),
                      {'kind': kind, 'func_name': func_name},
                      exc_info=True)
            return 0

    return func


class LoopingCallBase(object):
    _KIND = _("Unknown looping call")

    _RUN_ONLY_ONE_MESSAGE = _("A looping call can only run one function"
                              " at a time")

    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._running = False
        self._thread = None
        self.done = None

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()

    def _on_done(self, gt, *args, **kwargs):
        self._thread = None
        self._running = False

    def _start(self, idle_for, initial_delay=None, stop_on_exception=True):
        if self._thread is not None:
            raise RuntimeError(self._RUN_ONLY_ONE_MESSAGE)
        self._running = True
        self.done = event.Event()
        self._thread = greenthread.spawn(
            self._run_loop, self._KIND, self.done, idle_for,
            initial_delay=initial_delay, stop_on_exception=stop_on_exception)
        self._thread.link(self._on_done)
        return self.done

    def _run_loop(self, kind, event, idle_for_func,
                  initial_delay=None, stop_on_exception=True):
        func_name = reflection.get_callable_name(self.f)
        func = self.f if stop_on_exception else _safe_wrapper(self.f, kind,
                                                              func_name)
        if initial_delay:
            greenthread.sleep(initial_delay)
        try:
            watch = timeutils.StopWatch()
            while self._running:
                watch.restart()
                result = func(*self.args, **self.kw)
                watch.stop()
                if not self._running:
                    break
                idle = idle_for_func(result, watch.elapsed())
                LOG.trace('%(kind)s %(func_name)r sleeping '
                          'for %(idle).02f seconds',
                          {'func_name': func_name, 'idle': idle,
                           'kind': kind})
                greenthread.sleep(idle)
        except LoopingCallDone as e:
            event.send(e.retvalue)
        except Exception:
            exc_info = sys.exc_info()
            try:
                LOG.error(_LE('%(kind)s %(func_name)r failed'),
                          {'kind': kind, 'func_name': func_name},
                          exc_info=exc_info)
                event.send_exception(*exc_info)
            finally:
                del exc_info
            return
        else:
            event.send(True)


class FixedIntervalLoopingCall(LoopingCallBase):
    """A fixed interval looping call."""

    _RUN_ONLY_ONE_MESSAGE = _("A fixed interval looping call can only run"
                              " one function at a time")

    _KIND = _('Fixed interval looping call')

    def start(self, interval, initial_delay=None, stop_on_exception=True):
        def _idle_for(result, elapsed):
            delay = elapsed - interval
            if delay > 0:
                func_name = reflection.get_callable_name(self.f)
                LOG.warning(_LW('Function %(func_name)r run outlasted '
                                'interval by %(delay).2f sec'),
                            {'func_name': func_name, 'delay': delay})
            return -delay if delay < 0 else 0
        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class DynamicLoopingCall(LoopingCallBase):
    """A looping call which sleeps until the next known event.

    The function called should return how long to sleep for before being
    called again.
    """

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
                    # Note(suro-patz): An application used to receive a
                    #     TypeError thrown from eventlet layer, before
                    #     this RuntimeError was introduced.
                    raise RuntimeError(
                        self._TASK_MISSING_SLEEP_VALUE_MESSAGE)
            else:
                if periodic_interval_max is not None:
                    delay = min(delay, periodic_interval_max)
            return delay

        return self._start(_idle_for, initial_delay=initial_delay,
                           stop_on_exception=stop_on_exception)


class RetryDecorator(object):
    """Decorator for retrying a function upon suggested exceptions.

    The decorated function is retried for the given number of times, and the
    sleep time between the retries is incremented until max sleep time is
    reached. If the max retry count is set to -1, then the decorated function
    is invoked indefinitely until an exception is thrown, and the caught
    exception is not in the list of suggested exceptions.
    """

    def __init__(self, max_retry_count=-1, inc_sleep_time=10,
                 max_sleep_time=60, exceptions=()):
        """Configure the retry object using the input params.

        :param max_retry_count: maximum number of times the given function must
                                be retried when one of the input 'exceptions'
                                is caught. When set to -1, it will be retried
                                indefinitely until an exception is thrown
                                and the caught exception is not in param
                                exceptions.
        :param inc_sleep_time: incremental time in seconds for sleep time
                               between retries
        :param max_sleep_time: max sleep time in seconds beyond which the sleep
                               time will not be incremented using param
                               inc_sleep_time. On reaching this threshold,
                               max_sleep_time will be used as the sleep time.
        :param exceptions: suggested exceptions for which the function must be
                           retried, if no exceptions are provided (the default)
                           then all exceptions will be reraised, and no
                           retrying will be triggered.
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
                    LOG.warn(_LW("Exception which is in the suggested list of "
                                 "exceptions occurred while invoking function:"
                                 " %s."),
                             func_name,
                             exc_info=True)
                    if (self._max_retry_count != -1 and
                            self._retry_count >= self._max_retry_count):
                        LOG.error(_LE("Cannot retry %(func_name)s upon "
                                      "suggested exception "
                                      "since retry count (%(retry_count)d) "
                                      "reached max retry count "
                                      "(%(max_retry_count)d)."),
                                  {'retry_count': self._retry_count,
                                   'max_retry_count': self._max_retry_count,
                                   'func_name': func_name})
                    else:
                        ctxt.reraise = False
                        self._retry_count += 1
                        self._sleep_time += self._inc_sleep_time
                        return self._sleep_time
            raise LoopingCallDone(result)

        @six.wraps(f)
        def func(*args, **kwargs):
            loop = DynamicLoopingCall(_func, *args, **kwargs)
            evt = loop.start(periodic_interval_max=self._max_sleep_time)
            LOG.debug("Waiting for function %s to return.", func_name)
            return evt.wait()

        return func
