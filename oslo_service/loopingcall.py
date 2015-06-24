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

import logging
import sys

from eventlet import event
from eventlet import greenthread
from oslo_utils import timeutils

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


class LoopingCallBase(object):
    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._running = False
        self.done = None

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()

    def _run_loop(self, kind, event, idle_for_func,
                  initial_delay=None):
        if initial_delay:
            greenthread.sleep(initial_delay)
        try:
            watch = timeutils.StopWatch()
            while self._running:
                watch.restart()
                result = self.f(*self.args, **self.kw)
                watch.stop()
                if not self._running:
                    break
                idle = idle_for_func(result, watch.elapsed())
                LOG.debug('%(kind)s %(func_name)r sleeping '
                          'for %(idle).02f seconds',
                          {'func_name': self.f, 'idle': idle,
                           'kind': kind})
                greenthread.sleep(idle)
        except LoopingCallDone as e:
            self.stop()
            event.send(e.retvalue)
        except Exception:
            exc_info = sys.exc_info()
            try:
                LOG.error(_LE('%(kind)s %(func_name)r failed'),
                          {'kind': kind, 'func_name': self.f},
                          exc_info=exc_info)
                event.send_exception(*exc_info)
            finally:
                del exc_info
            return
        else:
            event.send(True)


class FixedIntervalLoopingCall(LoopingCallBase):
    """A fixed interval looping call."""

    _KIND = _('Fixed interval looping call')

    def start(self, interval, initial_delay=None):

        def _idle_for(result, elapsed):
            delay = elapsed - interval
            if delay > 0:
                LOG.warning(_LW('Function %(func_name)r run outlasted '
                                'interval by %(delay).2f sec'),
                            {'func_name': self.f, 'delay': delay})
            return -delay if delay < 0 else 0

        self._running = True
        self.done = event.Event()
        greenthread.spawn_n(self._run_loop,
                            self._KIND, self.done, _idle_for,
                            initial_delay=initial_delay)
        return self.done


class DynamicLoopingCall(LoopingCallBase):
    """A looping call which sleeps until the next known event.

    The function called should return how long to sleep for before being
    called again.
    """

    _KIND = _('Dynamic interval looping call')

    def start(self, initial_delay=None, periodic_interval_max=None):

        def _idle_for(suggested_delay, elapsed):
            delay = suggested_delay
            if periodic_interval_max is not None:
                delay = min(delay, periodic_interval_max)
            return delay

        self._running = True
        self.done = event.Event()
        greenthread.spawn_n(self._run_loop,
                            self._KIND, self.done, _idle_for,
                            initial_delay=initial_delay)
        return self.done
