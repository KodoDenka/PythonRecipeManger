"""Dependency-free JSON I/O shared by the generator-adjacent tooling.

The write convention here matches the **source data** under ``common/``: UTF-8,
``indent=2``, ``ensure_ascii=False``, and ``newline=""`` so json's ``"\n"`` stays LF on
Windows too, matching the mod repo's ``.gitattributes`` (``* text eol=lf``). Keeping it in
one stdlib-only module lets the GUI rewrite ``tiers.json``/``keys.json`` in the shape they
are already committed in, so an edit through the GUI produces a one-line diff.

Note this is *not* ``main.py``'s ``write_json``, which writes the generator's **output**
at ``indent=4`` to match the mod repo's existing data pack files. The two indents belong to
two different trees and are not a drift to be reconciled.

No third-party imports here — this stays importable by the stdlib-only core.
"""

import json
import os


def read_json(path: str):
    """Load and return parsed JSON, with clear errors for the common failures."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"JSON file not found at {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in file: {path}\nError: {e}") from e


def write_json(path: str, data) -> None:
    """Write ``data`` as pretty JSON with LF newlines, creating parent dirs."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # newline="" keeps json's "\n" as LF on Windows too (see module docstring).
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
