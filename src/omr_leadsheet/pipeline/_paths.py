"""Songbook layout discovery.

The gershwin-songbook (and similar songbook directories this pipeline
operates on) doesn't enforce a single naming convention for its
sub-directories. Snake-case is the project convention going forward
(``individual_songs``, ``music_xml``, ``lyrics``, ``lead_sheets``) but
historic / hand-managed layouts may use Title Case forms with or
without spaces (``Individual Songs``, ``MusicXML``, ``LeadSheets``).

The pipeline previously hardcoded specific names per call site, which
caused several silent failures:

* batch processed 0 songs because it looked at ``Individual Songs``
  while the cache was under ``individual_songs`` (#18)
* process re-ran Audiveris for every song because it looked at
  ``MusicXML`` while the cache was under ``music_xml`` (#21)

This module centralises the candidate-name lookup so all entry points
share one source of truth and we don't repeat the bug per call site.
"""
from __future__ import annotations

from pathlib import Path


# Per-sub-directory candidate lists, in priority order (snake-case
# project convention first). Add additional aliases as needed when new
# songbooks surface.
SONGS_DIR_CANDIDATES = ("individual_songs", "Individual Songs", "Individual_Songs")
MXL_DIR_CANDIDATES = ("music_xml", "MusicXML", "Music_XML")
LYRICS_DIR_CANDIDATES = ("lyrics", "Lyrics")
LEADSHEETS_DIR_CANDIDATES = ("lead_sheets", "LeadSheets", "Lead_Sheets")


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
