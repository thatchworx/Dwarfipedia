"""
world_update.py  --  re-import a world's legends data without losing your work
=============================================================================

WHY THIS IS MOSTLY ALREADY SAFE

Your edits and the game's data live in different places on purpose:

    worlds/<world>/parsed/     regenerated wholesale on every import
    userdata/*.json            your notes, overrides, tags, galleries,
                               vital fields. Keyed by "world:etype:id"

So a re-import already updates everything you HAVEN'T touched, automatically,
and leaves everything you HAVE touched exactly as you left it. That part
needs no machinery.

WHAT ACTUALLY NEEDS A DECISION

The interesting case is narrower: an entity you edited whose underlying facts
have since changed. You wrote a life story for someone who was alive; a
hundred years later they're dead, and the generated text that would describe
them now says something different from the version you kept. Nobody can
decide that for you, so those go in a queue.

We detect it by comparing the GENERATED text before and after, per edited
section. If the generator's output changed, the facts underneath changed. If
it didn't, your override is still sitting on the same ground and there's
nothing to review.

Also flagged: entities you edited that changed name, and ones that vanished
from the new export entirely.
"""
import json
import os
import shutil
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLDS_DIR = os.path.join(BASE_DIR, "worlds")
USERDATA_DIR = os.path.join(BASE_DIR, "userdata")
CONFLICTS_FILE = os.path.join(USERDATA_DIR, "conflicts.json")


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
def edited_keys(world):
    """Every entity in this world the user has put work into, and what kind of
    work. Anything not in here needs no review. It just updates."""
    out = {}

    def note(key, what):
        if not key.startswith(world + ":"):
            return
        out.setdefault(key, set()).add(what)

    for k in _read(os.path.join(USERDATA_DIR, "flavor_overrides.json"), {}):
        note(k, "text")
    for k, v in _read(os.path.join(USERDATA_DIR, "tags.json"), {}).items():
        if v:
            note(k, "tags")
    for k, v in _read(os.path.join(USERDATA_DIR, "gallery.json"), {}).items():
        if v:
            note(k, "images")
    for k, v in _read(os.path.join(USERDATA_DIR, "vital_fields.json"), {}).items():
        if v:
            note(k, "vitals")
    for k in _read(os.path.join(USERDATA_DIR, "deleted_categories.json"), {}):
        note(k, "deleted sections")
    return {k: sorted(v) for k, v in out.items()}


def snapshot(world, get_record):
    """Fingerprint the edited entities BEFORE the new data lands.

    get_record(etype, eid) -> the raw parsed record, or None.

    We store the entity's name plus the *generated* text of every section the
    user overrode. That generated text is the thing that reveals whether the
    facts moved.
    """
    snap = {}
    overrides = _read(os.path.join(USERDATA_DIR, "flavor_overrides.json"), {})
    for key, kinds in edited_keys(world).items():
        _, etype, eid = key.split(":", 2)
        rec = get_record(etype, eid)
        if rec is None:
            continue
        entry = {"name": rec.get("name") or rec.get("title") or "",
                 "kinds": kinds, "sections": {}}
        ov = overrides.get(key) or {}
        for c in rec.get("flavor", []) or []:
            if c.get("key") in ov:
                entry["sections"][c["key"]] = {"label": c.get("label", c["key"]),
                                               "generated": c.get("text", "")}
        snap[key] = entry
    return snap


