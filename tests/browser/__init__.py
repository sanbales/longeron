"""The browser-truth test tier (see README.md in this directory).

This __init__ makes tests/browser a package so its conftest imports as
``browser.conftest`` -- WITHOUT it, pytest would register this
directory's conftest under the bare module name ``conftest``, shadowing
``tests/conftest.py`` for every test that does ``from conftest import
VEHICLE_MODEL``.
"""
