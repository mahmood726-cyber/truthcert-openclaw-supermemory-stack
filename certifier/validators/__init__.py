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
from .schema_validator import SchemaValidator
from .scope_lock_validator import ScopeLockValidator
from .no_naked_numbers import NoNakedNumbersValidator
from .memory_leak import MemoryLeakValidator
from .memory_drift import MemoryDriftValidator
from .determinism import DeterminismValidator
from .multi_witness import MultiWitnessValidator
from .unit_drift import UnitDriftValidator
from .domain_pack_heterogeneity import HeterogeneityValidator
from .domain_pack_publication_bias import PublicationBiasValidator
from .effect_size_plausibility import EffectSizePlausibilityValidator
from .evidence_allowlist import EvidenceAllowlistValidator
from .nma_validator import NMAValidator, PRISMANMAValidator
from .idn_homograph import IDNHomographValidator
from .prisma_checklist import PRISMAChecklistValidator
from .qwed_validator import QWEDValidator, MathConsistencyValidator
from .grade_validator import (
    GRADECertaintyValidator,
    GRADECertainty,
    GRADEAssessment,
    DomainAssessment,
    calculate_ois,
    interpret_certainty,
    summarize_grade_table,
)
from .risk_of_bias import (
    ROB2Validator,
    ROBINSIValidator,
    QUADAS2Validator,
    PROBASTValidator,
    # Enums
    ROB2Judgment,
    ROBINSIJudgment,
    QUADAS2Judgment,
    PROBASTJudgment,
    # Domain definitions
    ROB2_DOMAINS,
    ROBINSI_DOMAINS,
    QUADAS2_DOMAINS,
    PROBAST_DOMAINS,
    # Helper functions
    get_rob2_template,
    get_robinsi_template,
    get_quadas2_template,
    get_probast_template,
    generate_rob_summary_table,
)

__all__ = [
    # Base
    "Validator",
    "ValidatorRegistry",
    # Core validators
    "SchemaValidator",
    "ScopeLockValidator",
    "NoNakedNumbersValidator",
    "DeterminismValidator",
    "MultiWitnessValidator",
    "UnitDriftValidator",
    # Memory safety validators
    "MemoryLeakValidator",
    "MemoryDriftValidator",
    # Statistical validators
    "HeterogeneityValidator",
    "PublicationBiasValidator",
    "EffectSizePlausibilityValidator",
    "NMAValidator",
    "PRISMANMAValidator",
    # Security validators
    "EvidenceAllowlistValidator",
    "IDNHomographValidator",
    # Reporting validators
    "PRISMAChecklistValidator",
    # QWED validators
    "QWEDValidator",
    "MathConsistencyValidator",
    # GRADE certainty validators
    "GRADECertaintyValidator",
    "GRADECertainty",
    "GRADEAssessment",
    "DomainAssessment",
    "calculate_ois",
    "interpret_certainty",
    "summarize_grade_table",
    # Risk of Bias validators
    "ROB2Validator",
    "ROBINSIValidator",
    "QUADAS2Validator",
    "PROBASTValidator",
    # Risk of Bias enums
    "ROB2Judgment",
    "ROBINSIJudgment",
    "QUADAS2Judgment",
    "PROBASTJudgment",
    # Risk of Bias domain definitions
    "ROB2_DOMAINS",
    "ROBINSI_DOMAINS",
    "QUADAS2_DOMAINS",
    "PROBAST_DOMAINS",
    # Risk of Bias helper functions
    "get_rob2_template",
    "get_robinsi_template",
    "get_quadas2_template",
    "get_probast_template",
    "generate_rob_summary_table",
]
