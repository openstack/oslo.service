# Copyright (C) 2025 Red Hat, Inc.
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

import multiprocessing

import cotyledon
from oslo_config import cfg

from oslo_service._multiprocessing import get_spawn_context
from oslo_service._multiprocessing import get_spawn_pool
from oslo_service.backend._threading import service
from oslo_service.backend.base import ServiceBase
from oslo_service.tests import base


class MockService(ServiceBase):
    """Mock service for spawn context tests."""
    def start(self):
        pass

    def stop(self):
        pass

    def wait(self):
        pass

    def reset(self):
        pass


class TestSpawnContextIntegration(base.ServiceBaseTestCase):
    """Test spawn context integration with service launcher."""

    def setUp(self):
        super().setUp()
        # Reset ServiceManager singleton between tests
        # This allows creating multiple ServiceManager instances in tests
        cotyledon.ServiceManager._process_runner_already_created = False

    def test_spawn_context_is_spawn_safe(self):
        """Test that get_spawn_context returns a spawn context."""
        ctx = get_spawn_context()
        self.assertEqual(ctx.get_start_method(), "spawn")

    def test_spawn_pool_creates_spawn_based_pool(self):
        """Test that get_spawn_pool creates a pool with spawn context."""
        pool = get_spawn_pool()
        self.assertIsInstance(pool, multiprocessing.pool.Pool)
        self.assertEqual(pool._ctx.get_start_method(), "spawn")
        pool.close()
        pool.join()

    def test_processlauncher_uses_spawn_context(self):
        """Test that ProcessLauncher initializes with spawn context."""
        # ProcessLauncher creates _manager lazily, so create a mock service
        # to trigger manager creation and verify it uses spawn context
        separate_conf_manager = cfg.ConfigOpts()
        launcher_with_manager = service.ProcessLauncher(
            conf=separate_conf_manager)
        # Trigger manager creation
        mock_service = MockService()
        launcher_with_manager.launch_service(mock_service, workers=1)
        # Verify that ServiceManager uses the spawn context (Cotyledon PR #84)
        self.assertEqual(
            launcher_with_manager._manager_context.get_start_method(),
            "spawn")
        self.assertEqual(
            launcher_with_manager._manager.mp_context.get_start_method(),
            "spawn")
        # Note: We don't call stop() or shutdown() here to avoid blocking.
        # The processes will be cleaned up when the test completes.

    def test_servicelauncher_uses_spawn_context(self):
        """Test that ServiceLauncher initializes with spawn context."""
        # Use a separate conf to avoid duplicate option registration
        separate_conf = cfg.ConfigOpts()
        launcher = service.ServiceLauncher(conf=separate_conf)
        launcher.launch_service(MockService(), workers=1)
        # Verify that ServiceManager uses the spawn context (Cotyledon PR #84)
        self.assertEqual(
            launcher._manager_context.get_start_method(), "spawn")
        self.assertEqual(
            launcher._manager.mp_context.get_start_method(), "spawn")
        # Note: We don't call stop() or shutdown() here to avoid blocking.
        # The processes will be cleaned up when the test completes.
