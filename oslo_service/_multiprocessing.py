# Copyright (C) 2025 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


"""Utilities for multiprocessing using the ``spawn`` start method.

This module provides two helpers:

* ``get_spawn_context()`` — return a multiprocessing context configured to
  use the ``spawn`` start method.
* ``get_spawn_pool()`` — create a ``Pool`` instance from this context.

These helpers allow oslo.service to safely use multiprocessing without relying
on the interpreter-wide ``set_start_method()``. This is a critical distinction:

Why not call ``set_start_method('spawn')`` globally?
---------------------------------------------------
``multiprocessing.set_start_method()`` can only be invoked **once per Python
interpreter**, and attempting to set it a second time will raise a
``RuntimeError``. More importantly, setting the method globally can interfere
with other components of OpenStack that also interact with multiprocessing,
including cotyledon, eventlet shims, or other subsystems that may require
different semantics.

Instead, we rely on ``multiprocessing.get_context('spawn')`` which returns a
*local, isolated multiprocessing context* that uses ``spawn`` **without**
modifying the global start method. This design is safer and avoids conflicts
between libraries while ensuring spawn-based semantics everywhere this module
is used.

Why ``spawn``?
--------------
Using ``spawn`` prevents deadlocks inherited from ``fork``, especially when
the parent process holds Python or C-level locks (e.g. logging locks, I/O
locks, or any lock held by threads). Forking while locks are held can result
in children inheriting these locked states and blocking indefinitely. This
issue is well-documented in:

* https://pythonspeed.com/articles/python-multiprocessing/
* The CPython issue tracker and Python documentation on multiprocessing.

By enforcing ``spawn`` in a controlled, local manner, oslo.service avoids these
deadlocks while remaining compatible with threaded runtimes and future
removal of eventlet.

Usage example:
--------------

.. code-block:: python

    from oslo_service._multiprocessing import get_spawn_pool

    # Safe spawn-based pool
    with get_spawn_pool(processes=4) as pool:
        results = pool.map(func, items)

This module performs no side-effects at import time and does not alter
global multiprocessing state.
"""


import multiprocessing
from multiprocessing.context import SpawnContext
from multiprocessing.pool import Pool

from collections.abc import Callable

__all__ = ("get_spawn_context", "get_spawn_pool")


def get_spawn_context() -> SpawnContext:
    """Get a multiprocessing context using the 'spawn' start method.

    This function returns a multiprocessing context that uses the 'spawn'
    start method, which avoids fork-inherited lock deadlocks by starting
    fresh processes without inheriting locks from the parent process.

    :returns: A multiprocessing context with start method set to 'spawn'
    """
    return multiprocessing.get_context('spawn')


def get_spawn_pool(
    processes: int | None = None,
    initializer: Callable | None = None,
    init_args: tuple = (),
    max_tasks_per_child: int | None = None,
) -> Pool:
    """Get a multiprocessing pool created with the 'spawn' start method.

    This function creates a multiprocessing pool using the 'spawn' start
    method, which avoids fork-inherited lock deadlocks. All parameters are
    passed through to the underlying Pool constructor.

    :param processes: The number of worker processes to use. If None, the
                      Pool will use the number returned by
                      os.process_cpu_count()
                      (or os.cpu_count() on older Python versions).
    :param initializer: If not None, each worker process will call
                       initializer(*init_args) when it starts.
    :param init_args: Arguments to be passed to the initializer.
    :param max_tasks_per_child: The number of tasks a worker process can
                               complete before it will exit and be replaced
                               with a fresh worker process, to enable unused
                               resources to be freed.
    :returns: A multiprocessing pool created with the 'spawn' start method
    """
    context = get_spawn_context()
    return context.Pool(
        processes=processes,
        initializer=initializer,
        initargs=init_args,
        maxtasksperchild=max_tasks_per_child
    )
