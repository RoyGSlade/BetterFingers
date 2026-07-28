"""Platform-facing adapters that must not leak into domain or service code.

Sub-packages here wrap an operating-system mechanism behind a contract the
rest of the backend can depend on without importing ``subprocess``, ``ctypes``,
or a vendor SDK. ``audio_privacy`` is the first: it owns capture isolation
(D-0010) on the platforms that can do it, and reports honestly on the ones
that cannot.

Naming note: this package shadows the stdlib ``platform`` module only inside
``backend.platform``'s own dotted path. Absolute imports elsewhere in the
tree (``import platform``) still resolve to the standard library, and modules
inside this package can import it normally for the same reason.
"""
