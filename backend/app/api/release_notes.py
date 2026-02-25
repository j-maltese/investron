"""Serve release notes from Docs/ReleaseNotes/*.json files."""

import json
from pathlib import Path

from fastapi import APIRouter

from app.models.schemas import ReleaseNote, ReleaseNotesResponse

router = APIRouter()

# Resolve Docs/ReleaseNotes relative to the repo root.
# This file lives at backend/app/api/release_notes.py — 4 levels up is repo root.
_RELEASE_NOTES_DIR: Path | None = None
for _candidate in [
    Path(__file__).resolve().parent.parent.parent.parent / "Docs" / "ReleaseNotes",
    Path("../Docs/ReleaseNotes"),
    Path("Docs/ReleaseNotes"),
]:
    if _candidate.exists():
        _RELEASE_NOTES_DIR = _candidate.resolve()
        break


def _load_release_notes() -> list[ReleaseNote]:
    """Load all release note JSON files from disk, sorted newest-first."""
    if _RELEASE_NOTES_DIR is None or not _RELEASE_NOTES_DIR.exists():
        return []

    notes: list[ReleaseNote] = []
    for filepath in _RELEASE_NOTES_DIR.glob("*.json"):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            notes.append(ReleaseNote(**data))
        except (json.JSONDecodeError, ValueError):
            continue

    notes.sort(
        key=lambda n: tuple(int(p) for p in n.version.split(".")),
        reverse=True,
    )
    return notes


@router.get("", response_model=ReleaseNotesResponse)
async def get_release_notes():
    """Return all release notes, sorted by version (newest first)."""
    return ReleaseNotesResponse(releases=_load_release_notes())
