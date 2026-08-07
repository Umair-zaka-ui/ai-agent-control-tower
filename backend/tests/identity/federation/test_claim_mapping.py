"""Phase 2.3.1 tests — IdP claim/group -> platform role mapping
(``app/identity/federation/claim_mapping.py``), ``ACT-INT-FR-183``.

Pure, no database, no I/O."""

from __future__ import annotations

from app.identity.federation.claim_mapping import resolve_role_names


def test_ac17_a_matching_group_maps_to_its_configured_role():
    mappings = {"rules": [{"idp_value": "AI-Admins", "role_name": "ADMIN"}]}
    assert resolve_role_names(["AI-Admins"], mappings) == ["ADMIN"]


def test_ac17_multiple_matching_groups_map_to_multiple_distinct_roles():
    mappings = {"rules": [
        {"idp_value": "AI-Admins", "role_name": "ADMIN"},
        {"idp_value": "AI-Reviewers", "role_name": "REVIEWER"},
    ]}
    result = resolve_role_names(["AI-Admins", "AI-Reviewers", "Everyone"], mappings)
    assert result == ["ADMIN", "REVIEWER"]


def test_a_non_matching_group_with_no_default_returns_empty():
    mappings = {"rules": [{"idp_value": "AI-Admins", "role_name": "ADMIN"}]}
    assert resolve_role_names(["Some-Other-Group"], mappings) == []


def test_a_non_matching_group_falls_back_to_the_configured_default():
    mappings = {"rules": [{"idp_value": "AI-Admins", "role_name": "ADMIN"}]}
    assert resolve_role_names(["Some-Other-Group"], mappings, default_role_name="VIEWER") == ["VIEWER"]


def test_empty_groups_with_no_rules_returns_empty():
    assert resolve_role_names([], {"rules": []}) == []


def test_duplicate_role_names_across_rules_are_not_repeated():
    mappings = {"rules": [
        {"idp_value": "Group-A", "role_name": "ADMIN"},
        {"idp_value": "Group-B", "role_name": "ADMIN"},
    ]}
    assert resolve_role_names(["Group-A", "Group-B"], mappings) == ["ADMIN"]


def test_a_malformed_rule_missing_a_key_is_skipped_not_raised():
    mappings = {"rules": [{"idp_value": "AI-Admins"}, {"role_name": "ADMIN"}, {}]}
    assert resolve_role_names(["AI-Admins"], mappings) == []


def test_missing_rules_key_entirely_is_treated_as_no_rules():
    assert resolve_role_names(["AI-Admins"], {}) == []
