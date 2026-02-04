# Copyright (C) 2026 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import threading
import time
from unittest import TestCase

from oslo_service.backend._threading import threadgroup


class ThreadGroupThreadDoneTestCase(TestCase):
    """Tests that thread_done() is called when threads finish (threading)."""

    def test_thread_done_called_when_thread_finishes(self):
        """Completed threads are removed from the group via thread_done()."""
        tg = threadgroup.ThreadGroup(max_threads=10)
        self.addCleanup(tg.stop)

        def noop():
            pass

        th = tg.add_thread(noop)
        th.wait()
        # After thread finishes, thread_done() removes it from the list
        with tg._lock:
            self.assertNotIn(th.thread, tg.threads)
        self.assertEqual(len(tg.threads), 0)

    def test_thread_done_called_when_thread_raises(self):
        """thread_done() is called in finally even when callback raises."""
        tg = threadgroup.ThreadGroup(max_threads=10)
        self.addCleanup(tg.stop)

        def raise_error():
            raise ValueError("expected")

        th = tg.add_thread(raise_error)
        th.wait()  # join() completes when thread exits (after finally)
        with tg._lock:
            self.assertNotIn(th.thread, tg.threads)
        self.assertEqual(len(tg.threads), 0)

    def test_multiple_threads_removed_after_completion(self):
        """Multiple threads are all removed when they complete."""
        tg = threadgroup.ThreadGroup(max_threads=10)
        self.addCleanup(tg.stop)

        done = threading.Event()
        count = [0]

        def worker():
            count[0] += 1
            done.wait()

        threads = [tg.add_thread(worker) for _ in range(3)]
        with tg._lock:
            self.assertEqual(len(tg.threads), 3)
        done.set()
        for t in threads:
            t.wait()
        with tg._lock:
            self.assertEqual(len(tg.threads), 0)
        self.assertEqual(count[0], 3)

    def test_waitall_completes_without_deadlock(self):
        """waitall() does not deadlock when threads call thread_done()."""
        tg = threadgroup.ThreadGroup(max_threads=10)
        self.addCleanup(tg.stop)

        def short_task():
            time.sleep(0.01)

        for _ in range(3):
            tg.add_thread(short_task)
        tg.waitall()
        with tg._lock:
            self.assertEqual(len(tg.threads), 0)
