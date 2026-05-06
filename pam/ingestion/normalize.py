from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pam.db.schema import resolve_workspace_id, utcnow


VALID_INPUT_TYPES = {"note", "link", "task", "document"}


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize(
    raw_text: str,
    input_type: str,
    provided_at: datetime | None = None,
    session_id: str | None = None,
    workspace_id: str | Path | None = None,
) -> dict:
    """
    Convert raw input into a canonical dict.

    Returns a dictionary with stripped text, validated input type, and UTC timestamps.
    """
    stripped_text = (raw_text or "").strip()
    if not stripped_text:
        raise ValueError("Empty input")

    normalized_input_type = (input_type or "note").strip().lower()
    if normalized_input_type not in VALID_INPUT_TYPES:
        raise ValueError(f"Unsupported input_type: {normalized_input_type}")

    recorded_at = utcnow()
    valid_at = _coerce_utc(provided_at) if provided_at is not None else recorded_at

    return {
        "raw_text": stripped_text,
        "input_type": normalized_input_type,
        "provided_at": valid_at,
        "recorded_at": recorded_at,
        "session_id": session_id,
        "workspace_id": resolve_workspace_id(workspace_id),
    }


__all__ = ["VALID_INPUT_TYPES", "normalize"]