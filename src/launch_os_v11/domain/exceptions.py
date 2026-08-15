class DomainError(Exception):
    """Base class for domain invariant violations."""


class TenantScopeViolation(DomainError):
    """Raised when a tenant-scoped operation crosses organization/business boundaries."""


class ImmutableObjectError(DomainError):
    """Raised when code attempts to mutate immutable history."""


class InvalidEpistemicTransition(DomainError):
    """Raised when truth-state transitions would collapse evidence semantics."""


class ApprovalBindingError(DomainError):
    """Raised when approval is reused for a different object, version, or action."""
