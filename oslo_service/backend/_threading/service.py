# Copyright (C) 2025 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import logging
import multiprocessing
from multiprocessing.reduction import ForkingPickler
import os
import signal
import sys
import threading
import traceback
import warnings

import cotyledon
from cotyledon import oslo_config_glue

from oslo_service._i18n import _
from oslo_service._multiprocessing import get_spawn_context
from oslo_service import _options
from oslo_service.backend._common.constants import _LAUNCHER_RESTART_METHODS
from oslo_service.backend._common import service as common_service
from oslo_service.backend._threading import threadgroup
from oslo_service.backend.base import ServiceBase

LOG = logging.getLogger(__name__)


def _select_service_manager_context(service_instance):
    try:
        ForkingPickler.dumps(service_instance)
    except Exception as exc:
        if "fork" in multiprocessing.get_all_start_methods():
            LOG.warning(
                "Service %s is not picklable with spawn; "
                "falling back to fork. "
                "Please make the service spawn-safe to avoid this fallback.",
                type(service_instance).__name__,
                exc_info=exc,
            )
            return multiprocessing.get_context("fork")
        LOG.error(
            "Service %s is not picklable with spawn and fork is unavailable.",
            type(service_instance).__name__,
            exc_info=exc,
        )
        raise
    return get_spawn_context()


def _get_service_manager(service_instance, graceful_shutdown_timeout, conf,
                         restart_method):
    """Create and link a cotyledon ServiceManager for the given service.

    :param service_instance: The service instance (used for spawn/fork check).
    :param graceful_shutdown_timeout: Timeout for graceful shutdown.
    :param conf: oslo.config ConfigOpts instance.
    :param restart_method: 'reload' or 'mutate' for SIGHUP handling.
    :returns: A tuple (manager_context, manager).
    """
    manager_context = _select_service_manager_context(service_instance)
    manager = cotyledon.ServiceManager(
        mp_context=manager_context,
        graceful_shutdown_timeout=graceful_shutdown_timeout)
    oslo_config_glue.link(
        manager, conf,
        reload_method=restart_method)
    return (manager_context, manager)


