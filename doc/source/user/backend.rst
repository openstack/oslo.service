==============
Backend System
==============

Introduction
============

The backend system in ``oslo.service`` provides a modular architecture
that allows you to choose between different concurrency models
without modifying your service logic.

Currently, two backends are implemented and supported:

- **Eventlet backend**: The traditional concurrency backend based on green
  threads and cooperative multitasking (`greenlet` library).
- **Threading backend**: A new backend using native Python threads, Cotyledon,
  and Futurist, designed to be compatible with modern Python versions,
  simplify debugging, and improve maintainability.

Why a Backend System?
=====================

This system was introduced to enable a
**gradual transition away from the Eventlet backend**, which has known
limitations for scaling, cooperative multitasking complexity, and debugging in
some Python environments. By using the backend system, you can test, adopt, or
migrate to the Threading backend while keeping the same public API and service
structure.

In the future, the Eventlet backend may be deprecated once the Threading
backend covers all use cases. Some related features tied to Eventlet,
like the embedded WSGI server and the backdoor shell, are also planned for
removal.

For more context, see:

- `Epoxy spec for Eventlet removal <https://specs.openstack.org/openstack/oslo-specs/specs/epoxy/remove-eventlet-from-oslo-service.html>`_
- `Eventlet removal guide <https://removal.eventlet.org/>`_
- `OpenStack Eventlet removal goal <https://governance.openstack.org/tc/goals/selected/remove-eventlet.html>`_

How It Works
============

The backend system exposes the same **public components**
(``ServiceLauncher``, ``ProcessLauncher``, ``ThreadGroup``,
``LoopingCall``, etc.) through a dynamic selection mechanism.

At runtime, you select the backend you want to use by calling the
``init_backend()`` function and providing the desired ``BackendType``:

.. code-block:: python

   from oslo_service.backend import init_backend, BackendType

   # Use the Threading backend
   init_backend(BackendType.THREADING)

If you do not explicitly initialize a backend, the system will
use the **Eventlet** backend by default.

Once the backend is initialized, it **cannot be changed**.
Trying to re-initialize it will raise a ``BackendAlreadySelected`` exception.

If you see this exception, ensure that your backend is initialized only once
early during your application startup (for example in your main() entry point).
Avoid calling ``init_backend()`` in shared libraries or multiple times.
If you need to reset the backend in unit tests, use the ``_reset_backend()``
helper to clear the backend cache:

.. code-block:: python

   from oslo_service.backend import _reset_backend

   _reset_backend()

How to Select a Backend
========================

There are two supported ways to select which backend to use:

1. **Explicit initialization**

   Call ``init_backend()`` early in your application entry point:

   .. code-block:: python

      from oslo_service.backend import init_backend, BackendType

      init_backend(BackendType.THREADING)

   This will load the Threading backend and cache its components.

   For practical usage, see how Nova does it:
   https://review.opendev.org/c/openstack/nova/+/948311

2. **Dynamic hook**

   You may register a Python hook to dynamically decide the backend
   if ``init_backend()`` is not called:

   .. code-block:: python

      from oslo_service.backend \
          import register_backend_default_hook, BackendType

      def my_backend_decider():
          # Add custom logic here if needed
          return BackendType.THREADING

      register_backend_default_hook(my_backend_decider)

   If no explicit backend is set, the system will call your hook
   to decide which backend to load.

.. note::
   There is **no automatic oslo.config option** for ``service_backend``.
   If you want to make the backend configurable through your application's
   config file, you need to define and parse that option yourself, then
   call ``init_backend()`` with the selected value.

Accessing Backend Components
============================

Once the backend is initialized, you can access its components
via the ``get_component()`` helper function.

Example: getting a ``ProcessLauncher`` instance:

.. code-block:: python

   from oslo_service.backend import get_component

   ProcessLauncher = get_component("ProcessLauncher")

   launcher = ProcessLauncher(conf)
   launcher.launch_service(my_service)
   launcher.wait()

Available components include:

- ``ServiceLauncher``
- ``ProcessLauncher``
- ``ThreadGroup``
- ``LoopingCall`` variants
- ``SignalHandler``
- And other related service utilities

If you try to access a component that does not exist
in the current backend, a ``KeyError`` will be raised.

Example Usage
=============

Here is a minimal example that shows how to initialize the Threading backend
and launch a service:

.. code-block:: python

   from oslo_service.backend import (
       init_backend,
       get_component,
       BackendType
   )

   def main():
       # Select the Threading backend
       init_backend(BackendType.THREADING)

       # Get the ProcessLauncher component
       ProcessLauncher = get_component("ProcessLauncher")

       # Initialize your service and launch it
       launcher = ProcessLauncher(conf)
       launcher.launch_service(my_service)
       launcher.wait()

   if __name__ == "__main__":
       main()

Understanding the Implications of Migrating from Eventlet to Threading
======================================================================

The following table is not about choosing a backend, but about understanding
the implications of migrating away from Eventlet to the Threading backend:

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Compared Aspect
     - Eventlet Backend
     - Threading Backend
   * - Concurrency model
     - Cooperative multitasking using green threads (`greenlet`)
     - Native Python threads (preemptive)
   * - Process management
     - Uses built-in eventlet processes
     - Uses Cotyledon for multi-process support
   * - Looping calls
     - Uses eventlet green thread pools
     - Uses Futurist thread pools
   * - Embedded WSGI server
     - Provided (with eventlet)
     - Planned for removal; use an external WSGI server instead
   * - Backdoor shell
     - Provided (eventlet only)
     - Planned for removal
   * - API compatibility
     - Same public API
     - Same public API
   * - Debugging
     - More complex due to cooperative multitasking and green threads.
       See `eventlet_backdoor.py <https://opendev.org/openstack/oslo.service/src/branch/master/oslo_service/eventlet_backdoor.py>`_
     - May produce clearer native thread stack traces and benefits
       from recent CPython improvements (e.g. PEP 768).
   * - Python compatibility
     - Known issues with CPython native threads and RLocks.
       May break with new Python versions.
     - Fully compatible with modern CPython threading.

Test Setup in Devstack and CI Gates
====================================

If you want to test the Threading backend in Devstack or your CI gates,
refer to:

- https://review.opendev.org/c/openstack/devstack/+/948436
- https://gibizer.github.io/posts/Eventlet-Removal-Scheduler-First-Run/
- https://review.opendev.org/c/openstack/devstack/+/948408

References
==========

- `Eventlet removal guide <https://removal.eventlet.org/>`_
- `Epoxy spec for oslo.service <https://specs.openstack.org/openstack/oslo-specs/specs/epoxy/remove-eventlet-from-oslo-service.html>`_
- `Eventlet removal goal <https://governance.openstack.org/tc/goals/selected/remove-eventlet.html>`_

For any questions, please refer to the OpenStack mailing list
or the oslo.service maintainers.