def diff(world, before, get_record):
    """Compare the snapshot against the freshly imported data and produce the
    review queue."""
    overrides = _read(os.path.join(USERDATA_DIR, "flavor_overrides.json"), {})
    conflicts = []
    for key, old in before.items():
        _, etype, eid = key.split(":", 2)
        rec = get_record(etype, eid)

        if rec is None:
            conflicts.append({
                "id": key + ":missing", "key": key, "etype": etype, "eid": eid,
                "kind": "missing", "name": old.get("name", ""),
                "detail": "This entity is not in the new export. Your work on it is "
                          "still saved, but the page it belonged to no longer exists.",
            })
            continue

        new_name = rec.get("name") or rec.get("title") or ""
        if old.get("name") and new_name and new_name != old["name"]:
            conflicts.append({
                "id": key + ":name", "key": key, "etype": etype, "eid": eid,
                "kind": "renamed", "name": new_name,
                "old_text": old["name"], "new_text": new_name,
                "detail": "This entity has a different name in the new export.",
            })

        new_by_key = {c.get("key"): c for c in (rec.get("flavor") or [])}
        ov = overrides.get(key) or {}
        for skey, oldsec in (old.get("sections") or {}).items():
            newsec = new_by_key.get(skey)
            if newsec is None:
                continue
            old_gen = (oldsec.get("generated") or "").strip()
            new_gen = (newsec.get("text") or "").strip()
            if old_gen and new_gen and old_gen != new_gen:
                mine = (ov.get(skey) or {}).get("text", "")
                conflicts.append({
                    "id": f"{key}:{skey}", "key": key, "etype": etype, "eid": eid,
                    "section": skey, "kind": "text",
                    "name": new_name, "label": oldsec.get("label", skey),
                    "mine": mine,
                    "old_text": old_gen, "new_text": new_gen,
                    "detail": "The world's own account of this changed, and you have "
                              "your own version saved over it.",
                })
    return conflicts


def store(world, conflicts):
    allc = _read(CONFLICTS_FILE, {})
    allc[world] = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "items": conflicts}
    _write(CONFLICTS_FILE, allc)
    return allc[world]


def get(world):
    return _read(CONFLICTS_FILE, {}).get(world, {"generated": None, "items": []})


def resolve(world, conflict_id, choice, merged_text=None):
    """choice: keep | take | merge

    keep. Leave your override exactly as it is
    take. Drop your override so the world's new account shows through
    merge. Replace your override with text you've edited yourself
    """
    data = get(world)
    items = data.get("items", [])
    item = next((i for i in items if i.get("id") == conflict_id), None)
    if not item:
        return {"ok": False, "error": "no such conflict"}

    if item.get("kind") == "text":
        path = os.path.join(USERDATA_DIR, "flavor_overrides.json")
        ov = _read(path, {})
        entry = ov.get(item["key"]) or {}
        if choice == "take":
            entry.pop(item["section"], None)
            if entry:
                ov[item["key"]] = entry
            else:
                ov.pop(item["key"], None)
            _write(path, ov)
        elif choice == "merge":
            entry[item["section"]] = {"text": merged_text or item.get("new_text", ""),
                                      "source": "edited"}
            ov[item["key"]] = entry
            _write(path, ov)
        # "keep" needs no write at all. That's the point of it

    data["items"] = [i for i in items if i.get("id") != conflict_id]
    allc = _read(CONFLICTS_FILE, {})
    allc[world] = data
    _write(CONFLICTS_FILE, allc)
    return {"ok": True, "remaining": len(data["items"])}


def clear(world):
    allc = _read(CONFLICTS_FILE, {})
    allc.pop(world, None)
    _write(CONFLICTS_FILE, allc)
    return {"ok": True}


# ---------------------------------------------------------------------------
def stage_paths(world):
    wd = os.path.join(WORLDS_DIR, world)
    return wd, os.path.join(wd, "raw"), os.path.join(wd, "raw_incoming")


def accept_upload(world, base_file, plus_file):
    """Put the new XML somewhere safe WITHOUT destroying the current raw
    files, so a failed parse can't leave the world unusable."""
    wd, raw, incoming = stage_paths(world)
    if os.path.isdir(incoming):
        shutil.rmtree(incoming, ignore_errors=True)
    os.makedirs(incoming, exist_ok=True)
    base_file.save(os.path.join(incoming, "legends.xml"))
    plus_file.save(os.path.join(incoming, "legends_plus.xml"))
    return incoming


def promote_incoming(world):
    """Swap the staged XML into place once it has parsed successfully."""
    wd, raw, incoming = stage_paths(world)
    backup = os.path.join(wd, "raw_previous")
    if os.path.isdir(raw):
        shutil.rmtree(backup, ignore_errors=True)
        os.rename(raw, backup)
    os.rename(incoming, raw)
    return backup
