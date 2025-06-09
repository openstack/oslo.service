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
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_service.backend.base import BaseBackend
from oslo_service.backend.common import daemon_utils
from oslo_service.backend.common import signal_utils
from oslo_service.backend.common import singleton
from oslo_service.backend.threading import loopingcall
from oslo_service.backend.threading import service
from oslo_service.backend.threading import threadgroup


class ThreadingBackend(BaseBackend):
    """Backend implementation using Python threading and Cotyledon."""

    @staticmethod
    def get_service_components():
        """Return the components provided by the Threading backend."""

        return {
            # Service-related classes
            "ServiceBase": service.ServiceBase,
            "ServiceLauncher": service.ProcessLauncher,
            "Launcher": service.ProcessLauncher,
            "ProcessLauncher": service.ProcessLauncher,
            "Service": service.Service,
            "Services": service.Services,
            "ServiceWrapper": service.ServiceWrapper,
            "SignalExit": signal_utils.SignalExit,
            "SignalHandler": service.SignalHandler,
            "Singleton": singleton.Singleton,
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
            # Thread group-related classes
            "ThreadGroup": threadgroup.ThreadGroup,
            "Thread": threadgroup.Thread,
            # Functions
            "_is_daemon": daemon_utils.is_daemon,
            "_is_sighup_and_daemon": daemon_utils.is_sighup_and_daemon,
            "launch": service.launch,
        }
