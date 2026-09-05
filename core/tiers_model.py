"""Editable data model for weapon tiers and their ingredient keys (no Qt).

Bridges the two-level indirection the generator reads: ``tiers.json`` maps a tier to
*key names* for its material/handle/binder, and ``keys.json`` maps each key name to an
``[prefix, id]`` ingredient (``"item"`` or ``"tag"``). The GUI wants to just pick an
ingredient per slot; this model does the bookkeeping — reusing an existing key when one
already describes that ingredient, otherwise creating a sensibly-named one — so both
files stay in the exact shape ``main.py``'s ``load_tiers`` expects.

Stdlib only. Writes go through :func:`core.dataio.write_json`, so diffs stay byte-clean.
"""

import os

from core.dataio import read_json, write_json

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "common", "data")

SLOTS = ("material", "handle", "binder")


def _base_name(value: str) -> str:
    """Derive a key name from an ingredient id: 'blue_skies:pyrope_gem' -> 'pyrope_gem'."""
    tail = value.split(":", 1)[-1]
    return tail.replace("/", "_") or "ingredient"


class TiersModel:
    """Load / edit / save tiers.json + keys.json, managing the key indirection.

    Slot values passed around the API are ``(prefix, value)`` pairs where ``prefix`` is
    ``"item"`` or ``"tag"`` and ``value`` is a resource id such as ``blue_skies:pyrope_gem``
    or a tag like ``c:wood_sticks``.
    """

    def __init__(self, version: str) -> None:
        self.tiers: dict[str, dict] = {}
        self.keys: dict[str, list] = {}
        self.mods: dict[str, dict] = {}
        self._dirty = False
        self.set_version(version, load=False)

    def set_version(self, version: str, load: bool = True) -> None:
        """Point the model at ``common/data/<version>/``; reloads its files by default."""
        self.version = version
        data_dir = os.path.join(DATA_DIR, version)
        self.tiers_file = os.path.join(data_dir, "tiers.json")
        self.keys_file = os.path.join(data_dir, "keys.json")
        self.mods_file = os.path.join(data_dir, "mods.json")
        if load:
            self.load()

    def load(self) -> None:
        self.tiers = read_json(self.tiers_file)
        self.keys = read_json(self.keys_file)
        self.mods = read_json(self.mods_file)
        self._dirty = False

    @property
    def dirty(self) -> bool:
        return self._dirty

    # --- reads ----------------------------------------------------------------

    def tier_names(self) -> list[str]:
        return list(self.tiers)

    def mod_ids(self) -> list[str]:
        return list(self.mods)

    def tier_mod_id(self, tier: str) -> str:
        return self.tiers.get(tier, {}).get("mod_id", "")

    def slot_ingredient(self, tier: str, slot: str) -> tuple[str, str] | None:
        """The ``(prefix, value)`` an occupied slot resolves to, or None if unset/dangling."""
        key_name = self.tiers.get(tier, {}).get(slot)
        if key_name is None:
            return None
        kv = self.keys.get(key_name)
        if not kv or len(kv) < 2:
            return None
        return kv[0], kv[1]

    def slot_key_name(self, tier: str, slot: str) -> str | None:
        return self.tiers.get(tier, {}).get(slot)

    # --- key management -------------------------------------------------------

    def _find_key(self, prefix: str, value: str) -> str | None:
        for name, kv in self.keys.items():
            if list(kv) == [prefix, value]:
                return name
        return None

    def _unique_name(self, base: str) -> str:
        if base not in self.keys:
            return base
        i = 2
        while f"{base}_{i}" in self.keys:
            i += 1
        return f"{base}_{i}"

    def ensure_key(self, prefix: str, value: str) -> str:
        """Return the name of a key for ``(prefix, value)``, creating one if needed."""
        existing = self._find_key(prefix, value)
        if existing is not None:
            return existing
        name = self._unique_name(_base_name(value))
        self.keys[name] = [prefix, value]
        self._dirty = True
        return name

    # --- writes ---------------------------------------------------------------

    def set_slot(self, tier: str, slot: str, prefix: str, value: str) -> str:
        """Point a tier's slot at ``(prefix, value)``; returns the key name used."""
        if slot not in SLOTS:
            raise ValueError(f"Unknown slot {slot!r}; expected one of {SLOTS}")
        if tier not in self.tiers:
            raise KeyError(f"No such tier: {tier}")
        key_name = self.ensure_key(prefix, value)
        self.tiers[tier][slot] = key_name
        self._dirty = True
        return key_name

    def set_mod_id(self, tier: str, mod_id: str) -> None:
        if tier not in self.tiers:
            raise KeyError(f"No such tier: {tier}")
        self.tiers[tier]["mod_id"] = mod_id
        self._dirty = True

    def add_tier(self, name: str, mod_id: str) -> None:
        """Create a tier with valid placeholder slots so the generator never KeyErrors.

        Handle defaults to the ``c:wood_sticks`` tag and binder/material to an iron nugget
        placeholder; the user then assigns a real material from the catalog.
        """
        if not name:
            raise ValueError("Tier name must not be empty")
        if name in self.tiers:
            raise ValueError(f"Tier already exists: {name}")
        handle = self.ensure_key("tag", "c:wood_sticks")
        binder = self.ensure_key("item", "minecraft:iron_nugget")
        self.tiers[name] = {
            "mod_id": mod_id,
            "material": binder,   # placeholder until the user picks a material
            "handle": handle,
            "binder": binder,
        }
        self._dirty = True

    def delete_tier(self, name: str) -> None:
        if name in self.tiers:
            del self.tiers[name]
            self._dirty = True

    def save(self) -> None:
        """Persist this version's tiers.json + keys.json (mods.json is untouched here)."""
        write_json(self.tiers_file, self.tiers)
        write_json(self.keys_file, self.keys)
        self._dirty = False
