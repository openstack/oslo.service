# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Generic Node base class for all workers that run on hosts.

This module provides two launchers for running services:

    * ServiceLauncher - used for running one or more service in
      a parent process.
    * ProcessLauncher - forks a given number of workers in which
      service(s) are then started.

Please be informed that it is highly recommended to use no more than
one instance of ServiceLauncher and ProcessLauncher classes per process.
"""

import abc
import copy
import errno
import io
import logging
import os
import random
import signal
import six
import sys
import time

import eventlet
from eventlet import event

from oslo_service import eventlet_backdoor
from oslo_service._i18n import _LE, _LI, _LW
from oslo_service import _options
from oslo_service import systemd
from oslo_service import threadgroup


LOG = logging.getLogger(__name__)


def list_opts():
    """Entry point for oslo-config-generator."""
    return [(None, copy.deepcopy(_options.eventlet_backdoor_opts +
                                 _options.service_opts))]


def _sighup_supported():
    return hasattr(signal, 'SIGHUP')


def _is_daemon():
    # The process group for a foreground process will match the
    # process group of the controlling terminal. If those values do
    # not match, or ioctl() fails on the stdout file handle, we assume
    # the process is running in the background as a daemon.
    # http://www.gnu.org/software/bash/manual/bashref.html#Job-Control-Basics
    try:
        is_daemon = os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno())
    except io.UnsupportedOperation:
        # Could not get the fileno for stdout, so we must be a daemon.
        is_daemon = True
    except OSError as err:
        if err.errno == errno.ENOTTY:
            # Assume we are a daemon because there is no terminal.
            is_daemon = True
        else:
            raise
    return is_daemon


def _is_sighup_and_daemon(signo):
    if not (_sighup_supported() and signo == signal.SIGHUP):
        # Avoid checking if we are a daemon, because the signal isn't
        # SIGHUP.
        return False
    return _is_daemon()


def _signo_to_signame(signo):
    signals = {signal.SIGTERM: 'SIGTERM',
               signal.SIGINT: 'SIGINT'}
    if _sighup_supported():
        signals[signal.SIGHUP] = 'SIGHUP'
    return signals[signo]


def _set_signals_handler(handler):
    signal.signal(signal.SIGTERM, handler)
    if _sighup_supported():
        signal.signal(signal.SIGHUP, handler)


@six.add_metaclass(abc.ABCMeta)
class ServiceBase(object):
    """Base class for all services."""

    @abc.abstractmethod
    def start(self):
        """Start service."""

    @abc.abstractmethod
    def stop(self):
        """Stop service."""

    @abc.abstractmethod
    def wait(self):
        """Wait for service to complete."""

    @abc.abstractmethod
    def reset(self):
        """Reset service.

        Called in case service running in daemon mode receives SIGHUP.
        """


class Launcher(object):
    """Launch one or more services and wait for them to complete."""

    def __init__(self, conf):
        """Initialize the service launcher.

        :returns: None

        """
        self.conf = conf
        conf.register_opts(_options.service_opts)
        self.services = Services()
        self.backdoor_port = (
            eventlet_backdoor.initialize_if_enabled(self.conf))

    def launch_service(self, service):
        """Load and start the given service.

        :param service: The service you would like to start.
        :returns: None

        """
        service.backdoor_port = self.backdoor_port
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

        :returns: None

        """
        self.conf.reload_config_files()
        self.services.restart()


class SignalExit(SystemExit):
    def __init__(self, signo, exccode=1):
        super(SignalExit, self).__init__(exccode)
        self.signo = signo


