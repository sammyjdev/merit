from pathlib import Path

import pytest

from merit.profile import ProfileError, load_profile, profile_hash, resolve

FIXTURE = Path(__file__).parent / "fixtures" / "profile_small.yaml"


def test_load_profile():
    p = load_profile(FIXTURE)
    assert p.skills[0].id == "fastapi"


def test_profile_hash_is_stable_sha256_hex():
    h = profile_hash(FIXTURE)
    assert h == profile_hash(FIXTURE) and len(h) == 64


def test_load_invalid_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("skills: [{id: x}]")
    with pytest.raises(ProfileError):
        load_profile(bad)


def test_resolve_by_name_case_insensitive():
    p = load_profile(FIXTURE)
    assert resolve(p, "fastapi").id == "fastapi"
    assert resolve(p, "FASTAPI").id == "fastapi"


def test_resolve_by_alias():
    p = load_profile(FIXTURE)
    assert resolve(p, "REST APIs").id == "fastapi"


def test_resolve_unknown_returns_none():
    p = load_profile(FIXTURE)
    assert resolve(p, "Quantum Computing") is None
