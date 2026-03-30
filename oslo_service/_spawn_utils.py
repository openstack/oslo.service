# Copyright (C) 2026 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Utilities for spawn-based worker processes."""

import logging

from oslo_config import cfg
from oslo_log import log as oslo_log


def get_current_oslo_logging_setup():
    """Return the project and version configured by oslo.log in this process.

    ``oslo_log.log.setup()`` forwards these values to the root logger's
    formatters. Spawn workers start fresh, so the parent has to send the
    values explicitly when creating the pool.
    """
    for handler in logging.getLogger().handlers:
        formatter = getattr(handler, 'formatter', None)
        project = getattr(formatter, 'project', None)
        version = getattr(formatter, 'version', None)
        if project is not None:
            return project, version or 'unknown'
    return 'unknown', 'unknown'


def configure_spawn_worker(
    conf: cfg.ConfigOpts,
    project: str = 'unknown',
    version: str = 'unknown',
) -> None:
    """Initialize a spawn worker using the parent configuration state.

    ConfigOpts supports pickle serialization through oslo.config's runtime
    state snapshot mechanism. Passing the parent ConfigOpts directly restores
    registered options, parsed values, defaults, and overrides in the worker.

    ``fix_eventlet=False`` is passed because spawn workers are fresh
    interpreter processes with no eventlet monkey-patching.

    :param conf: Parent process configuration state.
    :param project: Product name forwarded to ``oslo_log.log.setup``
                    (used in log formatting).
    :param version: Project version forwarded to ``oslo_log.log.setup``.
    """
    oslo_log.setup(conf, project, version, fix_eventlet=False)
