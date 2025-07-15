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
import signal
import sys
import threading
import traceback
import warnings

import cotyledon
from cotyledon import oslo_config_glue

from oslo_service._i18n import _
from oslo_service.backend._common.constants import _LAUNCHER_RESTART_METHODS
from oslo_service.backend._common.service \
    import check_service_base as _check_service_base
from oslo_service.backend._common.service import get_signal_mappings
from oslo_service.backend._common.service import Singleton
from oslo_service.backend._threading import threadgroup
from oslo_service.backend.base import ServiceBase

LOG = logging.getLogger(__name__)


class SignalHandler(metaclass=Singleton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._signals_by_name, self.signals_to_name = get_signal_mappings()
        self._signal_handlers = collections.defaultdict(list)
        self.clear()

    def clear(self):
        for sig in list(self._signal_handlers.keys()):
            signal.signal(sig, signal.SIG_DFL)
        self._signal_handlers.clear()

    def add_handlers(self, signals, handler):
        for sig in signals:
            self.add_handler(sig, handler)

    def add_handler(self, sig, handler):
        if not self.is_signal_supported(sig):
            return
        signo = self._signals_by_name[sig]
        self._signal_handlers[signo].append(handler)
        signal.signal(signo, self._handle_signal)

    def _handle_signal(self, signo, frame):
        threading.Thread(target=self._handle_signal_cb,
                         args=(signo, frame)).start()

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
    def __init__(self):
        self._launcher = None

    def launch_service(self, service, workers=None):
        _check_service_base(service)
        if workers not in (None, 1):
            raise NotImplementedError("Multiple workers is not supported.")
        self._launcher = service
        service.start()
        return service

    def wait(self):
        if self._launcher:
            self._launcher.wait()

    def stop(self):
        if self._launcher:
            self._launcher.stop()

    def restart(self):
        if self._launcher:
            self._launcher.stop()
            self._launcher.start()


class ServiceLauncher:
    def __init__(self, conf, restart_method='reload'):
        self.conf = conf
        self.restart_method = restart_method
        self.backdoor_port = None
        self._manager = cotyledon.ServiceManager()
        oslo_config_glue.setup(self._manager, conf)

    def launch_service(self, service_instance, workers=1):
        _check_service_base(service_instance)
        service_instance.backdoor_port = self.backdoor_port
        if not isinstance(workers, int) or workers < 1:
            raise ValueError("Number of workers must be >= 1")
        self._manager.add(ServiceWrapper, workers, args=(service_instance,))

    def stop(self):
        self._manager.shutdown()

    def wait(self):
        try:
            return self._manager.run()
        except SystemExit as exc:
            self.stop()
            return exc.code
        except BaseException:
            self.stop()
            LOG.exception("Unhandled exception")
            return 2


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
        self.restart_method = restart_method
        self.no_fork = no_fork
        self._manager = None

        if wait_interval is not None:
            warnings.warn(
                "'wait_interval' is deprecated and has no effect in the"
                " 'threading' backend. It is accepted only for compatibility"
                " reasons and will be removed.",
                category=DeprecationWarning,
            )

    def launch_service(self, service, workers=1):
        _check_service_base(service)

        if self.no_fork:
            LOG.warning("no_fork=True: running service in main process")
            service.start()
            service.wait()
            return

        if self._manager is None:
            self._manager = cotyledon.ServiceManager()
            oslo_config_glue.setup(self._manager, self.conf)

        self._manager.add(ServiceWrapper, workers, args=(service,))

    def wait(self):
        if self.no_fork:
            return 0
        return self._manager.run()

    def stop(self):
        LOG.info("Stopping service")
        if self._manager:
            self._manager.shutdown()


def launch(conf, service, workers=1, restart_method='reload', no_fork=False):
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
