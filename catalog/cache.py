"""Persist the parsed item catalog so it survives across GUI runs — **per MC version**.

Mods change their items between MC versions, so each version gets its own catalog:

    .cache/<version>/catalog.json        # loaded-jar records + all ItemEntry dicts
    .cache/<version>/icons/<ns>/<path>.png

The catalog is *derived* data (rebuilt from jars on demand), not a hand-authored input,
so it lives in a gitignored ``.cache/``. Stdlib only — no Qt. The GUI drives one ``Catalog``
per active version: drop a jar -> ``add_jar`` -> ``save``; switch version -> ``set_version``.
"""

import os

from catalog.jar_loader import ItemEntry, parse_jar
from core.dataio import read_json, write_json

# Repo root is the parent of this ``catalog/`` package.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_BASE = os.path.join(REPO_ROOT, ".cache")

CATALOG_VERSION = 2


def _icon_rel_for(item_id: str) -> str:
    """Relative icon path under the icons dir for an id, e.g. 'blue_skies/pyrope_gem.png'."""
    ns, _, path = item_id.partition(":")
    return os.path.join(ns, f"{path}.png")


class Catalog:
    """In-memory item catalog backed by ``.cache/<version>/``.

    ``items`` maps ``namespace:path`` -> :class:`ItemEntry`. ``jars`` records which jar
    files have been loaded (basename -> {"path", "size", "mtime", "namespaces"}) so a
    re-dropped jar can supersede an older version of the same mod.
    """

    def __init__(self, version: str, base_dir: str = CACHE_BASE) -> None:
        self._base_dir = base_dir
        self.items: dict[str, ItemEntry] = {}
        self.jars: dict[str, dict] = {}
        self.set_version(version, load=False)

    def set_version(self, version: str, load: bool = True) -> None:
        """Point the catalog at a version's cache dir; reloads its contents by default."""
        self.version = version
        self.cache_dir = os.path.join(self._base_dir, version)
        self.catalog_file = os.path.join(self.cache_dir, "catalog.json")
        self.icons_dir = os.path.join(self.cache_dir, "icons")
        if load:
            self.load()

    # --- mutation -------------------------------------------------------------

    def add_jar(self, jar_path: str) -> int:
        """Parse a jar, replacing any prior version of the same mod. Returns items added.

        A mod is identified by the namespace(s) its jar provides, not by filename, so
        dropping a *different version* of the same mod (e.g. ``blue_skies-1.3.29.jar`` ->
        ``blue_skies-1.3.30.jar``) fully replaces the old version's items rather than
        leaving both.
        """
        result = parse_jar(jar_path)
        source = os.path.basename(jar_path)
        namespaces = {e.namespace for e in result.entries}

        if namespaces:
            self.items = {i: e for i, e in self.items.items() if e.namespace not in namespaces}
            self.jars = {s: rec for s, rec in self.jars.items()
                         if not (set(rec.get("namespaces", [])) & namespaces)}
        self.jars.pop(source, None)

        for entry in result.entries:
            icon_bytes = result.icons.get(entry.id)
            if icon_bytes is not None:
                rel = _icon_rel_for(entry.id)
                dest = os.path.join(self.icons_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(icon_bytes)
                entry.icon_rel = rel
            self.items[entry.id] = entry

        record = {"path": jar_path, "namespaces": sorted(namespaces)}
        try:
            st = os.stat(jar_path)
            record["size"], record["mtime"] = st.st_size, st.st_mtime
        except OSError:
            record["size"], record["mtime"] = 0, 0
        self.jars[source] = record
        return len(result.entries)

    def remove_jar(self, source: str) -> None:
        """Forget a jar (by basename) and every item it contributed."""
        self.items = {i: e for i, e in self.items.items() if e.source_jar != source}
        self.jars.pop(source, None)

    # --- queries --------------------------------------------------------------

    def search(self, query: str) -> list[ItemEntry]:
        """Case-insensitive match on id or display name; sorted by id. Empty -> all."""
        q = query.strip().lower()
        items = sorted(self.items.values(), key=lambda e: e.id)
        if not q:
            return items
        return [e for e in items if q in e.id.lower() or q in e.display_name.lower()]

    def icon_abs_path(self, entry: ItemEntry) -> str | None:
        """Absolute path to an entry's cached icon, or None if it has none on disk."""
        if not entry.icon_rel:
            return None
        p = os.path.join(self.icons_dir, entry.icon_rel)
        return p if os.path.isfile(p) else None

    # --- persistence ----------------------------------------------------------

    def save(self) -> None:
        write_json(self.catalog_file, {
            "version": CATALOG_VERSION,
            "mc_version": self.version,
            "jars": self.jars,
            "items": [e.to_dict() for e in sorted(self.items.values(), key=lambda e: e.id)],
        })

    def load(self) -> None:
        """Load this version's cached catalog if present; leave empty (no error) if absent."""
        self.items = {}
        self.jars = {}
        if not os.path.isfile(self.catalog_file):
            return
        try:
            data = read_json(self.catalog_file)
        except (ValueError, FileNotFoundError):
            return
        self.jars = data.get("jars", {}) or {}
        for d in data.get("items", []):
            try:
                entry = ItemEntry.from_dict(d)
            except TypeError:
                continue
            self.items[entry.id] = entry
