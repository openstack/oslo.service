# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Unit tests for `wsgi`."""

import os
import platform
import socket
import tempfile
import testtools
from unittest import mock

import eventlet
import eventlet.wsgi
import requests
import webob

from oslo_config import cfg
from oslo_service import backend
from oslo_service.backend.exceptions import BackendAlreadySelected
from oslo_service.backend.exceptions import UnsupportedBackendError
from oslo_service import sslutils
from oslo_service.tests import base
from oslo_service import wsgi
from oslo_utils import netutils


SSL_CERT_DIR = os.path.normpath(os.path.join(
                                os.path.dirname(os.path.abspath(__file__)),
                                'ssl_cert'))
CONF = cfg.CONF


class WsgiTestCase(base.ServiceBaseTestCase):
    """Base class for WSGI tests."""

    def setUp(self):
        super().setUp()
        self.conf(args=[], default_config_files=[])

        # Ensure eventlet backend is active for WSGI tests
        backend._reset_backend()
        backend.init_backend(backend.BackendType.EVENTLET)


class TestLoaderNothingExists(WsgiTestCase):
    """Loader tests where os.path.exists always returns False."""

    def setUp(self):
        super().setUp()
        mock_patcher = mock.patch.object(os.path, 'exists',
                                         lambda _: False)
        mock_patcher.start()
        self.addCleanup(mock_patcher.stop)

    def test_relpath_config_not_found(self):
        self.config(api_paste_config='api-paste.ini')
        self.assertRaises(
            wsgi.ConfigNotFound,
            wsgi.Loader,
            self.conf
        )

    def test_asbpath_config_not_found(self):
        self.config(api_paste_config='/etc/openstack-srv/api-paste.ini')
        self.assertRaises(
            wsgi.ConfigNotFound,
            wsgi.Loader,
            self.conf
        )


