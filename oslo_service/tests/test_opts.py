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

import subprocess
import sys

from oslo_config import cfg
from oslotest import base as test_base

from oslo_service import _options
from oslo_service import opts


class TestListOpts(test_base.BaseTestCase):
    def assert_options_are_independent(
        self, callback, originals, expected_group=None
    ):
        [(group, options)] = callback()
        self.assertEqual(expected_group, group)
        self.assertEqual(
            [option.name for option in originals],
            [option.name for option in options],
        )
        for original, option in zip(originals, options):
            self.assertIsNot(original, option)

        original_default = originals[0].default
        options[0].default = object()
        options.pop()

        [(group, fresh_options)] = callback()
        self.assertEqual(original_default, originals[0].default)
        self.assertEqual(original_default, fresh_options[0].default)
        self.assertEqual(len(originals), len(fresh_options))

    def test_periodic_task_options_are_independent(self):
        self.assert_options_are_independent(
            opts.list_periodic_task_opts, _options.periodic_opts
        )

    def test_service_options_are_independent(self):
        self.assert_options_are_independent(
            opts.list_service_opts,
            _options.eventlet_backdoor_opts + _options.service_opts,
        )

    def test_ssl_options_are_independent(self):
        self.assert_options_are_independent(
            opts.list_ssl_opts, _options.ssl_opts, expected_group='ssl'
        )

    def test_wsgi_options_are_independent(self):
        self.assert_options_are_independent(
            opts.list_wsgi_opts, _options.wsgi_opts
        )

    def test_entry_points_do_not_select_a_backend(self):
        # Use a fresh process without the test suite's backend hook.
        code = """
import sys
from importlib import metadata

from oslo_service import backend

entry_points = metadata.entry_points(group='oslo.config.opts')
for namespace, expected_group in (
    ('oslo.service.periodic_task', None),
    ('oslo.service.service', None),
    ('oslo.service.sslutils', 'ssl'),
    ('oslo.service.wsgi', None),
):
    entry_point = next(ep for ep in entry_points if ep.name == namespace)
    options = entry_point.load()()
    assert options and options[0][0] == expected_group

assert backend.get_backend_type() is None
assert backend._backend_hook is None
assert 'eventlet' not in sys.modules
assert 'oslo_service.periodic_task' not in sys.modules
assert 'oslo_service.service' not in sys.modules
assert 'oslo_service.sslutils' not in sys.modules
assert 'oslo_service.wsgi' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


class TestSetServiceOptsDefaults(test_base.BaseTestCase):
    def setUp(self):
        super().setUp()
        self.conf = cfg.ConfigOpts()

    def test_set_defaults_for_multiple_options(self):
        opts.set_service_opts_defaults(
            self.conf, log_options=False, graceful_shutdown_timeout=120
        )
        self.conf(args=[])
        # Check the new defaults value
        self.assertFalse(self.conf.log_options)
        self.assertEqual(120, self.conf.graceful_shutdown_timeout)

    def test_set__defaults_for_single_option(self):
        opts.set_service_opts_defaults(self.conf, graceful_shutdown_timeout=30)
        self.conf(args=[])
        # Check new default for graceful_shutdown_timeout
        self.assertEqual(30, self.conf.graceful_shutdown_timeout)

    def test_service_opts_multiple_registration_same_conf(self):
        opts.register_service_opts(self.conf)
        opts.set_service_opts_defaults(
            self.conf, log_options=False, graceful_shutdown_timeout=120
        )
        # Check the new defaults value
        self.assertFalse(self.conf.log_options)
        self.assertEqual(120, self.conf.graceful_shutdown_timeout)
        opts.register_service_opts(self.conf)
        opts.set_service_opts_defaults(
            self.conf, log_options=True, graceful_shutdown_timeout=100
        )
        # Check the new defaults value
        self.assertTrue(self.conf.log_options)
        self.assertEqual(100, self.conf.graceful_shutdown_timeout)
        opts.register_service_opts(self.conf)

    def test_service_opts_multiple_registration_different_conf(self):
        opts.register_service_opts(self.conf)
        opts.set_service_opts_defaults(
            self.conf, log_options=False, graceful_shutdown_timeout=120
        )
        # Check the new defaults value
        self.assertFalse(self.conf.log_options)
        self.assertEqual(120, self.conf.graceful_shutdown_timeout)
        conf = cfg.ConfigOpts()
        opts.register_service_opts(conf)
        opts.set_service_opts_defaults(conf, graceful_shutdown_timeout=180)
        # Check the new defaults value
        self.assertEqual(180, conf.graceful_shutdown_timeout)
