"""Machine-learning subsystems for NADOC.

Currently houses the atomistic-propagator MVP (``backend.ml.propagator``): a
learned time-propagation operator for DNA–water–ion systems plus its data
pipeline.  Heavy ML dependencies (torch, e3nn) are OPTIONAL — the data-generation
and analysis modules import only NADOC core; only the model/training modules
require torch, and they guard the import so the core app and fast test suite
never pull it in.
"""
