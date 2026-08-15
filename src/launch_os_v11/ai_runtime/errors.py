from __future__ import annotations

from launch_os_v11.runtime.errors import PermanentJobError, TransientJobError


class AIRuntimeError(Exception):
    """Base class for governed AI runtime failures."""


class AIContractError(PermanentJobError, AIRuntimeError):
    """Agent contract or durable definition is invalid."""


class AIConfigurationError(PermanentJobError, AIRuntimeError):
    """Provider routing or credentials are not configured."""


class AIContextError(PermanentJobError, AIRuntimeError):
    """Scoped context cannot be safely built for an agent run."""


class AIInvalidOutputError(PermanentJobError, AIRuntimeError):
    """Provider output did not validate as the expected structured schema."""


class AIPermanentProviderError(PermanentJobError, AIRuntimeError):
    """Provider returned a non-retryable failure."""


class AITransientProviderError(TransientJobError, AIRuntimeError):
    """Provider returned a retryable failure."""
