"""
Base validator classes and registry.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Type
import time

from ..constants import Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult, ValidatorConfig


class Validator(ABC):
    """Base class for all validators."""

    name: str = "base"
    description: str = "Base validator"
    default_severity: Severity = Severity.BLOCK

    def __init__(self, config: Optional[ValidatorConfig] = None):
        self.config = config or ValidatorConfig(name=self.name)
        self.severity = config.severity if config else self.default_severity

    @abstractmethod
    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """
        Validate claims against this validator's rules.

        Args:
            claims: List of claims to validate
            scope_lock: The scope lock for this certification
            context: Additional context (evidence cache, policy, etc.)

        Returns:
            ValidatorResult with pass/fail status and details
        """
        pass

    def run(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Run validation with timing."""
        start_time = time.perf_counter()

        try:
            result = self.validate(claims, scope_lock, context)
        except Exception as e:
            result = ValidatorResult(
                validator_name=self.name,
                passed=False,
                severity=self.severity,
                message=f"Validator error: {str(e)}",
                details={"error": str(e), "error_type": type(e).__name__},
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        result.execution_time_ms = elapsed_ms

        return result


class ValidatorRegistry:
    """Registry of available validators."""

    _validators: dict[str, Type[Validator]] = {}

    @classmethod
    def register(cls, validator_class: Type[Validator]) -> Type[Validator]:
        """Register a validator class."""
        cls._validators[validator_class.name] = validator_class
        return validator_class

    @classmethod
    def get(cls, name: str) -> Optional[Type[Validator]]:
        """Get a validator class by name."""
        return cls._validators.get(name)

    @classmethod
    def get_instance(
        cls,
        name: str,
        config: Optional[ValidatorConfig] = None,
    ) -> Optional[Validator]:
        """Get a validator instance by name."""
        validator_class = cls.get(name)
        if validator_class:
            return validator_class(config)
        return None

    @classmethod
    def list_validators(cls) -> list[str]:
        """List all registered validator names."""
        return list(cls._validators.keys())

    @classmethod
    def create_pipeline(
        cls,
        validator_configs: list[ValidatorConfig],
    ) -> list[Validator]:
        """Create a validation pipeline from configs."""
        pipeline = []
        for config in validator_configs:
            if config.enabled:
                validator = cls.get_instance(config.name, config)
                if validator:
                    pipeline.append(validator)
        return pipeline
