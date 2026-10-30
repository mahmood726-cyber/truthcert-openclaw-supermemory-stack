"""
TruthCert validators - fail-closed validation pipeline.

Validators are organized into categories:
- Core: Schema, scope lock, determinism
- Memory safety: Memory leak, memory drift
- Statistical: Effect size, heterogeneity, publication bias, NMA
- Security: Evidence allowlist, IDN homograph
- Reporting: PRISMA 2020 checklist
- Risk of Bias: ROB 2, ROBINS-I, QUADAS-2, PROBAST
- Evidence Certainty: GRADE
"""

from .base import Validator, ValidatorRegistry
from .determinism import DeterminismValidator
from .domain_pack_heterogeneity import HeterogeneityValidator
from .domain_pack_publication_bias import PublicationBiasValidator
from .effect_size_plausibility import EffectSizePlausibilityValidator
from .evidence_allowlist import EvidenceAllowlistValidator
from .grade_validator import (
    DomainAssessment,
    GRADEAssessment,
    GRADECertainty,
    GRADECertaintyValidator,
    calculate_ois,
    interpret_certainty,
    summarize_grade_table,
)
from .idn_homograph import IDNHomographValidator
from .memory_drift import MemoryDriftValidator
from .memory_leak import MemoryLeakValidator
from .multi_witness import MultiWitnessValidator
from .nma_validator import NMAValidator, PRISMANMAValidator
from .no_naked_numbers import NoNakedNumbersValidator
from .prisma_checklist import PRISMAChecklistValidator
from .qwed_validator import MathConsistencyValidator, QWEDValidator
from .risk_of_bias import (
    PROBAST_DOMAINS,
    QUADAS2_DOMAINS,
    # Domain definitions
    ROB2_DOMAINS,
    ROBINSI_DOMAINS,
    PROBASTJudgment,
    PROBASTValidator,
    QUADAS2Judgment,
    QUADAS2Validator,
    # Enums
    ROB2Judgment,
    ROB2Validator,
    ROBINSIJudgment,
    ROBINSIValidator,
    generate_rob_summary_table,
    get_probast_template,
    get_quadas2_template,
    # Helper functions
    get_rob2_template,
    get_robinsi_template,
)
from .schema_validator import SchemaValidator
from .scope_lock_validator import ScopeLockValidator
from .unit_drift import UnitDriftValidator

__all__ = [
    "PROBAST_DOMAINS",
    "QUADAS2_DOMAINS",
    # Risk of Bias domain definitions
    "ROB2_DOMAINS",
    "ROBINSI_DOMAINS",
    "DeterminismValidator",
    "DomainAssessment",
    "EffectSizePlausibilityValidator",
    # Security validators
    "EvidenceAllowlistValidator",
    "GRADEAssessment",
    "GRADECertainty",
    # GRADE certainty validators
    "GRADECertaintyValidator",
    # Statistical validators
    "HeterogeneityValidator",
    "IDNHomographValidator",
    "MathConsistencyValidator",
    "MemoryDriftValidator",
    # Memory safety validators
    "MemoryLeakValidator",
    "MultiWitnessValidator",
    "NMAValidator",
    "NoNakedNumbersValidator",
    # Reporting validators
    "PRISMAChecklistValidator",
    "PRISMANMAValidator",
    "PROBASTJudgment",
    "PROBASTValidator",
    "PublicationBiasValidator",
    "QUADAS2Judgment",
    "QUADAS2Validator",
    # QWED validators
    "QWEDValidator",
    # Risk of Bias enums
    "ROB2Judgment",
    # Risk of Bias validators
    "ROB2Validator",
    "ROBINSIJudgment",
    "ROBINSIValidator",
    # Core validators
    "SchemaValidator",
    "ScopeLockValidator",
    "UnitDriftValidator",
    # Base
    "Validator",
    "ValidatorRegistry",
    "calculate_ois",
    "generate_rob_summary_table",
    "get_probast_template",
    "get_quadas2_template",
    # Risk of Bias helper functions
    "get_rob2_template",
    "get_robinsi_template",
    "interpret_certainty",
    "summarize_grade_table",
]