class ServiceLauncher(Launcher):
    """Runs one or more service in a parent process."""
    def __init__(self, conf):
        """Constructor.

        :param conf: an instance of ConfigOpts
        """
        super(ServiceLauncher, self).__init__(conf)

    def _handle_signal(self, signo, frame):
        """Set signal handlers and raise an exception.

        :param signo: signal number
        :param frame: current stack frame
        :raises SignalExit
        """
        # Allow the process to be killed again and die from natural causes
        _set_signals_handler(signal.SIG_DFL)
        raise SignalExit(signo)

    def handle_signal(self):
        """Set self._handle_signal as a signal handler."""
        _set_signals_handler(self._handle_signal)

    def _wait_for_exit_or_signal(self, ready_callback=None):
        status = None
        signo = 0

        if self.conf.log_options:
            LOG.debug('Full set of CONF:')
            self.conf.log_opt_values(LOG, logging.DEBUG)

        try:
            if ready_callback:
                ready_callback()
            super(ServiceLauncher, self).wait()
        except SignalExit as exc:
            signame = _signo_to_signame(exc.signo)
            LOG.info(_LI('Caught %s, exiting'), signame)
            status = exc.code
            signo = exc.signo
        except SystemExit as exc:
            status = exc.code
        finally:
            self.stop()

        return status, signo

    def wait(self, ready_callback=None):
        """Wait for a service to terminate and restart it on SIGHUP.

        :returns: termination status
        """
        systemd.notify_once()
        while True:
            self.handle_signal()
            status, signo = self._wait_for_exit_or_signal(ready_callback)
            if not _is_sighup_and_daemon(signo):
                return status
            self.restart()


class ServiceWrapper(object):
    def __init__(self, service, workers):
        self.service = service
        self.workers = workers
        self.children = set()
        self.forktimes = []


