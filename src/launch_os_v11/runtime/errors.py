from __future__ import annotations


class RuntimeJobError(Exception):
    """Base class for explicit runtime job failures."""


class TransientJobError(RuntimeJobError):
    """Failure that may be retried by the durable runtime."""


class PermanentJobError(RuntimeJobError):
    """Failure that must become terminal FAILED."""


class SecretRejectedError(PermanentJobError):
    """Payload or error content appears to contain a secret."""
