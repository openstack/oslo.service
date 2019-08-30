=====
Usage
=====

To use oslo.service in a project::

    import oslo_service

Migrating to oslo.service
=========================

The ``oslo.service`` library no longer assumes a global configuration object is
available. Instead the following functions and classes have been
changed to expect the consuming application to pass in an ``oslo.config``
configuration object:

* :func:`~oslo_service.eventlet_backdoor.initialize_if_enabled`
* :py:class:`oslo_service.periodic_task.PeriodicTasks`
* :func:`~oslo_service.service.launch`
* :py:class:`oslo_service.service.ProcessLauncher`
* :py:class:`oslo_service.service.ServiceLauncher`
* :func:`~oslo_service.sslutils.is_enabled`
* :func:`~oslo_service.sslutils.wrap`

When using service from oslo-incubator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    from foo.openstack.common import service

    launcher = service.launch(service, workers=2)

When using oslo.service
~~~~~~~~~~~~~~~~~~~~~~~

::

    from oslo_config import cfg
    from oslo_service import service

    CONF = cfg.CONF
    launcher = service.launch(CONF, service, workers=2)

Using oslo.service with oslo-config-generator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``oslo.service`` provides several entry points to generate configuration
files.

* :func:`oslo.service.service <oslo_service.service.list_opts>`
    The options from the :mod:`~oslo_service.service` and
    :mod:`~oslo_service.eventlet_backdoor` modules for the ``[DEFAULT]``
    section.

* :func:`oslo.service.periodic_task <oslo_service.periodic_task.list_opts>`
    The options from the :mod:`~oslo_service.periodic_task` module for the
    ``[DEFAULT]`` section.

* :func:`oslo.service.sslutils <oslo_service.sslutils.list_opts>`
    The options from the :mod:`~oslo_service.sslutils` module for the
    :oslo.config:group:`ssl` section.

* :func:`oslo.service.wsgi <oslo_service.wsgi.list_opts>`
    The options from the :mod:`~oslo_service.wsgi` module for the ``[DEFAULT]``
    section.

.. todo:: The ref page for oslo_service.wsgi doesn't seem to be rendering, so
          the above doesn't link.

.. todo:: Attempting to use :oslo.config:group:`DEFAULT` above only links to
          the first DEFAULT section in the configuration/index doc because the
          #DEFAULT anchor is duplicated for each of the show-options sections.

**ATTENTION:** The library doesn't provide an oslo.service entry point.

.. code-block:: bash

    $ oslo-config-generator --namespace oslo.service.service \
    --namespace oslo.service.periodic_task \
    --namespace oslo.service.sslutils

Launching and controlling services
==================================

The :mod:`oslo_service.service` module provides tools for launching OpenStack
services and controlling their lifecycles.

A service is an instance of any class that
subclasses :py:class:`oslo_service.service.ServiceBase`.
:py:class:`ServiceBase <oslo_service.service.ServiceBase>` is an
abstract class that defines an interface every
service should implement. :py:class:`oslo_service.service.Service` can
serve as a base for constructing new services.

Launchers
~~~~~~~~~

The :mod:`oslo_service.service` module provides two launchers for running
services:

* :py:class:`oslo_service.service.ServiceLauncher` - used for
  running one or more service in a parent process.
* :py:class:`oslo_service.service.ProcessLauncher` - forks a given
  number of workers in which service(s) are then started.

It is possible to initialize whatever launcher is needed and then
launch a service using it.

.. code-block:: python

    from oslo_config import cfg
    from oslo_service import service

    CONF = cfg.CONF


    service_launcher = service.ServiceLauncher(CONF)
    service_launcher.launch_service(service.Service())

    process_launcher = service.ProcessLauncher(CONF, wait_interval=1.0)
    process_launcher.launch_service(service.Service(), workers=2)

Or one can simply call :func:`oslo_service.service.launch` which will
automatically pick an appropriate launcher based on a number of workers that
are passed to it (:py:class:`~oslo_service.service.ServiceLauncher` if
``workers=1`` or ``None`` and :py:class:`~oslo_service.service.ProcessLauncher`
in other case).

.. code-block:: python

    from oslo_config import cfg
    from oslo_service import service

    CONF = cfg.CONF

    launcher = service.launch(CONF, service.Service(), workers=3)

.. note:: It is highly recommended to use no more than one instance of the
          :py:class:`~oslo_service.service.ServiceLauncher` or
          :py:class:`~oslo_service.service.ProcessLauncher` class per process.

Signal handling
~~~~~~~~~~~~~~~

:mod:`oslo_service.service` provides handlers for such signals as ``SIGTERM``,
``SIGINT``, and ``SIGHUP``.

``SIGTERM`` is used for graceful termination of services. This can allow a
server to wait for all clients to close connections while rejecting new
incoming requests. Config option
:oslo.config:option:`graceful_shutdown_timeout` specifies how many seconds
after receiving a ``SIGTERM`` signal a server should continue to run, handling
the existing connections. Setting
:oslo.config:option:`graceful_shutdown_timeout` to zero means that the server
will wait indefinitely until all remaining requests have been fully served.

To force instantaneous termination the ``SIGINT`` signal must be sent.

The behavior on receiving ``SIGHUP`` varies based on how the service is
configured. If the launcher uses ``restart_method='reload'`` (the default),
then the service will reload its configuration and any threads will be
completely restarted. If ``restart_method='mutate'`` is used, then only the
configuration options marked as mutable will be reloaded and the service
threads will not be restarted.

See :py:class:`oslo_service.service.Launcher` for more details on the
``restart_method`` parameter.

.. note:: ``SIGHUP`` is not supported on Windows.
.. note:: Config option :oslo.config:option:`graceful_shutdown_timeout` is not
          supported on Windows.

Below is an example of a service with a reset method that allows reloading
logging options by sending a ``SIGHUP``.

.. code-block:: python

    from oslo_config import cfg
    from oslo_log import log as logging
    from oslo_service import service

    CONF = cfg.CONF

    LOG = logging.getLogger(__name__)

    class FooService(service.ServiceBase):

        def start(self):
            pass

        def wait(self):
            pass

        def stop(self):
            pass

        def reset(self):
            logging.setup(cfg.CONF, 'foo')


Profiling
~~~~~~~~~

Processes spawned through :mod:`oslo_service.service` can be profiled (function
calltrace) through the :mod:`~oslo_service.eventlet_backdoor` module. The
service must be configured with the :oslo.config:option:`backdoor_port` option
to enable its workers to listen on TCP ports. The user can then send the
``prof()`` command to capture the worker process's function calltrace.

1) To start profiling send the ``prof()`` command on the process's listening
   port

2) To stop profiling and capture pstat calltrace to a file, send the
   ``prof()`` command with a file basename as an argument (``prof(basename)``)
   to the worker process's listening port. A stats file (in pstat format) will
   be generated in the temp directory with the user-provided basename with a
   ``.prof`` suffix .

For example, to profile a neutron server process (which is listening on
port 8002 configured through the :oslo.config:option:`backdoor_port` option):

.. code-block:: bash

    $ echo "prof()" | nc localhost 8002
    $ neutron net-create n1; neutron port-create --name p1 n1;
    $ neutron port-delete p1; neutron port-delete p1
    $ echo "prof('neutron')" | nc localhost 8002

This will generate a stats file in ``/tmp/neutron.prof``. Stats can be printed
from the trace file as follows:

.. code-block:: python

    import pstats

    stats = pstats.Stats('/tmp/neutron.prof')
    stats.print_stats()
