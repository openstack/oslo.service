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
from oslotest import base as test_base

from oslo_service import opts


class TestSetServiceOptsDefaults(test_base.BaseTestCase):
    def setUp(self):
        super().setUp()
        self.conf = cfg.ConfigOpts()

    def test_set_defaults_for_multiple_options(self):
        opts.set_service_opts_defaults(
            self.conf,
            log_options=False,
            graceful_shutdown_timeout=120
        )
        self.conf(args=[])
        # Check the new defaults value
        self.assertFalse(self.conf.log_options)
        self.assertEqual(120, self.conf.graceful_shutdown_timeout)

    def test_set__defaults_for_single_option(self):
        opts.set_service_opts_defaults(
            self.conf,
            graceful_shutdown_timeout=30
        )
        self.conf(args=[])
        # Check new default for graceful_shutdown_timeout
        self.assertEqual(30, self.conf.graceful_shutdown_timeout)

    def test_service_opts_multiple_registration_same_conf(self):
        opts.register_service_opts(self.conf)
        opts.set_service_opts_defaults(
            self.conf,
            log_options=False,
            graceful_shutdown_timeout=120
        )
        # Check the new defaults value
        self.assertFalse(self.conf.log_options)
        self.assertEqual(120, self.conf.graceful_shutdown_timeout)
        opts.register_service_opts(self.conf)
        opts.set_service_opts_defaults(
            self.conf,
            log_options=True,
            graceful_shutdown_timeout=100
        )
        # Check the new defaults value
        self.assertTrue(self.conf.log_options)
        self.assertEqual(100, self.conf.graceful_shutdown_timeout)
        opts.register_service_opts(self.conf)

    def test_service_opts_multiple_registration_different_conf(self):
        opts.register_service_opts(self.conf)
        opts.set_service_opts_defaults(
            self.conf,
            log_options=False,
            graceful_shutdown_timeout=120
        )
        # Check the new defaults value
        self.assertFalse(self.conf.log_options)
        self.assertEqual(120, self.conf.graceful_shutdown_timeout)
        conf = cfg.ConfigOpts()
        opts.register_service_opts(conf)
        opts.set_service_opts_defaults(
            conf,
            graceful_shutdown_timeout=180
        )
        # Check the new defaults value
        self.assertEqual(180, conf.graceful_shutdown_timeout)
