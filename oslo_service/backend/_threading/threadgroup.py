# Copyright (C) 2025 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
import threading
import time
import warnings

from oslo_service.backend._threading import loopingcall

LOG = logging.getLogger(__name__)


class Thread:
    """A simple wrapper around native threads.

        This class mimics the eventlet Thread interface (stop, wait, link,
        cancel) for compatibility with oslo.service consumers. The methods
        `stop`, `link`, and `cancel` are implemented as no-ops in the threading
        backend since native Python threads do not support these operations
        natively.
    """

    def __init__(self, thread, group=None, link=True):
        self.thread = thread
        self._ident = thread.ident
        self.group = group
        # Optionally, support for a link callback can be added here.

    @property
    def ident(self):
        return self._ident

    def stop(self):
        # These methods are no-ops in the threading backend because native
        # Python threads cannot be forcefully stopped or cancelled once
        # started. They are kept here to preserve API compatibility with the
        # eventlet backend, where these methods are implemented.
        pass

    def wait(self):
        self.thread.join()

    def link(self, func, *args, **kwargs):
        # Optionally schedule a callback after thread completion.
        pass

    def cancel(self, *throw_args):
        # Optionally implement cancellation if required.
        pass


class ThreadGroup:
    """A group of threads and timers similar to eventlet's GreenPool."""

    def __init__(self, max_threads=1000):
        self.max_threads = max_threads
        self.threads = []
        self.timers = []
        self._lock = threading.Lock()

    def __getstate__(self):
        # Exclude _lock from pickling.
        state = self.__dict__.copy()
        if '_lock' in state:
            del state['_lock']
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Recreate the lock after unpickling.
        self._lock = threading.Lock()

    def add_timer(self, delay, callback, *args, **kwargs):
        if args or kwargs:
            warnings.warn(
                "Calling add_timer() with arguments is deprecated. Use "
                "add_timer_args() instead.",
                DeprecationWarning
            )
        new_args = list(args)
        if new_args and new_args[0] == delay:
            new_args = new_args[1:]
        return self.add_timer_args(delay, callback, new_args, kwargs)

    def add_timer_args(self, interval, callback, args=None, kwargs=None,
                       initial_delay=None, stop_on_exception=True):
        args = args or []
        kwargs = kwargs or {}
        pulse = loopingcall.FixedIntervalLoopingCall(
            callback, *args, **kwargs)
        pulse.start(interval=interval,
                    initial_delay=initial_delay,
                    stop_on_exception=stop_on_exception)
        self._set_attr(pulse, '_running', True)
        pulse.args = tuple(args)
        pulse.kw = kwargs
        with self._lock:
            self.timers.append(pulse)
        return pulse

    def add_dynamic_timer(self, callback, initial_delay, periodic_interval_max,
                          *args, **kwargs):
        warnings.warn(
            "Calling add_dynamic_timer() with arguments is deprecated. Use "
            "add_dynamic_timer_args() instead.",
            DeprecationWarning
        )
        return self.add_dynamic_timer_args(
            callback, list(args), kwargs, initial_delay=initial_delay,
            periodic_interval_max=periodic_interval_max)

    def add_dynamic_timer_args(self, callback, args=None, kwargs=None,
                               initial_delay=None, periodic_interval_max=None,
                               stop_on_exception=True):
        args = args or []
        kwargs = kwargs or {}
        timer = loopingcall.DynamicLoopingCall(callback, *args, **kwargs)
        timer.start(initial_delay=initial_delay,
                    periodic_interval_max=periodic_interval_max,
                    stop_on_exception=stop_on_exception)
        self._set_attr(timer, '_running', True)
        timer.args = tuple(args)
        timer.kw = kwargs
        with self._lock:
            self.timers.append(timer)
        return timer

    def add_thread(self, callback, *args, **kwargs):
        with self._lock:
            if len(self.threads) >= self.max_threads:
                raise RuntimeError("Maximum number of threads reached")

            t = threading.Thread(target=callback, args=args, kwargs=kwargs)
            t.args = args
            t.kw = kwargs

            self.threads.append(t)

        t.start()
        return Thread(t, group=self)

    def thread_done(self, thread):
        with self._lock:
            try:
                self.threads.remove(
                    thread.thread if isinstance(thread, Thread) else thread)
            except ValueError:
                pass

    def timer_done(self, timer):
        with self._lock:
            try:
                self.timers.remove(timer)
            except ValueError:
                pass

    def cancel(self, *throw_args, **kwargs):
        pass

    def stop_timers(self):
        with self._lock:

            for timer in self.timers:
                timer.stop()

            self.timers = []

    def stop(self, graceful=False):
        self.stop_timers()

        if graceful:
            self._wait_threads()
        else:
            self._stop_threads()
            time.sleep(0.05)

    def _stop_threads(self):
        current = threading.current_thread()

        with self._lock:
            for t in self.threads:
                if t is not current and hasattr(t, "abort"):
                    t.abort.set()

            self.threads = [t for t in self.threads if t is current]

    def _wait_threads(self):
        current = threading.current_thread()

        with self._lock:
            for t in self.threads:
                if t is not current:
                    try:
                        t.join()
                    except Exception:
                        LOG.exception('Error waiting on thread.')

            self.threads = [t for t in self.threads if t is current]

    def waitall(self):
        """Block until all timers and threads in the group are complete.

        """
        with self._lock:
            threads_copy = list(self.threads)
            timers_copy = list(self.timers)

        for t in threads_copy:
            t.join()

        for timer in timers_copy:
            timer.wait()

    # NOTE(tkajinam): To keep interface consistent with eventlet version
    wait = waitall

    def _set_attr(self, obj, attr, value):
        try:
            object.__setattr__(obj, attr, value)
        except Exception:
            if hasattr(obj, '__dict__'):
                obj.__dict__[attr] = value
