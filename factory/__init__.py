"""ANCHORUM gateway factory, v0.3.0.

Two-level trust hierarchy:

    root (offline)   authorizes   factory key   signs   manifest

Independent verifier in the `verify/` package re-checks the whole chain
without importing anything from `factory/`.

Lifecycle: DISCOVERED -> DRAFT -> VALIDATED -> EVALUATED ->
DOMAIN_APPROVED -> PROMOTED. The factory can only write at or below DRAFT.
"""
FACTORY_VERSION = "0.3.0"
MANIFEST_SCHEMA = 2
CERTIFICATE_VERSION = 1