class ProcessLauncher(object):
    """Launch a service with a given number of workers."""
    _signal_handlers_set = set()

    @classmethod
    def _handle_class_signals(cls, *args, **kwargs):
        """Call all registered class handlers.

        That is needed in case there are multiple ProcessLauncher
        instances in one process.
        """
        for handler in cls._signal_handlers_set:
            handler(*args, **kwargs)

    def __init__(self, conf, wait_interval=0.01):
        """Constructor.

        :param conf: an instance of ConfigOpts
        :param wait_interval: The interval to sleep for between checks
                              of child process exit.
        """
        self.conf = conf
        conf.register_opts(_options.service_opts)
        self.children = {}
        self.sigcaught = None
        self.running = True
        self.wait_interval = wait_interval
        self.launcher = None
        rfd, self.writepipe = os.pipe()
        self.readpipe = eventlet.greenio.GreenPipe(rfd, 'r')
        self.handle_signal()

    def handle_signal(self):
        """Add instance's signal handlers to class handlers."""
        self._signal_handlers_set.add(self._handle_signal)
        _set_signals_handler(self._handle_class_signals)

    def _handle_signal(self, signo, frame):
        """Set signal handlers.

        :param signo: signal number
        :param frame: current stack frame
        """
        self.sigcaught = signo
        self.running = False

        # Allow the process to be killed again and die from natural causes
        _set_signals_handler(signal.SIG_DFL)

    def _pipe_watcher(self):
        # This will block until the write end is closed when the parent
        # dies unexpectedly
        self.readpipe.read(1)

        LOG.info(_LI('Parent process has died unexpectedly, exiting'))

        if self.launcher:
            self.launcher.stop()

        sys.exit(1)

    def _child_process_handle_signal(self):
        # Setup child signal handlers differently

        def _sigterm(*args):
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            self.launcher.stop()

        def _sighup(*args):
            signal.signal(signal.SIGHUP, signal.SIG_DFL)
            raise SignalExit(signal.SIGHUP)

        # Parent signals with SIGTERM when it wants us to go away.
        signal.signal(signal.SIGTERM, _sigterm)
        if _sighup_supported():
            signal.signal(signal.SIGHUP, _sighup)

    def _child_wait_for_exit_or_signal(self, launcher):
        status = 0
        signo = 0

        # NOTE(johannes): All exceptions are caught to ensure this
        # doesn't fallback into the loop spawning children. It would
        # be bad for a child to spawn more children.
        try:
            launcher.wait()
        except SignalExit as exc:
            signame = _signo_to_signame(exc.signo)
            LOG.info(_LI('Child caught %s, exiting'), signame)
            status = exc.code
            signo = exc.signo
        except SystemExit as exc:
            status = exc.code
        except BaseException:
            LOG.exception(_LE('Unhandled exception'))
            status = 2

        return status, signo

    def _child_process(self, service):
        self._child_process_handle_signal()

        # Reopen the eventlet hub to make sure we don't share an epoll
        # fd with parent and/or siblings, which would be bad
        eventlet.hubs.use_hub()

        # Close write to ensure only parent has it open
        os.close(self.writepipe)
        # Create greenthread to watch for parent to close pipe
        eventlet.spawn_n(self._pipe_watcher)

        # Reseed random number generator
        random.seed()

        launcher = Launcher(self.conf)
        launcher.launch_service(service)
        return launcher

    def _start_child(self, wrap):
        if len(wrap.forktimes) > wrap.workers:
            # Limit ourselves to one process a second (over the period of
            # number of workers * 1 second). This will allow workers to
            # start up quickly but ensure we don't fork off children that
            # die instantly too quickly.
            if time.time() - wrap.forktimes[0] < wrap.workers:
                LOG.info(_LI('Forking too fast, sleeping'))
                time.sleep(1)

            wrap.forktimes.pop(0)

        wrap.forktimes.append(time.time())

        pid = os.fork()
        if pid == 0:
            self.launcher = self._child_process(wrap.service)
            while True:
                self._child_process_handle_signal()
                status, signo = self._child_wait_for_exit_or_signal(
                    self.launcher)
                if not _is_sighup_and_daemon(signo):
                    self.launcher.wait()
                    break
                self.launcher.restart()

            os._exit(status)

        LOG.info(_LI('Started child %d'), pid)

        wrap.children.add(pid)
        self.children[pid] = wrap

        return pid

    def launch_service(self, service, workers=1):
        """Launch a service with a given number of workers.

       :param service: a service to launch, must be an instance of
              :class:`oslo_service.service.ServiceBase`
       :param workers: a number of processes in which a service
              will be running
        """
        wrap = ServiceWrapper(service, workers)

        LOG.info(_LI('Starting %d workers'), wrap.workers)
        while self.running and len(wrap.children) < wrap.workers:
            self._start_child(wrap)

    def _wait_child(self):
        try:
            # Don't block if no child processes have exited
            pid, status = os.waitpid(0, os.WNOHANG)
            if not pid:
                return None
        except OSError as exc:
            if exc.errno not in (errno.EINTR, errno.ECHILD):
                raise
            return None

        if os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            LOG.info(_LI('Child %(pid)d killed by signal %(sig)d'),
                     dict(pid=pid, sig=sig))
        else:
            code = os.WEXITSTATUS(status)
            LOG.info(_LI('Child %(pid)s exited with status %(code)d'),
                     dict(pid=pid, code=code))

        if pid not in self.children:
            LOG.warning(_LW('pid %d not in child list'), pid)
            return None

        wrap = self.children.pop(pid)
        wrap.children.remove(pid)
        return wrap

    def _respawn_children(self):
        while self.running:
            wrap = self._wait_child()
            if not wrap:
                # Yield to other threads if no children have exited
                # Sleep for a short time to avoid excessive CPU usage
                # (see bug #1095346)
                eventlet.greenthread.sleep(self.wait_interval)
                continue
            while self.running and len(wrap.children) < wrap.workers:
                self._start_child(wrap)

    def wait(self):
        """Loop waiting on children to die and respawning as necessary."""

        systemd.notify_once()
        if self.conf.log_options:
            LOG.debug('Full set of CONF:')
            self.conf.log_opt_values(LOG, logging.DEBUG)

        try:
            while True:
                self.handle_signal()
                self._respawn_children()
                # No signal means that stop was called.  Don't clean up here.
                if not self.sigcaught:
                    return

                signame = _signo_to_signame(self.sigcaught)
                LOG.info(_LI('Caught %s, stopping children'), signame)
                if not _is_sighup_and_daemon(self.sigcaught):
                    break

                self.conf.reload_config_files()
                for service in set(
                        [wrap.service for wrap in self.children.values()]):
                    service.reset()

                for pid in self.children:
                    os.kill(pid, signal.SIGHUP)

                self.running = True
                self.sigcaught = None
        except eventlet.greenlet.GreenletExit:
            LOG.info(_LI("Wait called after thread killed. Cleaning up."))

        self.stop()

    def stop(self):
        """Terminate child processes and wait on each."""
        self.running = False

        LOG.debug("Stop services.")
        for service in set(
                [wrap.service for wrap in self.children.values()]):
            service.stop()

        LOG.debug("Killing children.")
        for pid in self.children:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    raise

        # Wait for children to die
        if self.children:
            LOG.info(_LI('Waiting on %d children to exit'), len(self.children))
            while self.children:
                self._wait_child()


