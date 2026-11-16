"""Demonstration applications built on top of the inference service.

Each subpackage is one self-contained app the console's "apps" section drives:
its own storage subtree under ``<data root>/apps/``, its own router, and no
import of the management plane's internals (``admin_api``/``downloader`` are
off-limits by design -- they carry the model lifecycle).
"""
