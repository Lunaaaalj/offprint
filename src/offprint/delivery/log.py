"""The delivery log: what was sent, so the same version isn't sent twice."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class Record:
    identifier: str
    sha256: str
    time: str
    result: str
    """`sent`, or `failed: ` and the reason."""
    to: str


def append(path: Path, record: Record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def already_sent(path: Path, identifier: str, sha256: str) -> Record | None:
    """The record of this exact file having been sent, if there is one."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written line must not stop a delivery
        if (
            data.get("identifier") == identifier
            and data.get("sha256") == sha256
            and data.get("result") == "sent"
        ):
            return Record(**data)
    return None
