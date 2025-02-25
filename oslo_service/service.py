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

"""Generic Node base class for all workers that run on hosts."""


import copy

from oslo_service.backend import get_component

from oslo_service import _options


# Dynamically expose components from the backend
ServiceBase = get_component("ServiceBase")
ServiceLauncher = get_component("ServiceLauncher")
Launcher = get_component("Launcher")
ProcessLauncher = get_component("ProcessLauncher")
Service = get_component("Service")
Services = get_component("Services")
ServiceWrapper = get_component("ServiceWrapper")
SignalHandler = get_component("SignalHandler")
SignalExit = get_component("SignalExit")
Singleton = get_component("Singleton")

# Function exports
launch = get_component("launch")

# Utility functions
_is_daemon = get_component("_is_daemon")
_is_sighup_and_daemon = get_component("_is_sighup_and_daemon")


def list_opts():
    """Entry point for oslo-config-generator."""
    return [(None, copy.deepcopy(_options.eventlet_backdoor_opts +
                                 _options.service_opts))]
