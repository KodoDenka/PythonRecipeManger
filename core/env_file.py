"""Read and update the local ``.env`` file (stdlib only).

The GUI shows each version's saved output path from ``.env`` and writes edits back to it.
Reading mirrors ``main.py``'s ``load_env`` (``KEY=VALUE`` lines, ``#`` comments, optional
quotes). Writing updates a single key **in place**, preserving comments, ordering and other
keys, and appends the key if it is not present. ``.env`` is git-ignored and local-only.
"""

import os

DEFAULT_ENV = ".env"


def env_key_for_version(version: str) -> str:
    """The .env variable holding the mod project path for a version (1.21.1 -> MOD_PATH_1_21_1)."""
    return "MOD_PATH_" + version.replace(".", "_")


def read_env(path: str = DEFAULT_ENV) -> dict[str, str]:
    """Parse ``.env`` into a dict; empty if the file is absent."""
    values: dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def set_env_value(key: str, value: str, path: str = DEFAULT_ENV) -> None:
    """Set ``key=value`` in ``.env``, replacing an existing line or appending a new one.

    Comments, blank lines, ordering and unrelated keys are preserved. Written LF-style.
    """
    lines: list[str] = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    new_line = f"{key}={value}"
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip() == key:
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
