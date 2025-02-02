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
    "unused port number within the specified range of port numbers. The "
    "chosen port is displayed in the service's log file.")
eventlet_backdoor_opts = [
    cfg.StrOpt('backdoor_port',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'backdoor_port' option is deprecated and will be"
                   " removed in a future release."
               ),
               help="Enable eventlet backdoor.  %s" % help_for_backdoor_port),
    cfg.StrOpt('backdoor_socket',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'backdoor_socket' option is deprecated and will be"
                   " removed in a future release."
               ),
               help="Enable eventlet backdoor, using the provided path"
                    " as a unix socket that can receive connections. This"
                    " option is mutually exclusive with 'backdoor_port' in"
                    " that only one should be provided. If both are provided"
                    " then the existence of this option overrides the usage of"
                    " that option. Inside the path {pid} will be replaced with"
                    " the PID of the current process.")
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
    cfg.IntOpt('graceful_shutdown_timeout',
               default=60,
               help='Specify a timeout after which a gracefully shutdown '
                    'server will exit. Zero value means endless wait.'),
]

wsgi_opts = [
    cfg.StrOpt('api_paste_config',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'api_paste_config' option is deprecated and will be"
                   " removed in a future release."
               ),
               default="api-paste.ini",
               help='File name for the paste.deploy config for api service'),
    cfg.StrOpt('wsgi_log_format',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'wsgi_log_format' option is deprecated and will be"
                   " removed in a future release."
               ),
               default='%(client_ip)s "%(request_line)s" status: '
                       '%(status_code)s  len: %(body_length)s time:'
                       ' %(wall_seconds).7f',
               help='A python format string that is used as the template to '
                    'generate log lines. The following values can be'
                    'formatted into it: client_ip, date_time, request_line, '
                    'status_code, body_length, wall_seconds.'),
    cfg.IntOpt('tcp_keepidle',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'tcp_keepidle' option is deprecated and will be"
                   " removed in a future release."
               ),
               default=600,
               help="Sets the value of TCP_KEEPIDLE in seconds for each "
                    "server socket. Not supported on OS X."),
    cfg.IntOpt('wsgi_default_pool_size',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'wsgi_default_pool_size' option is deprecated and will"
                   " be removed in a future release."
               ),
               default=100,
               help="Size of the pool of greenthreads used by wsgi"),
    cfg.IntOpt('max_header_line',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'max_header_line' option is deprecated and will be"
                   " removed in a future release."
               ),
               default=16384,
               help="Maximum line size of message headers to be accepted. "
                    "max_header_line may need to be increased when using "
                    "large tokens (typically those generated when keystone "
                    "is configured to use PKI tokens with big service "
                    "catalogs)."),
    cfg.BoolOpt('wsgi_keep_alive',
                deprecated_for_removal=True,
                deprecated_reason=(
                    "The 'wsgi_keep_alive' option is deprecated and will be"
                    " removed in a future release."
                ),
                default=True,
                help="If False, closes the client socket connection "
                     "explicitly."),
    cfg.IntOpt('client_socket_timeout', default=900,
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'client_socket_timeout' option is deprecated and will"
                   " be removed in a future release."
               ),
               help="Timeout for client connections' socket operations. "
                    "If an incoming connection is idle for this number of "
                    "seconds it will be closed. A value of '0' means "
                    "wait forever."),
    cfg.BoolOpt('wsgi_server_debug',
                deprecated_for_removal=True,
                deprecated_reason=(
                    "The 'wsgi_server_debug' option is deprecated and will be"
                    " removed in a future release."
                ),
                default=False,
                help="True if the server should send exception tracebacks to "
                     "the clients on 500 errors. If False, the server will "
                     "respond with empty bodies."),
    ]

ssl_opts = [
    cfg.StrOpt('ca_file',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'ca_file' option is deprecated and will be"
                   " removed in a future release."
               ),
               help="CA certificate file to use to verify "
                    "connecting clients."),
    cfg.StrOpt('cert_file',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'cert_file' option is deprecated and will be"
                   " removed in a future release."
               ),
               help="Certificate file to use when starting "
                    "the server securely."),
    cfg.StrOpt('key_file',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'key_file' option is deprecated and will be"
                   " removed in a future release."
               ),
               help="Private key file to use when starting "
                    "the server securely."),
    cfg.StrOpt('version',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'version' option is deprecated and will be"
                   " removed in a future release."
               ),
               help='SSL version to use (valid only if SSL enabled). '
                    'Valid values are TLSv1 and SSLv23. SSLv2, SSLv3, '
                    'TLSv1_1, and TLSv1_2 may be available on some '
                    'distributions.'
               ),
    cfg.StrOpt('ciphers',
               deprecated_for_removal=True,
               deprecated_reason=(
                   "The 'ciphers' option is deprecated and will be"
                   " removed in a future release."
               ),
               help='Sets the list of available ciphers. value should be a '
                    'string in the OpenSSL cipher list format.'
               ),
]
