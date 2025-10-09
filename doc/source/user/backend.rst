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

- `Epoxy spec for Eventlet removal`_
- `Eventlet removal guide <https://removal.eventlet.org/>`_
- `OpenStack Eventlet removal goal`_

How It Works
============

The backend system exposes the same **public components**
(``ServiceLauncher``, ``ProcessLauncher``, ``ThreadGroup``,
``LoopingCall``, etc.) through a dynamic selection mechanism.

At runtime, you can select the backend you want to use in two ways:

1. **Explicit initialization** by calling ``init_backend()`` with the desired
   ``BackendType``:

   .. code-block:: python

      from oslo_service.backend import init_backend, BackendType

      # Use the Threading backend
      init_backend(BackendType.THREADING)

2. **Dynamic selection** using a hook function that decides which backend
   to use:

   .. code-block:: python

      from oslo_service.backend import register_backend_default_hook, \
          BackendType

      def my_backend_decider():
          # Add custom logic here
          return BackendType.THREADING

      register_backend_default_hook(my_backend_decider)

If no backend is explicitly initialized, the system will use the **Eventlet**
backend by default, unless a hook has been registered to override this choice.

Once the backend is initialized, it **cannot be changed**.
Trying to re-initialize it with a different backend will raise a
``BackendAlreadySelected`` exception.

If you see this exception, ensure that your backend is initialized only once
early during your application startup (for example in your main() entry point).
Avoid calling ``init_backend()`` in shared libraries or multiple times.
If you need to reset the backend in unit tests, use the ``_reset_backend()``
helper to clear the backend cache:

.. code-block:: python

   from oslo_service.backend import _reset_backend

   _reset_backend()

Backend Selection Mechanism
===========================

The backend system uses a sophisticated caching and selection mechanism to
ensure efficient and consistent backend selection throughout your application
lifecycle.

**Core Functions:**

- **``init_backend(type_: BackendType)``**: Explicitly initializes and caches
  a specific backend. This function loads the backend module, instantiates
  the backend class, and caches both the backend instance and its components.
  Once called, the backend cannot be changed to a different type.

- **``get_backend()``**: Returns the currently cached backend instance. If no
  backend has been explicitly initialized, it follows this selection process:

  1. If a hook is registered, calls the hook to determine the backend type
  2. If the hook raises an exception, falls back to the default backend
     (Eventlet)
  3. If no hook is registered, uses the default backend (Eventlet)
  4. Initializes the selected backend and returns it

- **``register_backend_default_hook(hook: Callable[[], BackendType])``**:
  Registers a callback function that decides which backend to use when no
  explicit initialization has occurred. The hook function should return a
  ``BackendType`` and will be called by ``get_backend()`` when needed.

- **``get_component(name: str)``**: Retrieves a specific component from the
  cached backend. This is the primary way to access backend-specific
  implementations of service components.

**Backend Caching:**

The system maintains four global caches:

- ``_cached_backend_type``: The selected backend type
- ``_cached_backend``: The instantiated backend object
- ``_cached_components``: Dictionary of available components from the backend
- ``_backend_hook``: The registered hook function for dynamic backend selection

**Backend Loading Process:**

When a backend is initialized, the following steps occur:

1. **Module Import**: The backend module is dynamically imported using
   ``importlib.import_module()``
2. **Class Instantiation**: The backend class (e.g., ``EventletBackend``,
   ``ThreadingBackend``) is instantiated
3. **Component Caching**: All available components are retrieved and cached
4. **Type Caching**: The backend type is stored for future reference

This process ensures that backend components are loaded only once and
efficiently cached for subsequent access.

For implementation details, see:

https://opendev.org/openstack/oslo.service/src/branch/master/oslo_service/backend/__init__.py

**Hook Function Requirements:**

Your hook function must:

- Accept no parameters
- Return a valid ``BackendType`` enum value
- Handle any exceptions internally (the system will fall back to the default
  if your hook raises an exception)

Example hook function:

