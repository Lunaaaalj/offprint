"""Publisher profiles: YAML files holding every value specific to one journal template (#3)."""

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

import yaml

from offprint.profiles.schema import Profile, ProfileError, build_profile

__all__ = [
    "DocumentFacts",
    "NoProfileMatch",
    "Profile",
    "ProfileError",
    "available_profiles",
    "load_profile",
    "load_profile_file",
    "select_profile",
]


class NoProfileMatch(LookupError):
    """No profile fits a document. The message names the closest one."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentFacts:
    """What a document shows about its template."""

    producer: str = ""
    creator: str = ""
    fonts: frozenset[str] = frozenset()
    text: str = ""


def _parse(text: str, source: str) -> Profile:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ProfileError(f"{source}: not valid YAML: {error}") from error
    return build_profile(data, source)


def load_profile_file(path: Path) -> Profile:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ProfileError(f"{path}: can't read profile: {error}") from error
    return _parse(text, str(path))


@cache
def load_profile(name: str) -> Profile:
    """Load a profile shipped with the package, by name."""
    file = resources.files(__package__) / f"{name}.yaml"
    if not file.is_file():
        raise ProfileError(f"no profile {name!r} (available: {', '.join(available_profiles())})")
    return _parse(file.read_text(encoding="utf-8"), file.name)


def available_profiles() -> tuple[str, ...]:
    names = (Path(item.name) for item in resources.files(__package__).iterdir())
    return tuple(sorted(path.stem for path in names if path.suffix == ".yaml"))


def _criteria(profile: Profile, facts: DocumentFacts) -> dict[str, bool]:
    """Evaluate each thing the profile asks of a document."""
    match = profile.match
    results: dict[str, bool] = {}
    if match.producer is not None:
        results["producer"] = re.search(match.producer, facts.producer) is not None
    if match.creator is not None:
        results["creator"] = re.search(match.creator, facts.creator) is not None
    for font in match.fonts:
        results[f"font {font}"] = any(name.startswith(font) for name in facts.fonts)
    for pattern in match.text:
        results[f"text {pattern}"] = re.search(pattern, facts.text) is not None
    return results


def select_profile(facts: DocumentFacts, profiles: tuple[Profile, ...] | None = None) -> Profile:
    """Return the profile whose every criterion holds, or fail naming the closest one."""
    if profiles is None:
        profiles = tuple(load_profile(name) for name in available_profiles())
    closest: tuple[float, str, list[str]] = (-1.0, "", [])
    for profile in profiles:
        results = _criteria(profile, facts)
        if results and all(results.values()):
            return profile
        score = sum(results.values()) / len(results) if results else 0.0
        if score > closest[0]:
            closest = (score, profile.name, [name for name, ok in results.items() if not ok])
    _, name, failed = closest
    raise NoProfileMatch(
        f"no profile matches this document; the closest is {name!r}, "
        f"which also needs: {', '.join(failed) or 'nothing'}. "
        "Use --profile PATH to supply a publisher profile."
    )
