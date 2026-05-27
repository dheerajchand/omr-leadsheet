"""Songbook layout discovery.

Snake-case is the project convention for songbook sub-directories
(``individual_songs``, ``music_xml``, ``lyrics``, ``lead_sheets``).
Earlier songbooks carried hand-managed Title Case duplicates
(``Individual Songs``, ``MusicXML``, ``LeadSheets``) that were
tolerated as fallback candidates here; those have been removed from
disk, so the candidate lists now only carry the canonical names.

This module centralises the lookup so all entry points share one
source of truth — previously each call site hardcoded a name, which
caused silent failures when the disk layout used a different form
(#18, #21).
"""
from __future__ import annotations

from pathlib import Path


SONGS_DIR_CANDIDATES = ("individual_songs",)
MXL_DIR_CANDIDATES = ("music_xml",)
LYRICS_DIR_CANDIDATES = ("lyrics",)
LEADSHEETS_DIR_CANDIDATES = ("lead_sheets",)


def find_subdir(
    parent: Path,
    candidates: tuple[str, ...],
    *,
    must_exist: bool = True,
) -> Path:
    """Return the first existing sub-directory of ``parent`` from
    ``candidates``, tried in order.

    When ``must_exist=True`` (default), raises ``FileNotFoundError``
    listing all candidates if none exist. Use the default for inputs
    where missing the dir is a real failure (the user pointed
    ``BOOK_DIR`` somewhere wrong).

    When ``must_exist=False``, returns ``parent / candidates[0]`` even
    if none exist — useful for output directories that the caller
    intends to ``mkdir(parents=True, exist_ok=True)``.
    """
    for name in candidates:
        candidate = parent / name
        if candidate.is_dir():
            return candidate
    if must_exist:
        raise FileNotFoundError(
            f"No matching sub-directory found under {parent}. "
            f"Tried: {', '.join(candidates)}."
        )
    return parent / candidates[0]


__all__ = [
    "SONGS_DIR_CANDIDATES",
    "MXL_DIR_CANDIDATES",
    "LYRICS_DIR_CANDIDATES",
    "LEADSHEETS_DIR_CANDIDATES",
    "find_subdir",
]