.. code-block:: python

   def environment_based_backend():
       import os
       if os.environ.get('USE_THREADING_BACKEND'):
           return BackendType.THREADING
       return BackendType.EVENTLET

   register_backend_default_hook(environment_based_backend)

The hook mechanism is primarily useful for library authors or applications
that wish to select the backend dynamically based on environment,
configuration, or context — without enforcing it explicitly.

.. warning::
   If ``get_backend()`` or ``init_backend()`` has already been called before
   your hook is registered, the hook will be ignored and the default backend
   (usually Eventlet) will be used. Make sure to register the hook as early
   as possible, ideally before any other imports that might trigger
   backend usage.

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

When to Use init_backend() vs register_backend_default_hook()
-------------------------------------------------------------

.. list-table::
   :header-rows: 1

   * - Use Case
     - Recommended Method
   * - You control the application entry point
     - ``init_backend()``
   * - You write a shared library or plugin
     - ``register_backend_default_hook()``
   * - You want full predictability
     - ``init_backend()``
   * - You want context-based dynamic selection
     - ``register_backend_default_hook()``

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

Here's an example using a hook for dynamic backend selection:

.. code-block:: python

   from oslo_service.backend import (
       register_backend_default_hook,
       get_component,
       BackendType
   )

   def config_based_backend():
       # Read from configuration or environment
       if config.get('backend_type') == 'threading':
           return BackendType.THREADING
       return BackendType.EVENTLET

   def main():
       # Register the hook before any backend access
       register_backend_default_hook(config_based_backend)

       # The backend will be selected automatically when needed
       ProcessLauncher = get_component("ProcessLauncher")
       launcher = ProcessLauncher(conf)
       launcher.launch_service(my_service)
       launcher.wait()

Common Backend Errors and Exceptions
====================================

When working with the backend system, you may encounter several specific
exceptions and errors:

**BackendAlreadySelected**
   Raised when trying to initialize a backend after one has already been
   selected. This typically happens when ``init_backend()`` is called
   multiple times in your application.

   **Solution**: Ensure that ``init_backend()`` is called only once early
   in your application startup, typically in your main entry point.

**KeyError**
   Raised when trying to access a component that doesn't exist in the
   current backend using ``get_component()``.

   **Solution**: Check that the component name is correct and that the
   component is available in your selected backend.

**ValueError**
   Raised when trying to initialize an unknown backend type.

   **Solution**: Ensure you're using a valid ``BackendType`` enum value
   (``BackendType.EVENTLET`` or ``BackendType.THREADING``).

**ImportError**
   Raised when the backend module cannot be imported or the backend class
   is not found in the module.

   **Solution**: This usually indicates an installation issue or missing
   dependencies for the selected backend.

**Hook Exceptions**
   If your hook function raises an exception, the system will log the error
   and fall back to the default backend (Eventlet).

   **Solution**: Ensure your hook function handles all potential errors
   and always returns a valid ``BackendType``.

**Debugging Tips:**

- Use ``_reset_backend()`` in unit tests to clear the backend cache
- Check that your backend initialization happens before any component access
- Verify that all required dependencies are installed for your chosen backend
- Use logging to track backend loading and component access
- Test your hook function independently to ensure it works correctly

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
       See `eventlet_backdoor.py`_
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
- `Epoxy spec for oslo.service`_
- `Eventlet removal goal`_

For any questions, please refer to the OpenStack mailing list
or the oslo.service maintainers.

.. _Epoxy spec for Eventlet removal: https://specs.openstack.org/openstack/oslo-specs/specs/epoxy/remove-eventlet-from-oslo-service.html
.. _OpenStack Eventlet removal goal: https://governance.openstack.org/tc/goals/selected/remove-eventlet.html
.. _Epoxy spec for oslo.service: https://specs.openstack.org/openstack/oslo-specs/specs/epoxy/remove-eventlet-from-oslo-service.html
.. _Eventlet removal goal: https://governance.openstack.org/tc/goals/selected/remove-eventlet.html
.. _eventlet_backdoor.py: https://opendev.org/openstack/oslo.service/src/branch/master/oslo_service/eventlet_backdoor.py
