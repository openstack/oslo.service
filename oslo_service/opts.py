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

import copy
from typing import Any

from oslo_config import cfg

from oslo_service import _options


def list_periodic_task_opts():
    """Return periodic task options without loading the implementation."""
    return [(None, copy.deepcopy(_options.periodic_opts))]


def list_service_opts():
    """Return service options without loading a backend."""
    return [
        (
            None,
            copy.deepcopy(
                _options.eventlet_backdoor_opts + _options.service_opts
            ),
        )
    ]


def list_ssl_opts():
    """Return SSL options without loading the deprecated SSL module."""
    return [('ssl', copy.deepcopy(_options.ssl_opts))]


def list_wsgi_opts():
    """Return WSGI options without loading a backend or Eventlet."""
    return [(None, copy.deepcopy(_options.wsgi_opts))]


def register_service_opts(
    conf: cfg.ConfigOpts,
) -> None:
    """Register the service opts configuration options.

    :param conf: Configuration object, managed by the caller.
    """
    conf.register_opts(_options.service_opts)


def set_service_opts_defaults(
    conf: cfg.ConfigOpts,
    **kwargs: Any,
) -> None:
    """Set defaults for configuration variables.

    Overrides default options values.

    :param conf: Configuration object, managed by the caller.
    :param kwargs: oslo.service[service_opts] configuration variable and
                   their new default value.
    """
    register_service_opts(conf)

    if kwargs:
        cfg.set_defaults(_options.service_opts, **kwargs)
