"""Dependency-free JSON I/O shared by the generator-adjacent tooling.

The write convention here is deliberately identical to ``main.py``'s ``write_json``:
UTF-8, ``indent=2``, ``ensure_ascii=False``, and ``newline=""`` so json's ``"\n"``
stays LF on Windows too, matching the mod repo's ``.gitattributes`` (``* text eol=lf``).
Keeping this in one stdlib-only module lets the GUI edit ``tiers.json``/``keys.json``
with byte-identical formatting to the generator, so runs produce clean diffs.

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