class SignalHandler(metaclass=common_service.Singleton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._signals_by_name, self.signals_to_name = (
            common_service.get_signal_mappings())
        self._signal_handlers = collections.defaultdict(list)
        self.clear()

    def clear(self):
        for sig in list(self._signal_handlers.keys()):
            signal.signal(sig, signal.SIG_DFL)
        self._signal_handlers.clear()

    def ignore_handler(self, sig):
        signo = self._signals_by_name[sig]
        signal.signal(signo, signal.SIG_IGN)
        self._signal_handlers.pop(signo, None)

    def add_handlers(self, signals, handler):
        for sig in signals:
            self.add_handler(sig, handler)

    def add_handler(self, sig, handler):
        if not self.is_signal_supported(sig):
            return
        signo = self._signals_by_name[sig]
        self._signal_handlers[signo].append(handler)
        signal.signal(signo, self._handle_signal_cb)

    def _handle_signal_cb(self, signo, frame):
        for handler in reversed(self._signal_handlers[signo]):
            handler(signo, frame)

    def is_signal_supported(self, sig_name):
        return sig_name in self._signals_by_name


class ServiceWrapper(cotyledon.Service):
    def __init__(self, worker_id, service_instance, **kwargs):
        super().__init__(worker_id)
        if not isinstance(service_instance, ServiceBase):
            raise TypeError("Service must be an instance of ServiceBase")
        self.service_instance = service_instance

    def run(self):
        try:
            self.service_instance.start()
            self.service_instance.wait()
        except Exception:
            traceback.print_exc()
            sys.exit(1)

    def terminate(self):
        self.service_instance.stop()


class Launcher:
    """Launch one or more services and wait for them to complete."""

    def __init__(self, conf, restart_method='reload'):
        self.conf = conf
        self.services = Services(restart_method=restart_method)
        self.backdoor_port = None
        self.restart_method = restart_method

    def launch_service(self, service, workers=1):
        """Load and start the given service.

        :param service: The service you would like to start, must be an
                        instance of :class:`oslo_service.service.ServiceBase`
        :param workers: This param makes this method compatible with
                        ProcessLauncher.launch_service. It must be None, 1 or
                        omitted.
        :returns: None
        """
        if workers is not None and workers != 1:
            raise ValueError(_("Launcher asked to start multiple workers"))
        common_service.check_service_base(service)
        self.services.add(service)

    def stop(self):
        """Stop all services which are currently running.

        :returns: None
        """
        self.services.stop()

    def wait(self):
        """Wait until all services have been stopped, and then return.

        :returns: None
        """
        self.services.wait()

    def restart(self):
        """Reload config files and restart service.

        :returns: The return value from reload_config_files or
            mutate_config_files, according to the restart_method.
        """
        if self.restart_method == 'reload':
            self.conf.reload_config_files()
        else:  # self.restart_method == 'mutate'
            self.conf.mutate_config_files()
        self.services.restart()


class ServiceLauncher:
    def __init__(self, conf, restart_method='reload'):
        self.conf = conf
        self.conf.register_opts(_options.service_opts)
        self.restart_method = restart_method
        self.backdoor_port = None
        self._manager = None
        self._manager_context = None
        self._lock = threading.Lock()

    def launch_service(self, service_instance, workers=1):
        common_service.check_service_base(service_instance)
        service_instance.backdoor_port = self.backdoor_port
        if not isinstance(workers, int) or workers < 1:
            raise ValueError("Number of workers must be >= 1")
        with self._lock:
            if self._manager is None:
                self._manager_context, self._manager = _get_service_manager(
                    service_instance,
                    self.conf.graceful_shutdown_timeout,
                    self.conf,
                    self.restart_method,
                )
            else:
                # NOTE(gmaan): This case means services are launching the
                # multiple workers of the same or different service instances.
                # The first worker has initialized the cotyledon.ServiceManager
                # with the manager context based on whether their service
                # instance is spawn-safe or not. If the next worker is
                # launching a different service instance, which may not be
                # spawn-safe, we need to re-evaluate its spawn-readiness and
                # accordingly select the manager context.
                # This ensures that if any of the worker service_instance is
                # not spawn-safe, we fallback to 'fork' start method.
                self._manager_context = _select_service_manager_context(
                    service_instance)
                self._manager.mp_context = self._manager_context
        # ServiceManager.add() is thread-safe, no need to hold lock
        self._manager.add(
            ServiceWrapper, workers, args=(service_instance,))

    def stop(self):
        with self._lock:
            if not self._manager:
                return
            manager = self._manager
        manager.shutdown()

    def wait(self):
        with self._lock:
            if not self._manager:
                return 0
            manager = self._manager
        try:
            return manager.run()
        except SystemExit as exc:
            self.stop()
            return exc.code
        except BaseException:
            self.stop()
            LOG.exception("Unhandled exception")
            return 2

    def restart(self):
        raise NotImplementedError()


class Service(ServiceBase):
    def __init__(self, threads=1000):
        super().__init__()
        self.tg = threadgroup.ThreadGroup(threads)
        self.backdoor_port = None

    def reset(self):
        pass

    def start(self):
        pass

    def stop(self, graceful=False):
        self.tg.stop(graceful)

    def wait(self):
        self.tg.waitall()


class Services:
    def __init__(self, restart_method='reload'):
        if restart_method not in _LAUNCHER_RESTART_METHODS:
            raise ValueError(_("Invalid restart_method: %s") % restart_method)
        self.restart_method = restart_method
        self.services = []
        self.tg = threadgroup.ThreadGroup()
        self.done = threading.Event()

    def add(self, service):
        self.services.append(service)
        self.tg.add_thread(self.run_service, service, self.done)

    def stop(self):
        for service in self.services:
            service.stop()
        if not self.done.is_set():
            self.done.set()
        self.tg.stop()

    def wait(self):
        for service in self.services:
            service.wait()
        self.tg.wait()

    def restart(self):
        if self.restart_method == 'reload':
            self.stop()
            self.done = threading.Event()

        for restart_service in self.services:
            restart_service.reset()
            if self.restart_method == 'reload':
                self.tg.add_thread(
                    self.run_service, restart_service, self.done)

    @staticmethod
    def run_service(service, done):
        try:
            service.start()
        except Exception:
            LOG.exception('Error starting service thread.')
            raise SystemExit(1)
        else:
            done.wait()


class ProcessLauncher:
    def __init__(
            self, conf, wait_interval=None, restart_method='reload',
            no_fork=False):
        self.conf = conf
        self.conf.register_opts(_options.service_opts)
        self.restart_method = restart_method
        self.no_fork = no_fork
        self._lock = threading.Lock()
        self._manager = None
        self._manager_context = None
        self.service = None
        self.signal_handler = None
        # NOTE(gmaan): If service is launched with no_fork=True that means
        # service is running in the main process, and we need to handle the
        # signals. In other cases, service processes are handled by the
        # cotyledon library which handles the signals for all worker
        # processes, so let's not override their signal handling.
        if self.no_fork:
            self.signal_handler = SignalHandler()
            self.add_signal_handlers()

        if wait_interval is not None:
            warnings.warn(
                "'wait_interval' is deprecated and has no effect in the "
                "'threading' backend. It is accepted only for compatibility "
                "reasons and will be removed.",
                category=DeprecationWarning,
            )

    def launch_service(self, service, workers=1):
        common_service.check_service_base(service)

        if self.no_fork:
            LOG.warning("no_fork=True: running service in main process")
            self.service = service
            self.service.start()
            self.service.wait()
            return

        # NOTE(gmaan): cotyledon.ServiceManager does not allow more than one
        # instance per application. There is use case where multiple services
        # can be launched at same time. To avoid any race condition, we need
        # lock while creating the ServiceManager.
        # For more detail, ref to the bug#2138840
        with self._lock:
            if self._manager is None:
                self._manager_context, self._manager = _get_service_manager(
                    service,
                    self.conf.graceful_shutdown_timeout,
                    self.conf,
                    self.restart_method,
                )
            else:
                # NOTE(gmaan): This case means services are launching the
                # multiple workers of the same or different service instances.
                # The first worker has initialized the cotyledon.ServiceManager
                # with the manager context based on whether their service
                # instance is spawn-safe or not. If the next worker is
                # launching a different service instance, which may not be
                # spawn-safe, we need to re-evaluate its spawn-readiness and
                # accordingly select the manager context.
                # This ensures that if any of the worker service_instance is
                # not spawn-safe, we fallback to 'fork' start method.
                self._manager_context = _select_service_manager_context(
                    service)
                self._manager.mp_context = self._manager_context
        # ServiceManager.add() is thread-safe, no need to hold lock
        self._manager.add(ServiceWrapper, workers, args=(service,))

    def _graceful_shutdown(self, *args):
        LOG.info('Graceful shutdown start')
        # At this time, first SIGTERM is caught and this handler started the
        # graceful shutdown. We need to ignore the another SIGTERM signal if
        # they comes during the graceful shutdown otherwise they will interupt
        # and race the already running graceful shutdown.
        self.signal_handler.ignore_handler('SIGTERM')
        # Register alarm signal with conf.graceful_shutdown_timeout.
        # If graceful shutdown is not finished within the
        # timeout, then alarm signal will exit the process.
        if (self.conf.graceful_shutdown_timeout and
                self.signal_handler.is_signal_supported('SIGALRM')):
            signal.alarm(self.conf.graceful_shutdown_timeout)
        self.service.stop()
        LOG.info('Graceful shutdown finish')
        os._exit(0)

    def _reload_service(self, *args):
        # TODO(gmaan): This handler is suppose to reload the service but we
        # need to implement the restart() method for no_fork case which can
        # call reset/restart on the service instance.
        self.signal_handler.clear()
        raise common_service.SignalExit(signal.SIGHUP)

    def _fast_exit(self, *args):
        LOG.info('Caught SIGINT signal, instantaneous exiting')
        os._exit(1)

    def _on_alarm_exit(self, *args):
        LOG.info('Graceful shutdown timeout exceeded, '
                 'instantaneous exiting')
        os._exit(1)

    def add_signal_handlers(self):
        """Add signal handlers."""
        self.signal_handler.clear()
        self.signal_handler.add_handler('SIGTERM', self._graceful_shutdown)
        self.signal_handler.add_handler('SIGINT', self._fast_exit)
        self.signal_handler.add_handler('SIGHUP', self._reload_service)
        self.signal_handler.add_handler('SIGALRM', self._on_alarm_exit)

    def wait(self):
        if self.no_fork:
            return 0
        with self._lock:
            if not self._manager:
                return 0
            manager = self._manager
        return manager.run()

    def stop(self):
        LOG.info("Stopping service")
        with self._lock:
            if not self._manager:
                return
            manager = self._manager
        manager.shutdown()

    def restart(self):
        raise NotImplementedError()


def launch(conf, service, workers=1, restart_method='reload', no_fork=False):
    """Launch a service with a given number of workers.

    :param conf: an instance of ConfigOpts
    :param service: a service to launch, must be an instance of
           :class:`oslo_service.service.ServiceBase`
    :param workers: a number of processes in which a service will be running,
        type should be int.
    :param restart_method: Passed to the constructed launcher. If 'reload', the
        launcher will call reload_config_files on SIGHUP. If 'mutate', it will
        call mutate_config_files on SIGHUP. Other values produce a ValueError.
    :param no_fork: Whether to allow forking or not. If True,
        :class:`~ProcessLauncher` will always be used.
    :returns: An instance of a launcher that was used to launch the service
    """
    if workers is not None and not isinstance(workers, int):
        raise TypeError("Type of workers should be int!")

    if workers is not None and workers <= 0:
        raise ValueError("Number of workers should be positive!")

    if workers == 1 and not no_fork:
        launcher = ServiceLauncher(conf, restart_method=restart_method)
    else:
        launcher = ProcessLauncher(
            conf, restart_method=restart_method, no_fork=no_fork)

    launcher.launch_service(service, workers=workers)

    return launcher
