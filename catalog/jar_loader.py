"""Build an item catalog from Minecraft / mod ``.jar`` files.

Items are discovered from **item model files** — ``assets/<ns>/models/item/<path>.json`` —
because those correspond one-to-one with registered (renderable) items. Lang files are
noisy for this: ``en_us.json`` also holds tooltips, creative-tab names, subtitles, death
messages, etc., which are not items. So lang is used here only as a *display-name lookup*
for the model-derived items; when an item has no matching ``item.<ns>.<path>`` string we
fall back to a prettified id.

An item's id is ``<ns>:<path>`` where ``<path>`` is the model file's path under
``models/item/`` (sub-folders become ``/`` in the id). Icons are resolved from the flat
item/block texture, or from the model's ``textures`` (preferring ``layer0``).

Stdlib only (zipfile + json) — no Qt, no third-party imports.
"""

import json
import os
import zipfile
from dataclasses import dataclass, field, asdict

# Translation-key prefixes that can name an item/block, used only for display lookup.
LANG_PREFIXES = ("item", "block")


@dataclass
class ItemEntry:
    """One catalog item derived from an item model file.

    ``id`` is the ``namespace:path`` resource id used as an ingredient. ``icon_rel`` is
    filled in later by the cache layer (a path under ``.cache/icons``); it is ``None``
    until the icon has been extracted and saved, or if no texture could be resolved.
    """
    id: str
    namespace: str
    path: str
    kind: str            # "item" (kept for schema stability / future use)
    display_name: str
    source_jar: str
    icon_rel: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ItemEntry":
        # Ignore unknown keys so older/newer cache files stay loadable.
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)


@dataclass
class ParseResult:
    entries: list[ItemEntry] = field(default_factory=list)
    # item id -> raw PNG bytes, kept separate so ItemEntry stays cheaply serialisable.
    icons: dict[str, bytes] = field(default_factory=dict)


def _prettify(path: str) -> str:
    """Fallback display name from an id path: 'knightmetal_ingot' -> 'Knightmetal Ingot'."""
    return path.rsplit("/", 1)[-1].replace("_", " ").title()


def _iter_lang_files(zf: zipfile.ZipFile):
    """Yield (namespace, parsed_json) for every en_us.json under assets/<ns>/lang/."""
    for name in zf.namelist():
        parts = name.split("/")
        if (len(parts) == 4 and parts[0] == "assets" and parts[2] == "lang"
                and parts[3].lower() == "en_us.json"):
            try:
                with zf.open(name) as f:
                    data = json.loads(f.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                continue
            if isinstance(data, dict):
                yield parts[1], data


def _iter_item_models(zf: zipfile.ZipFile):
    """Yield (namespace, rel_path, zip_name) for each assets/<ns>/models/item/**/*.json."""
    for name in zf.namelist():
        parts = name.split("/")
        # assets/<ns>/models/item/<path...>.json  (at least one path segment)
        if (len(parts) >= 5 and parts[0] == "assets" and parts[2] == "models"
                and parts[3] == "item" and name.lower().endswith(".json")):
            rel = "/".join(parts[4:])[:-len(".json")]
            if rel:
                yield parts[1], rel, name


def _display_map(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map item id -> display name from every lang file (item./block. keys only)."""
    display: dict[str, str] = {}
    for _ns, lang in _iter_lang_files(zf):
        for key, value in lang.items():
            if not isinstance(value, str):
                continue
            segs = key.split(".")
            if len(segs) < 3 or segs[0] not in LANG_PREFIXES:
                continue
            item_id = f"{segs[1]}:{'.'.join(segs[2:])}"
            display.setdefault(item_id, value)
    return display


def _resolve_icon(zf: zipfile.ZipFile, names: set[str], ns: str, rel: str,
                  model_name: str) -> bytes | None:
    """Best-effort PNG bytes for an item: flat item/block texture, else model textures."""
    for kind in ("item", "block"):
        candidate = f"assets/{ns}/textures/{kind}/{rel}.png"
        if candidate in names:
            with zf.open(candidate) as f:
                return f.read()

    # Fall back to the texture(s) named inside the model (layer0 first).
    try:
        with zf.open(model_name) as f:
            model = json.loads(f.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
        model = None
    if isinstance(model, dict) and isinstance(model.get("textures"), dict):
        textures = model["textures"]
        ordered = ([textures["layer0"]] if "layer0" in textures else []) + \
                  [v for k, v in textures.items() if k != "layer0"]
        for ref in ordered:
            if not isinstance(ref, str) or not ref:
                continue
            rns, rp = ref.split(":", 1) if ":" in ref else (ns, ref)
            candidate = f"assets/{rns}/textures/{rp}.png"
            if candidate in names:
                with zf.open(candidate) as f:
                    return f.read()
    return None


def parse_jar(jar_path: str) -> ParseResult:
    """Parse one jar into catalog entries + icon bytes.

    Discovery is driven by item model files; duplicate ids keep the first seen. Raises for
    a missing or non-zip file.
    """
    if not os.path.isfile(jar_path):
        raise FileNotFoundError(f"Jar not found: {jar_path}")
    if not zipfile.is_zipfile(jar_path):
        raise ValueError(f"Not a valid jar/zip file: {jar_path}")

    result = ParseResult()
    by_id: dict[str, ItemEntry] = {}
    source = os.path.basename(jar_path)

    with zipfile.ZipFile(jar_path) as zf:
        names = set(zf.namelist())
        display = _display_map(zf)
        for ns, rel, model_name in _iter_item_models(zf):
            item_id = f"{ns}:{rel}"
            if item_id in by_id:
                continue
            by_id[item_id] = ItemEntry(
                id=item_id, namespace=ns, path=rel, kind="item",
                display_name=display.get(item_id) or _prettify(rel),
                source_jar=source,
            )
            icon = _resolve_icon(zf, names, ns, rel, model_name)
            if icon is not None:
                result.icons[item_id] = icon

    result.entries = list(by_id.values())
    return result
