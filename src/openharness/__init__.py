"""Reusable OpenHarness runtime package.

Public CLI applications compose the provider, engine, tool, extension, UI, and
persistence subsystems below this namespace. Keep package initialization free of
side effects so importing a model, plugin contract, or utility does not start an
event loop, load credentials, or allocate runtime resources.
"""
