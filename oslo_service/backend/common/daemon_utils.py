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