class TestLoaderNormalFilesystem(WsgiTestCase):
    """Loader tests with normal filesystem (unmodified os.path module)."""

    _paste_config = """
[app:test_app]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        super().setUp()
        self.paste_config = tempfile.NamedTemporaryFile(mode="w+t")
        self.paste_config.write(self._paste_config.lstrip())
        self.paste_config.seek(0)
        self.paste_config.flush()

        self.config(api_paste_config=self.paste_config.name)
        self.loader = wsgi.Loader(CONF)

    def test_config_found(self):
        self.assertEqual(self.paste_config.name, self.loader.config_path)

    def test_app_not_found(self):
        self.assertRaises(
            wsgi.PasteAppNotFound,
            self.loader.load_app,
            "nonexistent app",
        )

    def test_app_found(self):
        url_parser = self.loader.load_app("test_app")
        self.assertEqual("/tmp", url_parser.directory)

    def tearDown(self):
        self.paste_config.close()
        super().tearDown()


class TestWSGIServer(WsgiTestCase):
    """WSGI server tests."""

    def setUp(self):
        super().setUp()

    def test_no_app(self):
        server = wsgi.Server(self.conf, "test_app", None)
        self.assertEqual("test_app", server.name)

    def test_custom_max_header_line(self):
        self.config(max_header_line=4096)  # Default value is 16384
        wsgi.Server(self.conf, "test_custom_max_header_line", None)
        self.assertEqual(eventlet.wsgi.MAX_HEADER_LINE,
                         self.conf.max_header_line)

    def test_start_random_port(self):
        server = wsgi.Server(self.conf, "test_random_port", None,
                             host="127.0.0.1", port=0)
        server.start()
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    @testtools.skipIf(not netutils.is_ipv6_enabled(), "no ipv6 support")
    def test_start_random_port_with_ipv6(self):
        server = wsgi.Server(self.conf, "test_random_port", None,
                             host="::1", port=0)
        server.start()
        self.assertEqual("::1", server.host)
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    @testtools.skipIf(platform.mac_ver()[0] != '',
                      'SO_REUSEADDR behaves differently '
                      'on OSX, see bug 1436895')
    def test_socket_options_for_simple_server(self):
        # test normal socket options has set properly
        self.config(tcp_keepidle=500)
        server = wsgi.Server(self.conf, "test_socket_options", None,
                             host="127.0.0.1", port=0)
        server.start()
        sock = server.socket
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_REUSEADDR))
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_KEEPALIVE))
        if hasattr(socket, 'TCP_KEEPIDLE'):
            self.assertEqual(self.conf.tcp_keepidle,
                             sock.getsockopt(socket.IPPROTO_TCP,
                                             socket.TCP_KEEPIDLE))
        self.assertFalse(server._server.dead)
        server.stop()
        server.wait()
        self.assertTrue(server._server.dead)

    @testtools.skipIf(not hasattr(socket, "AF_UNIX"),
                      'UNIX sockets not supported')
    def test_server_with_unix_socket(self):
        socket_file = self.get_temp_file_path('sock')
        socket_mode = 0o644
        server = wsgi.Server(self.conf, "test_socket_options", None,
                             socket_family=socket.AF_UNIX,
                             socket_mode=socket_mode,
                             socket_file=socket_file)
        self.assertEqual(socket_file, server.socket.getsockname())
        self.assertEqual(socket_mode,
                         os.stat(socket_file).st_mode & 0o777)
        server.start()
        self.assertFalse(server._server.dead)
        server.stop()
        server.wait()
        self.assertTrue(server._server.dead)

    def test_server_pool_waitall(self):
        # test pools waitall method gets called while stopping server
        server = wsgi.Server(self.conf, "test_server", None, host="127.0.0.1")
        server.start()
        with mock.patch.object(server._pool,
                               'waitall') as mock_waitall:
            server.stop()
            server.wait()
            mock_waitall.assert_called_once_with()

    def test_uri_length_limit(self):
        eventlet.monkey_patch(os=False, thread=False)
        server = wsgi.Server(self.conf, "test_uri_length_limit", None,
                             host="127.0.0.1", max_url_len=16384, port=33337)
        server.start()
        self.assertFalse(server._server.dead)

        uri = "http://127.0.0.1:%d/%s" % (server.port, 10000 * 'x')
        resp = requests.get(uri, proxies={"http": ""})
        eventlet.sleep(0)
        self.assertNotEqual(requests.codes.REQUEST_URI_TOO_LARGE,
                            resp.status_code)

        uri = "http://127.0.0.1:%d/%s" % (server.port, 20000 * 'x')
        resp = requests.get(uri, proxies={"http": ""})
        eventlet.sleep(0)
        self.assertEqual(requests.codes.REQUEST_URI_TOO_LARGE,
                         resp.status_code)
        server.stop()
        server.wait()

    def test_reset_pool_size_to_default(self):
        server = wsgi.Server(self.conf, "test_resize", None,
                             host="127.0.0.1", max_url_len=16384)
        server.start()

        # Stopping the server, which in turn sets pool size to 0
        server.stop()
        self.assertEqual(0, server._pool.size)

        # Resetting pool size to default
        server.reset()
        server.start()
        self.assertEqual(CONF.wsgi_default_pool_size, server._pool.size)

    def test_client_socket_timeout(self):
        self.config(client_socket_timeout=5)

        # mocking eventlet spawn method to check it is called with
        # configured 'client_socket_timeout' value.
        with mock.patch.object(eventlet,
                               'spawn') as mock_spawn:
            server = wsgi.Server(self.conf, "test_app", None,
                                 host="127.0.0.1", port=0)
            server.start()
            _, kwargs = mock_spawn.call_args
            self.assertEqual(self.conf.client_socket_timeout,
                             kwargs['socket_timeout'])
            server.stop()

    def test_wsgi_keep_alive(self):
        self.config(wsgi_keep_alive=False)

        # mocking eventlet spawn method to check it is called with
        # configured 'wsgi_keep_alive' value.
        with mock.patch.object(eventlet,
                               'spawn') as mock_spawn:
            server = wsgi.Server(self.conf, "test_app", None,
                                 host="127.0.0.1", port=0)
            server.start()
            _, kwargs = mock_spawn.call_args
            self.assertEqual(self.conf.wsgi_keep_alive,
                             kwargs['keepalive'])
            server.stop()


def requesting(host, port, ca_certs=None, method="POST",
               content_type="application/x-www-form-urlencoded",
               address_familly=socket.AF_INET):
    frame = bytes("{verb} / HTTP/1.1\r\n\r\n".format(verb=method), "utf-8")
    with socket.socket(address_familly, socket.SOCK_STREAM) as sock:
        if ca_certs:
            with eventlet.wrap_ssl(sock, ca_certs=ca_certs) as wrappedSocket:
                wrappedSocket.connect((host, port))
                wrappedSocket.send(frame)
                data = wrappedSocket.recv(1024).decode()
                return data
        else:
            sock.connect((host, port))
            sock.send(frame)
            data = sock.recv(1024).decode()
            return data


class TestWSGIServerWithSSL(WsgiTestCase):
    """WSGI server with SSL tests."""

    def setUp(self):
        super().setUp()
        cert_file_name = os.path.join(SSL_CERT_DIR, 'certificate.crt')
        key_file_name = os.path.join(SSL_CERT_DIR, 'privatekey.key')
        eventlet.monkey_patch(os=False, thread=False)
        self.host = "127.0.0.1"

        self.config(cert_file=cert_file_name,
                    key_file=key_file_name,
                    group=sslutils.config_section)

    def test_ssl_server(self):
        def test_app(env, start_response):
            start_response('200 OK', {})
            return ['PONG']

        fake_ssl_server = wsgi.Server(self.conf, "fake_ssl", test_app,
                                      host=self.host, port=0, use_ssl=True)
        fake_ssl_server.start()
        self.assertNotEqual(0, fake_ssl_server.port)

        response = requesting(
            method='GET',
            host=self.host,
            port=fake_ssl_server.port,
            ca_certs=os.path.join(SSL_CERT_DIR, 'ca.crt'),
        )
        self.assertEqual('PONG', response[-4:])

        fake_ssl_server.stop()
        fake_ssl_server.wait()

    def test_two_servers(self):
        def test_app(env, start_response):
            start_response('200 OK', {})
            return ['PONG']

        fake_ssl_server = wsgi.Server(self.conf, "fake_ssl", test_app,
                                      host="127.0.0.1", port=0, use_ssl=True)
        fake_ssl_server.start()
        self.assertNotEqual(0, fake_ssl_server.port)

        fake_server = wsgi.Server(self.conf, "fake", test_app,
                                  host="127.0.0.1", port=0)
        fake_server.start()
        self.assertNotEqual(0, fake_server.port)

        response = requesting(
            method='GET',
            host='127.0.0.1',
            port=fake_ssl_server.port,
            ca_certs=os.path.join(SSL_CERT_DIR, 'ca.crt'),
        )
        self.assertEqual('PONG', response[-4:])

        response = requesting(
            method='GET',
            host='127.0.0.1',
            port=fake_server.port,
        )
        self.assertEqual('PONG', response[-4:])

        fake_ssl_server.stop()
        fake_ssl_server.wait()

        fake_server.stop()
        fake_server.wait()

    @testtools.skipIf(platform.mac_ver()[0] != '',
                      'SO_REUSEADDR behaves differently '
                      'on OSX, see bug 1436895')
    def test_socket_options_for_ssl_server(self):
        # test normal socket options has set properly
        self.config(tcp_keepidle=500)
        server = wsgi.Server(self.conf, "test_socket_options", None,
                             host="127.0.0.1", port=0, use_ssl=True)
        server.start()
        sock = server.socket
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_REUSEADDR))
        self.assertEqual(1, sock.getsockopt(socket.SOL_SOCKET,
                                            socket.SO_KEEPALIVE))
        if hasattr(socket, 'TCP_KEEPIDLE'):
            self.assertEqual(CONF.tcp_keepidle,
                             sock.getsockopt(socket.IPPROTO_TCP,
                                             socket.TCP_KEEPIDLE))
        server.stop()
        server.wait()

    def test_app_using_ipv6_and_ssl(self):
        greetings = 'Hello, World!!!'

        @webob.dec.wsgify
        def hello_world(req):
            return greetings

        server = wsgi.Server(self.conf, "fake_ssl",
                             hello_world,
                             host="::1",
                             port=0,
                             use_ssl=True)

        server.start()

        response = requesting(
            method='GET',
            host='::1',
            port=server.port,
            ca_certs=os.path.join(SSL_CERT_DIR, 'ca.crt'),
            address_familly=socket.AF_INET6
        )
        self.assertEqual(greetings, response[-15:])

        server.stop()
        server.wait()


class TestWSGIServerBackendCompatibility(WsgiTestCase):
    """Tests for WSGI Server backend compatibility."""

    def setUp(self):
        super().setUp()
        self.backend_module = backend
        # Reset backend state before each test to allow re-initialization
        self.backend_module._reset_backend()

    def tearDown(self):
        super().tearDown()
        # Reset backend state after each test
        self.backend_module._reset_backend()

    def test_server_creation_with_eventlet_backend(self):
        """Test that Server can be created with eventlet backend."""
        # Initialize eventlet backend explicitly
        self.backend_module.init_backend(
            self.backend_module.BackendType.EVENTLET)

        # This should work without raising an exception
        server = wsgi.Server(self.conf, "test_eventlet", None)
        self.assertEqual("test_eventlet", server.name)

    def test_server_creation_fails_with_threading_backend(self):
        """Test that Server creation fails with threading backend."""
        # Initialize threading backend
        self.backend_module.init_backend(
            self.backend_module.BackendType.THREADING)

        # This should raise UnsupportedBackendError
        def create_server():
            return wsgi.Server(self.conf, "test_threading", None)

        exc = self.assertRaises(UnsupportedBackendError, create_server)

        # Check that the error message contains specific information
        error_message = str(exc)
        self.assertIn("oslo.service.wsgi.Server", error_message)
        self.assertIn("threading backend", error_message)
        self.assertIn("standard WSGI servers", error_message)

    def test_check_backend_compatibility_function_eventlet(self):
        """Test _check_backend_compatibility with eventlet backend."""
        # Initialize eventlet backend
        self.backend_module.init_backend(
            self.backend_module.BackendType.EVENTLET)

        # This should not raise an exception
        try:
            wsgi._check_backend_compatibility()
        except Exception as e:
            self.fail(f"_check_backend_compatibility raised {e} unexpectedly")

    def test_check_backend_compatibility_function_threading(self):
        """Test _check_backend_compatibility with threading backend."""
        # Initialize threading backend
        self.backend_module.init_backend(
            self.backend_module.BackendType.THREADING)

        # This should raise UnsupportedBackendError
        self.assertRaises(
            UnsupportedBackendError,
            wsgi._check_backend_compatibility)

    def test_check_backend_compatibility_with_default_backend(self):
        """Test _check_backend_compatibility with defaut backend."""
        # Don't explicitly initialize backend, use default (eventlet)

        # This should not raise an exception since default is eventlet
        try:
            wsgi._check_backend_compatibility()
        except Exception as e:
            self.fail(f"_check_backend_compatibility raised {e} unexpectedly")

    @mock.patch('oslo_service.wsgi.backend.get_backend_type')
    def test_check_backend_compatibility_with_none_backend(
        self, mock_get_backend_type):
        """Test _check_backend_compatibility when backend type is None."""
        # Simulate the case where backend hasn't been initialized yet
        mock_get_backend_type.return_value = None

        # This should not raise an exception
        try:
            wsgi._check_backend_compatibility()
        except Exception as e:
            self.fail(f"_check_backend_compatibility raised {e} unexpectedly")

    def test_server_initialization_sequence_with_threading_backend(self):
        """Test that the error occurs during Server.__init__, not after."""
        # Initialize threading backend
        self.backend_module.init_backend(
            self.backend_module.BackendType.THREADING)

        # The error should occur immediately during __init__
        def create_server():
            # Server.__init__ should fail before any actual server setup
            return wsgi.Server(
                self.conf, "test_early_fail", None, host="127.0.0.1", port=0)

        self.assertRaises(UnsupportedBackendError, create_server)

    def test_multiple_server_creation_attempts_with_threading_backend(self):
        """Test that all attempts creating Server fail consistently."""
        # Initialize threading backend
        self.backend_module.init_backend(
            self.backend_module.BackendType.THREADING)

        # Multiple attempts should all fail in the same way
        for i in range(3):
            def create_server():
                return wsgi.Server(self.conf, f"test_multi_{i}", None)

            self.assertRaises(UnsupportedBackendError, create_server)

    def test_backend_switching_behavior(self):
        """Test behavior when trying to switch backends."""
        # Start with eventlet backend
        self.backend_module.init_backend(
            self.backend_module.BackendType.EVENTLET)

        # Server creation should work
        server = wsgi.Server(self.conf, "test_eventlet_first", None)
        self.assertEqual("test_eventlet_first", server.name)

        # Attempting to switch to threading backend should fail
        def switch_backend():
            self.backend_module.init_backend(
                self.backend_module.BackendType.THREADING)

        self.assertRaises(BackendAlreadySelected, switch_backend)

        # Server creation should still work since backend is still eventlet
        server2 = wsgi.Server(self.conf, "test_eventlet_second", None)
        self.assertEqual("test_eventlet_second", server2.name)
