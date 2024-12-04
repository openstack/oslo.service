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


from oslo_service.backend import get_component


# Dynamically load looping call components from the backend
LoopingCallBase = get_component("LoopingCallBase")
LoopingCallDone = get_component("LoopingCallDone")
LoopingCallTimeOut = get_component("LoopingCallTimeOut")
FixedIntervalLoopingCall = get_component("FixedIntervalLoopingCall")
FixedIntervalWithTimeoutLoopingCall = get_component(
    "FixedIntervalWithTimeoutLoopingCall")
DynamicLoopingCall = get_component("DynamicLoopingCall")
BackOffLoopingCall = get_component("BackOffLoopingCall")
RetryDecorator = get_component("RetryDecorator")
