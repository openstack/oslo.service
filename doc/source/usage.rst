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
