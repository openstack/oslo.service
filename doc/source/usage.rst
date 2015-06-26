=======
 Usage
=======

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    from foo.openstack.common import service

    launcher = service.launch(service, workers=2)

When using oslo.service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    from oslo_config import cfg
    from oslo_service import service

    CONF = cfg.CONF
    launcher = service.launch(CONF, service, workers=2)

Using oslo.service with oslo-config-generator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``oslo.service`` provides several entry points to generate a configuration
files.

* :func:`oslo.service.service <oslo_service.service.list_opts>`
    The options from the service and eventlet_backdoor modules for
    the [DEFAULT] section.

* :func:`oslo.service.periodic_task <oslo_service.periodic_task.list_opts>`
    The options from the periodic_task module for the [DEFAULT] section.

* :func:`oslo.service.sslutils <oslo_service.sslutils.list_opts>`
    The options from the sslutils module for the [ssl] section.

**ATTENTION:** The library doesn't provide an oslo.service entry point.

.. code-block:: bash

    $ oslo-config-generator --namespace oslo.service.service \
    --namespace oslo.service.periodic_task \
    --namespace oslo.service.sslutils
