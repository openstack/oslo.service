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


from eventlet import event
from eventlet import greenthread
from oslo_utils import eventletutils

from oslo_service.backend._common import loopingcall


# Re-export common classes and exceptions
LoopingCallDone = loopingcall.LoopingCallDone
LoopingCallTimeOut = loopingcall.LoopingCallTimeOut


class LoopingCallBase(loopingcall.LoopingCallBase):
    """Eventlet-specific implementation of LoopingCallBase."""

    def _get_abort_mechanism(self):
        """Return a new abort mechanism instance."""
        return eventletutils.EventletEvent()

    def _create_done_event(self):
        return event.Event()

    def _spawn_loop(self, loop_func):
        thread = greenthread.spawn(loop_func)
        thread.link(self._on_done)
        return thread


class FixedIntervalLoopingCall(
        loopingcall.FixedIntervalLoopingCallBase,
        LoopingCallBase):
    """A fixed interval looping call for eventlet backend."""
    pass


class FixedIntervalWithTimeoutLoopingCall(
        loopingcall.FixedIntervalWithTimeoutLoopingCallBase,
        LoopingCallBase):
    """A fixed interval looping call with timeout for eventlet backend."""
    pass


class DynamicLoopingCall(loopingcall.DynamicLoopingCallBase, LoopingCallBase):
    """A dynamic looping call for eventlet backend."""
    pass


class BackOffLoopingCall(loopingcall.BackOffLoopingCallBase, LoopingCallBase):
    """A backoff looping call for eventlet backend."""
    pass


class RetryDecorator(loopingcall.RetryDecorator):
    """Eventlet-specific retry decorator."""

    def _create_dynamic_looping_call(self, func, *args, **kwargs):
        """Create a dynamic looping call instance for eventlet backend."""
        return DynamicLoopingCall(func, *args, **kwargs)
