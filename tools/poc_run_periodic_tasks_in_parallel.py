#!/usr/bin/env python3
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

# Proof-of-concept for PeriodicTasks.run_periodic_tasks_in_parallel().
#
# Requirements (see periodic_task and release notes):
# - **Threading** backend only (not eventlet): init_backend(THREADING).
# - The PeriodicTasks instance and **context** must be picklable for
#   ForkingPickler / spawn. No lambdas; avoid local classes for fragile entry
#   points — here everything is module-level so workers can unpickle it.
#
# Usage (from repo root, with project venv / install):
#   python tools/poc_run_periodic_tasks_in_parallel.py
#
# Service-style integration: call periodically (e.g. via
# tg.add_dynamic_timer) run_periodic_tasks_in_parallel(ctx, processes=N)
# instead of run_periodic_tasks() when you want due tasks to run in parallel
# without fork-inherited locks (spawn pool).

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time

from oslo_service.backend import BackendType
from oslo_service.backend import init_backend
from oslo_service import periodic_task

LOG = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [pid=%(process)d] %(message)s",
    )


class PicklablePocConf:
    """Minimal conf for spawn: a full ``cfg.ConfigOpts()`` is not picklable."""

    run_external_periodic_tasks = False

    def register_opts(self, opts):
        # PeriodicTasks.__init__ registers periodic_opts; no Oslo Config
        # needed.
        pass


class DemoPeriodicTasks(periodic_task.PeriodicTasks):
    """Module-level subclass: required for spawn worker pickling."""

    def __init__(self, conf: PicklablePocConf) -> None:
        super().__init__(conf)
        # Do not rely on self.* mutated in workers: each process gets its own
        # unpickled copy of self.
        self.sleep_seconds = 0.4

    @periodic_task.periodic_task(spacing=60, run_immediately=True)
    def task_alpha(self, context: dict) -> None:
        path = context["marker_file"]
        pid = os.getpid()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"alpha start pid={pid} t={time.monotonic():.3f}\n")
            f.flush()
        time.sleep(self.sleep_seconds)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"alpha end   pid={pid} t={time.monotonic():.3f}\n")
            f.flush()
        LOG.info("task_alpha done in worker pid=%s", pid)

    @periodic_task.periodic_task(spacing=60, run_immediately=True)
    def task_beta(self, context: dict) -> None:
        path = context["marker_file"]
        pid = os.getpid()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"beta start pid={pid} t={time.monotonic():.3f}\n")
            f.flush()
        time.sleep(self.sleep_seconds)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"beta end   pid={pid} t={time.monotonic():.3f}\n")
            f.flush()
        LOG.info("task_beta done in worker pid=%s", pid)

    @periodic_task.periodic_task(spacing=60, run_immediately=True)
    def task_gamma(self, context: dict) -> None:
        path = context["marker_file"]
        pid = os.getpid()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"gamma start pid={pid} t={time.monotonic():.3f}\n")
            f.flush()
        time.sleep(self.sleep_seconds)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"gamma end   pid={pid} t={time.monotonic():.3f}\n")
            f.flush()
        LOG.info("task_gamma done in worker pid=%s", pid)


def main() -> int:
    _configure_logging()

    # Required for run_periodic_tasks_in_parallel.
    init_backend(BackendType.THREADING)

    marker = os.path.join(
        tempfile.gettempdir(), "oslo_service_poc_parallel_periodic.txt")
    if os.path.exists(marker):
        os.remove(marker)

    manager = DemoPeriodicTasks(PicklablePocConf())
    context: dict = {"marker_file": marker}

    LOG.info(
        "Parent pid=%s: running 3 due periodic tasks in parallel "
        "(processes=3). Sequential wall time ~ %.1fs; parallel ~ %.1fs.",
        os.getpid(),
        3 * manager.sleep_seconds,
        manager.sleep_seconds,
    )
    t0 = time.monotonic()
    idle = manager.run_periodic_tasks_in_parallel(context, processes=3)
    elapsed = time.monotonic() - t0
    LOG.info(
        "run_periodic_tasks_in_parallel finished in %.2fs, idle_for=%s",
        elapsed, idle)

    with open(marker, encoding="utf-8") as f:
        lines = f.read().strip().splitlines()

    print(
        "\n--- Marker file (overlapping 'start' lines indicate "
        "parallelism) ---")
    for line in lines:
        print(line)
    print("--- end ---\n")

    pids = {
        line.split("pid=")[1].split()[0]
        for line in lines
        if "pid=" in line
    }
    parent = str(os.getpid())
    workers = pids - {parent}
    print(f"Worker PIDs seen: {sorted(workers)}")
    secs = manager.sleep_seconds
    print(
        f"If at least 2 distinct workers and elapsed ~ {secs:.1f}s, "
        "the POC demonstrates spawn parallelism.\n")

    # Simple heuristic for manual / scripted exit code
    if elapsed < (2 * manager.sleep_seconds) and len(workers) >= 2:
        return 0
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
