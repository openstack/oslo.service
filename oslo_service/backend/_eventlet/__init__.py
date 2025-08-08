# Copyright (C) 2024 Red Hat, Inc.
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


from oslo_service.backend._common import service as service_common
from oslo_service.backend._eventlet import loopingcall
from oslo_service.backend._eventlet import service
from oslo_service.backend._eventlet import threadgroup
from oslo_service.backend.base import BaseBackend


class EventletBackend(BaseBackend):
    """Backend implementation for Eventlet."""

    @staticmethod
    def get_service_components():
        """Return the components provided by the Eventlet backend."""

        return {
            # Classes
            "ServiceBase": service.ServiceBase,
            "ServiceLauncher": service.ServiceLauncher,
            "Launcher": service.Launcher,
            "ProcessLauncher": service.ProcessLauncher,
            "Service": service.Service,
            "Services": service.Services,
            "ServiceWrapper": service.ServiceWrapper,
            "SignalHandler": service.SignalHandler,
            "SignalExit": service_common.SignalExit,
            "Singleton": service_common.Singleton,

            # Looping call-related classes
            "LoopingCallBase": loopingcall.LoopingCallBase,
            "LoopingCallDone": loopingcall.LoopingCallDone,
            "LoopingCallTimeOut": loopingcall.LoopingCallTimeOut,
            "FixedIntervalLoopingCall": loopingcall.FixedIntervalLoopingCall,
            "FixedIntervalWithTimeoutLoopingCall":
                loopingcall.FixedIntervalWithTimeoutLoopingCall,
            "DynamicLoopingCall": loopingcall.DynamicLoopingCall,
            "BackOffLoopingCall": loopingcall.BackOffLoopingCall,
            "RetryDecorator": loopingcall.RetryDecorator,

            # Threadgroup call-related classes
            "ThreadGroup": threadgroup.ThreadGroup,
            "Thread": threadgroup.Thread,

            # Functions
            "launch": service.launch,
            "_is_daemon": service_common.is_daemon,
            "_is_sighup_and_daemon": service_common.is_sighup_and_daemon,
        }
