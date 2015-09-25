========================================================
 oslo.service -- Library for running OpenStack services
========================================================

oslo.service provides a framework for defining new long-running
services using the patterns established by other OpenStack
applications. It also includes utilities long-running applications
might need for working with SSL or WSGI, performing periodic
operations, interacting with systemd, etc.

.. toctree::
   :maxdepth: 2

   installation
   usage
   opts
   contributing

API Documentation
=================

.. toctree::
   :maxdepth: 2

   api/eventlet_backdoor
   api/loopingcall
   api/periodic_task
   api/service
   api/sslutils
   api/systemd
   api/threadgroup

Release Notes
=============

.. toctree::
   :maxdepth: 1

   history

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

.. _oslo: https://wiki.openstack.org/wiki/Oslo
