# Copyright 2015 Mirantis Inc.
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

from oslo_config import cfg


help_for_backdoor_port = (
    "Acceptable values are 0, <port>, and <start>:<end>, where 0 results "
    "in listening on a random tcp port number; <port> results in listening "
    "on the specified port number (and not enabling backdoor if that port "
    "is in use); and <start>:<end> results in listening on the smallest "
    "unused port number within the specified range of port numbers.  The "
    "chosen port is displayed in the service's log file.")
eventlet_backdoor_opts = [
    cfg.StrOpt('backdoor_port',
               help="Enable eventlet backdoor.  %s" % help_for_backdoor_port)
]

periodic_opts = [
    cfg.BoolOpt('run_external_periodic_tasks',
                default=True,
                help='Some periodic tasks can be run in a separate process. '
                     'Should we run them here?'),
]

service_opts = [
    cfg.BoolOpt('log_options',
                default=True,
                help='Enables or disables logging values of all registered '
                     'options when starting a service (at DEBUG level).'),
]

ssl_opts = [
    cfg.StrOpt('ca_file',
               help="CA certificate file to use to verify "
                    "connecting clients."),
    cfg.StrOpt('cert_file',
               help="Certificate file to use when starting "
                    "the server securely."),
    cfg.StrOpt('key_file',
               help="Private key file to use when starting "
                    "the server securely."),
]
