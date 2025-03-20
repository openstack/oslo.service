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

import errno
import io
import os
import signal
import sys

from oslo_concurrency import lockutils

from oslo_service._i18n import _
from oslo_service.backend.base import ServiceBase


def is_daemon():
    try:
        return os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno())
    except io.UnsupportedOperation:
        return True
    except OSError as err:
        return err.errno == errno.ENOTTY or False


def is_sighup_and_daemon(signo, signal_handler):
    return (signal_handler.is_signal_supported('SIGHUP') and
            signo == signal.SIGHUP and is_daemon())


def get_signal_mappings():
    signals_by_name = {
        name: getattr(signal, name)
        for name in dir(signal)
        if name.startswith('SIG') and
        isinstance(getattr(signal, name), signal.Signals)
    }
    signals_to_name = {v: k for k, v in signals_by_name.items()}

    return signals_by_name, signals_to_name


class SignalExit(SystemExit):
    """Raised to indicate a signal-based exit.

    This exception is commonly raised when the process receives a termination
    signal (e.g., SIGTERM, SIGINT). The signal number is stored in `signo`.
    """

    def __init__(self, signo, exccode=1):
        super().__init__(exccode)
        self.signo = signo


def check_service_base(service):
    if not isinstance(service, ServiceBase):
        raise TypeError(
            _("Service %(service)s must be an instance of %(base)s!")
            % {'service': service, 'base': ServiceBase})


class Singleton(type):
    _instances = {}
    _semaphores = lockutils.Semaphores()

    def __call__(cls, *args, **kwargs):
        with lockutils.lock('singleton_lock', semaphores=cls._semaphores):
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
