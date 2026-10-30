"""Synthetic checks of domain validator severity and missing metadata."""

import pytest

from certifier.constants import CertificationProfile, Severity
from certifier.domain_packs import (
    DomainPack,
    create_validator_configs_for_domain,
    get_claim_types_for_domain,
    get_domain_pack,
    get_reporting_checklist,
    get_validators_for_domain,
    list_available_packs,
    validate_domain_metadata,
)


@pytest.mark.parametrize(
    "pack",
    [
        DomainPack.META_ANALYSIS,
        DomainPack.NMA,
        DomainPack.DTA,
        DomainPack.IPDMA,
        DomainPack.PROGNOSIS,
        DomainPack.PREDICTION,
        DomainPack.RCT,
    ],
)
def test_registered_packs_have_complete_contract(pack):
    spec = get_domain_pack(pack)
    assert spec.claim_types and spec.validators and spec.required_metadata_keys
    assert get_claim_types_for_domain(pack) == spec.claim_types
    assert get_validators_for_domain(pack) == spec.validators
    assert get_reporting_checklist(pack) == spec.reporting_checklist


@pytest.mark.parametrize("profile", list(CertificationProfile))
def test_evidence_guards_are_blocking_for_all_profiles(profile):
    configs = create_validator_configs_for_domain(DomainPack.NMA, profile)
    by_name = {c.name: c for c in configs}
    assert by_name["memory_leak"].severity == Severity.BLOCK
    assert by_name["evidence_allowlist"].severity == Severity.BLOCK
    assert all(c.enabled for c in configs)
    assert all(c.params["domain_pack"] == DomainPack.NMA.value for c in configs)


def test_prisma_policy_is_profile_aware():
    bronze = create_validator_configs_for_domain(
        DomainPack.META_ANALYSIS, CertificationProfile.BRONZE
    )
    gold = create_validator_configs_for_domain(DomainPack.META_ANALYSIS, CertificationProfile.GOLD)
    assert next(c for c in bronze if c.name == "prisma_2020").severity == Severity.WARN
    assert next(c for c in gold if c.name == "prisma_2020").severity == Severity.BLOCK


def test_required_optional_and_none_metadata():
    pack = DomainPack.META_ANALYSIS
    required, optional = validate_domain_metadata(pack, {})
    assert required == get_domain_pack(pack).required_metadata_keys
    assert optional == get_domain_pack(pack).optional_metadata_keys
    required2, optional2 = validate_domain_metadata(pack, {required[0]: None})
    assert required[0] in required2
    assert optional2 == optional
    required3, _ = validate_domain_metadata(pack, {required[0]: 0})
    assert required[0] not in required3


def test_unknown_pack_does_not_invent_validators():
    unknown = "synthetic-unknown-pack"
    assert get_domain_pack(unknown) is None
    assert get_validators_for_domain(unknown) == []
    assert get_claim_types_for_domain(unknown) == []
    assert create_validator_configs_for_domain(unknown) == []


def test_catalog_matches_registered_specs():
    assert {d["name"] for d in list_available_packs()} == {
        p.value for p in DomainPack if get_domain_pack(p) is not None
    }