class Service(ServiceBase):
    """Service object for binaries running on hosts."""

    def __init__(self, threads=1000):
        self.tg = threadgroup.ThreadGroup(threads)

        # signal that the service is done shutting itself down:
        self._done = event.Event()

    def reset(self):
        """Reset a service in case it received a SIGHUP."""
        # NOTE(Fengqian): docs for Event.reset() recommend against using it
        self._done = event.Event()

    def start(self):
        """Start a service."""

    def stop(self, graceful=False):
        """Stop a service.

        :param graceful: indicates whether to wait for all threads to finish
               or terminate them instantly
        """
        self.tg.stop(graceful)
        self.tg.wait()
        # Signal that service cleanup is done:
        if not self._done.ready():
            self._done.send()

    def wait(self):
        """Wait for a service to shut down."""
        self._done.wait()


class Services(object):

    def __init__(self):
        self.services = []
        self.tg = threadgroup.ThreadGroup()
        self.done = event.Event()

    def add(self, service):
        """Add a service to a list and create a thread to run it.

        :param service: service to run
        """
        self.services.append(service)
        self.tg.add_thread(self.run_service, service, self.done)

    def stop(self):
        """Wait for graceful shutdown of services and kill the threads."""
        for service in self.services:
            service.stop()

        # Each service has performed cleanup, now signal that the run_service
        # wrapper threads can now die:
        if not self.done.ready():
            self.done.send()

        # reap threads:
        self.tg.stop()

    def wait(self):
        """Wait for services to shut down."""
        for service in self.services:
            service.wait()
        self.tg.wait()

    def restart(self):
        """Reset services and start them in new threads."""
        self.stop()
        self.done = event.Event()
        for restart_service in self.services:
            restart_service.reset()
            self.tg.add_thread(self.run_service, restart_service, self.done)

    @staticmethod
    def run_service(service, done):
        """Service start wrapper.

        :param service: service to run
        :param done: event to wait on until a shutdown is triggered
        :returns: None

        """
        service.start()
        done.wait()


def launch(conf, service, workers=1):
    """Launch a service with a given number of workers.

    :param conf: an instance of ConfigOpts
    :param service: a service to launch, must be an instance of
           :class:`oslo_service.service.ServiceBase`
    :param workers: a number of processes in which a service will be running
    :returns: instance of a launcher that was used to launch the service
    """
    if not isinstance(service, ServiceBase):
        raise TypeError("Service %(service)s must be subclass of %(base)s!"
                        % {'service': service, 'base': ServiceBase})
    if workers is None or workers == 1:
        launcher = ServiceLauncher(conf)
        launcher.launch_service(service)
    else:
        launcher = ProcessLauncher(conf)
        launcher.launch_service(service, workers=workers)

    return launcher
