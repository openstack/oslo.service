# Copyright 2026 Red Hat, Inc.
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

import logging
from unittest import mock

from oslo_config import cfg
from oslo_log import log as oslo_log

from oslo_service import _spawn_utils
from oslo_service.tests import base


class SpawnUtilsTestCase(base.ServiceBaseTestCase):

    def setUp(self):
        super().setUp()
        self.root_logger = logging.getLogger()
        self.original_handlers = list(self.root_logger.handlers)
        self.addCleanup(self._restore_root_handlers)
        self.root_logger.handlers = []

    def _restore_root_handlers(self):
        self.root_logger.handlers = self.original_handlers

    def test_get_current_oslo_logging_setup_from_formatter(self):
        formatter = logging.Formatter()
        formatter.project = 'nova'
        formatter.version = '31.0.0'
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.root_logger.addHandler(handler)

        self.assertEqual(
            ('nova', '31.0.0'),
            _spawn_utils.get_current_oslo_logging_setup(),
        )

    def test_get_current_oslo_logging_setup_defaults_unknown(self):
        self.root_logger.addHandler(logging.StreamHandler())

        self.assertEqual(
            ('unknown', 'unknown'),
            _spawn_utils.get_current_oslo_logging_setup(),
        )

    def test_get_current_oslo_logging_setup_without_version(self):
        formatter = logging.Formatter()
        formatter.project = 'nova'
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.root_logger.addHandler(handler)

        self.assertEqual(
            ('nova', 'unknown'),
            _spawn_utils.get_current_oslo_logging_setup(),
        )

    def test_configure_spawn_worker(self):
        conf = cfg.ConfigOpts()

        with mock.patch.object(oslo_log, 'setup') as setup:
            _spawn_utils.configure_spawn_worker(
                conf,
                project='test-project',
                version='1.0',
            )

        setup.assert_called_once_with(
            conf,
            'test-project',
            '1.0',
            fix_eventlet=False,
        )
