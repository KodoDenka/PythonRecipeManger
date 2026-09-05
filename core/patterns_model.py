"""Editable model for recipe patterns — **per MC version**, with per-tier overrides (no Qt).

Two files per version under ``common/patterns/<version>/``:

- ``sword_patterns.json`` — base grids ``{sword: {"pattern": [row, row, row]}}``, the default
  recipe shape for every tier.
- ``tier_patterns.json`` — per-tier overrides ``{tier: {sword: [row, row, row]}}``. When a tier
  overrides a sword, that grid is used for the tier's recipe instead of the base one (so a tier
  can add/remove binders or change the shape). Recipe templates can also differ between versions,
  which is why the base file is per-version.

Every grid is a 3x3 of ``H`` (handle), ``M`` (material), ``B`` (binder) and space (empty) — the
shaped-recipe grid ``main.py`` reads. Writes go through :func:`core.dataio.write_json`. Stdlib only.
"""

import os

from core.dataio import read_json, write_json

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS_DIR = os.path.join(REPO_ROOT, "common", "patterns")

GRID = 3
EMPTY = " "
CELLS = (EMPTY, "H", "M", "B")  # empty, handle, material, binder


def normalize_grid(rows) -> list[str]:
    """Coerce a pattern's rows to exactly GRID rows of GRID chars (pad/truncate with space)."""
    rows = list(rows or [])
    out = []
    for r in range(GRID):
        row = rows[r] if r < len(rows) else ""
        row = (row + EMPTY * GRID)[:GRID]
        row = "".join(ch if ch in CELLS else EMPTY for ch in row)
        out.append(row)
    return out


class PatternsModel:
    """Load / edit / save a version's base patterns and per-tier overrides.

    The "template set" being edited is either the **base** (``tier=None``) or a specific
    **tier** (its overrides). ``effective_grid`` resolves override-then-base.
    """

    def __init__(self, version: str) -> None:
        self.entries: dict[str, dict] = {}                    # sword -> {"pattern": grid}
        self.tier_overrides: dict[str, dict[str, list]] = {}  # tier -> {sword: grid}
        self._dirty = False
        self.set_version(version, load=False)

    def set_version(self, version: str, load: bool = True) -> None:
        """Point the model at ``common/patterns/<version>/``; reloads its files by default."""
        self.version = version
        self.patterns_file = os.path.join(PATTERNS_DIR, version, "sword_patterns.json")
        self.overrides_file = os.path.join(PATTERNS_DIR, version, "tier_patterns.json")
        if load:
            self.load()

    def load(self) -> None:
        raw = read_json(self.patterns_file)
        self.entries = {}
        for name, entry in raw.items():
            entry = dict(entry) if isinstance(entry, dict) else {}
            entry["pattern"] = normalize_grid(entry.get("pattern"))
            self.entries[name] = entry
        self.tier_overrides = {}
        if os.path.isfile(self.overrides_file):
            raw_ov = read_json(self.overrides_file)
            for tier, swords in (raw_ov or {}).items():
                if not isinstance(swords, dict):
                    continue
                self.tier_overrides[tier] = {s: normalize_grid(g) for s, g in swords.items()}
        self._dirty = False

    @property
    def dirty(self) -> bool:
        return self._dirty

    # --- reads ----------------------------------------------------------------

    def names(self) -> list[str]:
        return list(self.entries)

    def base_grid(self, sword: str) -> list[str]:
        if sword not in self.entries:
            return [EMPTY * GRID] * GRID
        return list(self.entries[sword]["pattern"])

    def is_overridden(self, tier: str, sword: str) -> bool:
        return sword in self.tier_overrides.get(tier, {})

    def effective_grid(self, sword: str, tier: str | None = None) -> list[str]:
        """The grid actually used: a tier's override if present, otherwise the base."""
        if tier and self.is_overridden(tier, sword):
            return list(self.tier_overrides[tier][sword])
        return self.base_grid(sword)

    def uses_binder(self, sword: str, tier: str | None = None) -> bool:
        return any("B" in row for row in self.effective_grid(sword, tier))

    def overridden_swords(self, tier: str) -> set[str]:
        return set(self.tier_overrides.get(tier, {}))

    # --- writes ---------------------------------------------------------------

    def set_cell(self, sword: str, row: int, col: int, char: str,
                 tier: str | None = None) -> None:
        """Paint one cell of the base grid (``tier=None``) or a tier's override grid.

        Editing a tier's grid that has no override yet seeds the override from the current
        base grid, then applies the change.
        """
        if char not in CELLS:
            raise ValueError(f"Invalid cell {char!r}; expected one of {CELLS}")
        if not (0 <= row < GRID and 0 <= col < GRID):
            raise IndexError(f"cell ({row},{col}) out of range")

        if tier is None:
            rows = self.base_grid(sword)
            line = list(rows[row]); line[col] = char; rows[row] = "".join(line)
            self.entries.setdefault(sword, {})["pattern"] = rows
        else:
            grid = self.tier_overrides.setdefault(tier, {}).get(sword)
            if grid is None:
                grid = self.base_grid(sword)   # seed override from base
            line = list(grid[row]); line[col] = char; grid[row] = "".join(line)
            self.tier_overrides[tier][sword] = grid
        self._dirty = True

    def reset_override(self, tier: str, sword: str) -> None:
        """Drop a tier's override for a sword (falls back to the base grid)."""
        swords = self.tier_overrides.get(tier)
        if swords and sword in swords:
            del swords[sword]
            if not swords:
                del self.tier_overrides[tier]
            self._dirty = True

    # --- base-pattern management (operate on the base set) --------------------

    def add(self, name: str) -> None:
        if not name:
            raise ValueError("Pattern name must not be empty")
        if name in self.entries:
            raise ValueError(f"Pattern already exists: {name}")
        self.entries[name] = {"pattern": [EMPTY * GRID] * GRID}
        self._dirty = True

    def rename(self, old: str, new: str) -> None:
        if old not in self.entries:
            raise KeyError(f"No such pattern: {old}")
        if not new:
            raise ValueError("Pattern name must not be empty")
        if new != old and new in self.entries:
            raise ValueError(f"Pattern already exists: {new}")
        if new == old:
            return
        self.entries = {(new if k == old else k): v for k, v in self.entries.items()}
        # Follow the rename through any tier overrides that reference this sword.
        for swords in self.tier_overrides.values():
            if old in swords:
                swords[new] = swords.pop(old)
        self._dirty = True

    def delete(self, name: str) -> None:
        if name in self.entries:
            del self.entries[name]
            for tier in list(self.tier_overrides):
                self.tier_overrides[tier].pop(name, None)
                if not self.tier_overrides[tier]:
                    del self.tier_overrides[tier]
            self._dirty = True

    def save(self) -> None:
        write_json(self.patterns_file, self.entries)
        # Prune empty tier maps so the file stays tidy.
        overrides = {t: s for t, s in self.tier_overrides.items() if s}
        write_json(self.overrides_file, overrides)
        self._dirty = False
