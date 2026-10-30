"""
Unit/timepoint drift validator - detects unit and temporal inconsistencies.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from ..constants import CertificationProfile, Severity
from ..models import NumericClaim, ScopeLock, ValidatorResult
from .base import Validator, ValidatorRegistry


@ValidatorRegistry.register
class UnitDriftValidator(Validator):
    """
    Detects unit and timepoint drift in claims.

    Checks for:
    1. Unit inconsistencies within related claims
    2. Temporal drift (stale data)
    3. Unit conversion errors

    Severity:
    - BRONZE: INFO
    - SILVER: WARN
    - GOLD: BLOCK
    """

    name = "unit_drift"
    description = "Detects unit and timepoint inconsistencies"
    default_severity = Severity.WARN

    # Common unit families for consistency checking
    UNIT_FAMILIES: ClassVar[dict[str, str]] = {
        "time": [
            "seconds",
            "minutes",
            "hours",
            "days",
            "weeks",
            "months",
            "years",
            "s",
            "min",
            "h",
            "d",
            "w",
            "mo",
            "y",
        ],
        "proportion": ["percent", "%", "proportion", "ratio", "fraction"],
        "count": ["n", "count", "number", "participants", "subjects", "patients"],
        "effect": ["d", "g", "r", "rr", "or", "hr", "smd", "md"],
    }

    def validate(
        self,
        claims: list[NumericClaim],
        scope_lock: ScopeLock,
        context: dict[str, Any],
    ) -> ValidatorResult:
        """Validate for unit and timepoint drift."""
        issues = []
        warnings = []

        # Group claims by type for consistency checking
        claims_by_type: dict[str, list[NumericClaim]] = {}
        for claim in claims:
            claim_type = claim.claim_type.value
            if claim_type not in claims_by_type:
                claims_by_type[claim_type] = []
            claims_by_type[claim_type].append(claim)

        # Check unit consistency within each type
        for claim_type, type_claims in claims_by_type.items():
            units = set()
            for claim in type_claims:
                if claim.unit:
                    units.add(claim.unit.lower())

            # Check for mixed units in same family
            if len(units) > 1:
                family = self._get_unit_family(next(iter(units)))
                if family:
                    mixed_in_family = [u for u in units if u in self.UNIT_FAMILIES.get(family, [])]
                    if len(mixed_in_family) > 1:
                        issues.append(
                            {
                                "claim_type": claim_type,
                                "issue": f"Mixed units in {family} family",
                                "units_found": list(units),
                            }
                        )

        # Check for temporal drift (evidence age)
        max_age_days = self.config.params.get("max_evidence_age_days", 365 * 2)  # 2 years default
        now = datetime.now()

        for claim in claims:
            for evidence in claim.evidence:
                if evidence.extracted_at:
                    try:
                        # Handle timezone-aware vs naive
                        extracted = evidence.extracted_at
                        if extracted.tzinfo:
                            now_aware = datetime.now(UTC)
                            age_days = (now_aware - extracted).days
                        else:
                            age_days = (now - extracted).days

                        if age_days > max_age_days:
                            warnings.append(
                                {
                                    "claim_id": claim.claim_id,
                                    "issue": f"Evidence is {age_days} days old (max: {max_age_days})",
                                    "evidence_uri": evidence.uri,
                                    "extracted_at": evidence.extracted_at.isoformat(),
                                }
                            )
                    except (TypeError, ValueError):
                        pass

        # Check for obvious unit conversion errors
        for claim in claims:
            if claim.unit and claim.value:
                error = self._check_conversion_error(claim)
                if error:
                    issues.append(
                        {
                            "claim_id": claim.claim_id,
                            "issue": error,
                            "value": claim.value,
                            "unit": claim.unit,
                        }
                    )

        # Determine severity based on profile
        severity = self._get_severity_for_profile(scope_lock.profile)

        # Only issues (not warnings) cause failure for blocking severity
        passed = len(issues) == 0 or severity == Severity.INFO

        return ValidatorResult(
            validator_name=self.name,
            passed=passed,
            severity=severity if issues else (Severity.WARN if warnings else Severity.INFO),
            message=(
                "No unit/timepoint drift detected"
                if not issues and not warnings
                else f"Unit/timepoint drift: {len(issues)} issues, {len(warnings)} warnings"
            ),
            details={
                "issues": issues,
                "warnings": warnings,
                "profile": scope_lock.profile.value,
            },
        )

    def _get_unit_family(self, unit: str) -> str | None:
        """Get the family name for a unit."""
        unit_lower = unit.lower()
        for family, units in self.UNIT_FAMILIES.items():
            if unit_lower in units:
                return family
        return None

    def _check_conversion_error(self, claim: NumericClaim) -> str | None:
        """Check for obvious unit conversion errors."""
        unit = claim.unit.lower() if claim.unit else ""
        value = claim.value

        # Proportion checks
        if unit in ["percent", "%"] and (value < 0 or value > 100):
            return f"Percentage value {value} outside valid range [0, 100]"

        if unit in ["proportion", "ratio", "fraction"] and (value < 0 or value > 1):
            return f"Proportion value {value} outside valid range [0, 1]"

        # Count checks
        if unit in ["n", "count", "number", "participants"]:
            if value < 0:
                return f"Count cannot be negative: {value}"
            if value != int(value):
                return f"Count should be integer: {value}"

        return None

    def _get_severity_for_profile(self, profile: CertificationProfile) -> Severity:
        """Get appropriate severity based on certification profile."""
        if profile == CertificationProfile.GOLD:
            return Severity.BLOCK
        elif profile == CertificationProfile.SILVER:
            return Severity.WARN
        else:
            return Severity.INFO
