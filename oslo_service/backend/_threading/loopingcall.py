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

import threading

import futurist
from oslo_log import log as logging

from oslo_service.backend._common import loopingcall

LOG = logging.getLogger(__name__)

# Re-export common classes and exceptions
LoopingCallDone = loopingcall.LoopingCallDone
LoopingCallTimeOut = loopingcall.LoopingCallTimeOut


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


class LoopingCallBase(loopingcall.LoopingCallBase):
    """Threading-specific implementation of LoopingCallBase."""

    def _get_abort_mechanism(self):
        """Return a new abort mechanism instance."""
        return threading.Event()

    def _create_done_event(self):
        return FutureEvent()

    def _spawn_loop(self, loop_func):
        executor = futurist.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(loop_func)
        future.add_done_callback(self._on_done)
        return future


class FixedIntervalLoopingCall(
        loopingcall.FixedIntervalLoopingCallBase,
        LoopingCallBase):
    """A fixed interval looping call for threading backend."""
    pass


class FixedIntervalWithTimeoutLoopingCall(
        loopingcall.FixedIntervalWithTimeoutLoopingCallBase,
        LoopingCallBase):
    """A fixed interval looping call with timeout for threading backend."""
    pass


class DynamicLoopingCall(loopingcall.DynamicLoopingCallBase, LoopingCallBase):
    """A dynamic looping call for threading backend."""
    pass


class BackOffLoopingCall(loopingcall.BackOffLoopingCallBase, LoopingCallBase):
    """A backoff looping call for threading backend."""
    pass


class RetryDecorator(loopingcall.RetryDecorator):
    """Threading-specific retry decorator."""

    def _create_dynamic_looping_call(self, func, *args, **kwargs):
        """Create a dynamic looping call instance for threading backend."""
        return DynamicLoopingCall(func, *args, **kwargs)
