# Copyright 2015 Mirantis, Inc.
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

import os
import ssl
from unittest import mock

from oslo_config import cfg

from oslo_service import sslutils
from oslo_service.tests import base


CONF = cfg.CONF

SSL_CERT_DIR = os.path.normpath(os.path.join(
                                os.path.dirname(os.path.abspath(__file__)),
                                'ssl_cert'))


class SslutilsTestCase(base.ServiceBaseTestCase):
    """Test cases for sslutils."""

    def setUp(self):
        super().setUp()
        self.cert_file_name = os.path.join(SSL_CERT_DIR, 'certificate.crt')
        self.key_file_name = os.path.join(SSL_CERT_DIR, 'privatekey.key')
        self.ca_file_name = os.path.join(SSL_CERT_DIR, 'ca.crt')

    @mock.patch("%s.RuntimeError" % RuntimeError.__module__)
    @mock.patch("os.path.exists")
    def test_is_enabled(self, exists_mock, runtime_error_mock):
        exists_mock.return_value = True
        self.conf.set_default("cert_file", self.cert_file_name,
                              group=sslutils.config_section)
        self.conf.set_default("key_file", self.key_file_name,
                              group=sslutils.config_section)
        self.conf.set_default("ca_file", self.ca_file_name,
                              group=sslutils.config_section)
        sslutils.is_enabled(self.conf)
        self.assertFalse(runtime_error_mock.called)

    @mock.patch("os.path.exists")
    def test_is_enabled_no_ssl_cert_file_fails(self, exists_mock):
        exists_mock.side_effect = [False]
        self.conf.set_default("cert_file", "/no/such/file",
                              group=sslutils.config_section)
        self.assertRaises(RuntimeError, sslutils.is_enabled, self.conf)

    @mock.patch("os.path.exists")
    def test_is_enabled_no_ssl_key_file_fails(self, exists_mock):
        exists_mock.side_effect = [True, False]
        self.conf.set_default("cert_file", self.cert_file_name,
                              group=sslutils.config_section)
        self.conf.set_default("key_file", "/no/such/file",
                              group=sslutils.config_section)
        self.assertRaises(RuntimeError, sslutils.is_enabled, self.conf)

    @mock.patch("os.path.exists")
    def test_is_enabled_no_ssl_ca_file_fails(self, exists_mock):
        exists_mock.side_effect = [True, True, False]
        self.conf.set_default("cert_file", self.cert_file_name,
                              group=sslutils.config_section)
        self.conf.set_default("key_file", self.key_file_name,
                              group=sslutils.config_section)
        self.conf.set_default("ca_file", "/no/such/file",
                              group=sslutils.config_section)
        self.assertRaises(RuntimeError, sslutils.is_enabled, self.conf)

    @mock.patch("ssl.SSLContext")
    @mock.patch("os.path.exists")
    def _test_wrap(self, exists_mock, ssl_context_mock,
                   ca_file=None,
                   ciphers=None,
                   ssl_version=None):
        exists_mock.return_value = True
        sock = mock.Mock()
        context = mock.Mock()
        ssl_context_mock.return_value = context
        self.conf.set_default("cert_file", self.cert_file_name,
                              group=sslutils.config_section)
        self.conf.set_default("key_file", self.key_file_name,
                              group=sslutils.config_section)
        sslutils.wrap(self.conf, sock)
        ssl_version = ssl_version or ssl.PROTOCOL_TLS_SERVER
        ssl_context_mock.assert_called_once_with(ssl_version)
        context.load_cert_chain.assert_called_once_with(
            self.conf.ssl.cert_file,
            self.conf.ssl.key_file,
        )
        if ca_file:
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            context.load_verify_locations.assert_called_once_with(
                ca_file
            )
        else:
            self.assertEqual(context.verify_mode, ssl.CERT_NONE)
            self.assertFalse(context.check_hostname)
        if ciphers:
            context.set_ciphers.assert_called_once_with(
                ciphers
            )
        context.wrap_socket.assert_called_once_with(sock, server_side=True)

    def test_wrap(self):
        self._test_wrap()

    def test_wrap_ca_file(self):
        self.conf.set_default("ca_file", self.ca_file_name,
                              group=sslutils.config_section)
        self._test_wrap(ca_file=self.conf.ssl.ca_file)

    def test_wrap_ciphers(self):
        self.conf.set_default("ca_file", self.ca_file_name,
                              group=sslutils.config_section)
        ciphers = (
            'ECDH+AESGCM:DH+AESGCM:ECDH+AES256:DH+AES256:ECDH+AES128:DH+'
            'AES:ECDH+HIGH:DH+HIGH:ECDH+3DES:DH+3DES:RSA+AESGCM:RSA+AES:'
            'RSA+HIGH:RSA+3DES:!aNULL:!eNULL:!MD5:!DSS:!RC4'
        )
        self.conf.set_default("ciphers", ciphers,
                              group=sslutils.config_section)
        self._test_wrap(ca_file=self.conf.ssl.ca_file,
                        ciphers=self.conf.ssl.ciphers)

    def test_wrap_ssl_version(self):
        self.conf.set_default("ca_file", self.ca_file_name,
                              group=sslutils.config_section)
        self.conf.set_default("version", "tlsv1",
                              group=sslutils.config_section)
        self._test_wrap(ca_file=self.conf.ssl.ca_file,
                        ssl_version=ssl.PROTOCOL_TLSv1)
