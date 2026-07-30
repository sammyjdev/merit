"""Read-only profile store: load, hash, and deterministic alias resolution."""
import hashlib
from pathlib import Path

import yaml
from pydantic import ValidationError

from merit.schemas import Profile, SkillEntry


class ProfileError(Exception):
    pass


def load_profile(path: str | Path) -> Profile:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return Profile.model_validate(data)
    except (yaml.YAMLError, ValidationError, OSError) as exc:
        raise ProfileError(f"invalid profile {path}: {exc}") from exc


def profile_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve(profile: Profile, demand_name: str) -> SkillEntry | None:
    needle = demand_name.strip().lower()
    by_id = {s.id.lower(): s for s in profile.skills}
    if needle in by_id:
        return by_id[needle]
    for s in profile.skills:
        if s.name.lower() == needle:
            return s
    for alias, skill_id in profile.aliases.items():
        if alias.lower() == needle:
            return by_id.get(skill_id.lower())
    return None


def strong_terms(profile: Profile) -> list[str]:
    strong_ids = {s.id.lower() for s in profile.skills if s.status == "strong"}
    terms = [s.name.lower() for s in profile.skills if s.status == "strong"]
    for alias, skill_id in profile.aliases.items():
        if skill_id.lower() in strong_ids:
            terms.append(alias.lower())
    return terms
