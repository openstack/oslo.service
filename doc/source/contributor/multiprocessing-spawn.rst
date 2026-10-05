==============================
Multiprocessing Spawn Strategy
==============================

This page is for contributors maintaining oslo.service launchers and parallel
periodic tasks. It describes the design choices and process-boundary
constraints to preserve when changing these components. Application migration
procedures are outside its scope.

Design rationale
================

Spawn starts a fresh interpreter, avoiding lock state inherited from a threaded
parent through fork. This also means workers need explicit initialization;
successful serialization alone does not establish that a service works with
spawn.

Use local multiprocessing contexts so library code does not change the
application-wide start method. The module documentation in
``oslo_service/_multiprocessing.py`` explains the fork-related risks and the
reason for using local contexts in detail.

Current behavior and scope
==========================

Parallel periodic tasks use spawn-based pools and require the threading
backend. Threading launchers manage service processes through Cotyledon,
separately from these pools. They retain fork by default where available;
services can opt into spawn with ``start_method="spawn"`` after validating
worker initialization. Where fork is unavailable, they use spawn.

Keep these process boundaries distinct when changing either execution path.
Selecting a context for one path must not change the application's global
multiprocessing start method.

Using the internal helpers
==========================

For internal pool-based work, use ``get_spawn_pool()`` from
``oslo_service._multiprocessing``. Use ``get_spawn_context()`` when creating
related synchronization or communication objects. These helpers are internal
to oslo.service, not a public application API; their docstrings describe the
parameters.

For example, save the following as an importable Python file and execute it
as a script. Both worker functions are defined at module scope; creating the
pool is protected by the main guard.

.. code-block:: python

   import logging

   from oslo_service._multiprocessing import get_spawn_pool


   def initialize_worker(level):
       logging.basicConfig(level=level)


   def square(value):
       return value * value


   if __name__ == "__main__":
       with get_spawn_pool(
           processes=2,
           initializer=initialize_worker,
           init_args=(logging.INFO,),
           max_tasks_per_child=100,
       ) as pool:
           print(pool.map(square, [1, 2, 3]))

The blocking ``map`` completes before the context manager exits. For
asynchronous work, collect results before leaving the context, or explicitly
``close()`` and ``join()`` the pool after submission. Create related queues,
events and locks from the same spawn context; objects from a fork context
may be incompatible.

Worker boundaries and validation
================================

When changing spawn-based execution, preserve these constraints:

* Define workers in importable modules and avoid import-time process creation.
  Protect executable entry points with ``if __name__ == "__main__":``.
* Transfer serializable data across process boundaries. Recreate runtime
  resources such as locks and client connections in the worker.
* Initialize worker-local configuration, logging and clients explicitly.
  Parent-only changes to module globals are not reproduced by spawn. Ensure
  worker imports select the intended backend before importing
  backend-dependent oslo.service components.
* Do not rely on changes to a task instance or context in a child being copied
  back to the parent. Persist intended task effects explicitly.
* Test actual child startup, task effects, shutdown and restart behavior,
  rather than serialization alone. Consider startup and memory costs when
  choosing pool size and worker recycling.

Use the helper, threading launcher and periodic task tests to validate changes
across these boundaries. The functional fork-safety regressions run with
``tox -e py313-threading``.

References
==========

* `Python multiprocessing documentation
  <https://docs.python.org/3/library/multiprocessing.html>`_: contexts,
  start methods and programming guidelines.
