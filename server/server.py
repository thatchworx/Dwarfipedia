"""
server.py  --  DwarfWiki local server
=====================================

A tiny Flask app that:
  * serves the static single-page wiki (../static)
  * serves the parsed world data as JSON APIs (entities are fully hydrated so
    the browser only has to render links, never resolve ids)
  * persists your notes / bookmarks / tags to ../userdata (kept separate from
    parsed world data so re-importing a world never touches what you wrote)
  * auto-imports any world that has raw XML but no parsed JSON on startup

Run:  python server.py         (the DwarfWiki.bat launcher does this for you)
Then: http://localhost:5000
"""

import os
import io
import re
import json
import tempfile
import shutil
import time
import uuid
import zipfile
import threading
from collections import defaultdict

from flask import (Flask, jsonify, request, send_from_directory,
                   send_file, abort, Response)

import parser as dfparser
import flavor_entity
import ai_provider

# ---------------------------------------------------------------------------
# Paths (all relative to this file -> fully portable, no hard-coded C:\ path)
# ---------------------------------------------------------------------------
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SERVER_DIR)
STATIC_DIR = os.path.join(BASE_DIR, "static")
WORLDS_DIR = os.path.join(BASE_DIR, "worlds")
USERDATA_DIR = os.path.join(BASE_DIR, "userdata")
NOTES_DIR = os.path.join(USERDATA_DIR, "notes")
IMAGES_DIR = os.path.join(USERDATA_DIR, "images")
BOOKMARKS_FILE = os.path.join(USERDATA_DIR, "bookmarks.json")
TAGS_FILE = os.path.join(USERDATA_DIR, "tags.json")
WORLD_NAMES_FILE = os.path.join(USERDATA_DIR, "world_names.json")
WORLD_SLOTS_FILE = os.path.join(USERDATA_DIR, "world_slots.json")
ARCHIVED_FILE = os.path.join(USERDATA_DIR, "archived_worlds.json")
GALLERY_FILE = os.path.join(USERDATA_DIR, "gallery.json")
FLAVOR_OVERRIDES_FILE = os.path.join(USERDATA_DIR, "flavor_overrides.json")
DELETED_CATEGORIES_FILE = os.path.join(USERDATA_DIR, "deleted_categories.json")

for d in (USERDATA_DIR, NOTES_DIR, IMAGES_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__, static_folder=None)

# DFCart's map/globe API, folded in as a blueprint. One app, one port.
# Registered right after app creation so its routes exist before the
# catch-all static route below can shadow them.
import cartography_routes
app.register_blueprint(cartography_routes.cart)

# Fortress Mode's DFHack-backed dashboard API. Same "one app, one port"
# reasoning as the map blueprint above.
import fortress
app.register_blueprint(fortress.fortress)

# ---------------------------------------------------------------------------
# World data cache (lazy)
# ---------------------------------------------------------------------------
_worlds = {}          # name -> dict of loaded json (heavy, lazy)
_meta_cache = {}      # name -> meta.json (light, eager)
_lock = threading.Lock()

_HEAVY = ["figures", "sites", "artifacts", "entities", "regions",
          "underground_regions", "written", "identities", "creatures",
          "landmasses", "peaks", "constructions", "events", "collections",
          "search_index", "bestiary"]

TYPE_FILES = {
    "hf": "figures", "site": "sites", "artifact": "artifacts",
    "ent": "entities", "region": "regions", "wc": "written",
    "identity": "identities", "creature": "bestiary",
}


def _load_json(world, name):
    path = os.path.join(WORLDS_DIR, world, "parsed", name + ".json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def refresh_meta():
    _meta_cache.clear()
    for wd in dfparser.discover_worlds():
        name = os.path.basename(wd)
        if dfparser.is_parsed(wd):
            try:
                _meta_cache[name] = _load_json(name, "meta")
            except Exception:
                pass


def get_world(world):
    """Lazy-load and cache a world's heavy data."""
    if world in _worlds:
        return _worlds[world]
    with _lock:
        if world in _worlds:
            return _worlds[world]
        wd = os.path.join(WORLDS_DIR, world)
        if not dfparser.is_parsed(wd):
            abort(404, f"world '{world}' not found or not imported")
        data = {}
        for n in _HEAVY:
            data[n] = _load_json(world, n)
        data["meta"] = _load_json(world, "meta")
        _worlds[world] = data
        return data


def evict(world):
    _worlds.pop(world, None)
    # the map holds its own derived-cartography cache for the same world.
    # Drop it too, or a re-import would refresh the wiki while the map kept
    # serving the old territory/site data until a restart
    cartography_routes.evict_cart_cache(world)


# ---------------------------------------------------------------------------
# Hydration helpers  (turn ids into {t,id,name} link tokens)
# ---------------------------------------------------------------------------
def _name_tables(w):
    return {
        "hf": w["figures"], "site": w["sites"], "artifact": w["artifacts"],
        "ent": w["entities"], "region": w["regions"], "wc": w["written"],
    }


def _link(w, kind, id_):
    if id_ is None:
        return None
    tbl = {"hf": w["figures"], "site": w["sites"], "artifact": w["artifacts"],
           "ent": w["entities"], "region": w["regions"],
           "wc": w["written"]}.get(kind, {})
    rec = tbl.get(str(id_))
    if rec is None:
        return None
    nm = rec.get("name") or rec.get("title") or f"{kind} #{id_}"
    return {"t": kind, "id": id_, "name": nm}


def _events_for(w, ids, limit=None):
    """Return rendered events for a list of ids, sorted by year."""
    ev = w["events"]
    out = []
    for i in ids:
        e = ev.get(str(i))
        if e:
            out.append(dict(e, id=i))
    out.sort(key=lambda e: (e.get("y") is None, e.get("y") or 0))
    return out


def _collections_for(w, ids):
    cols = w["collections"]
    out = []
    for i in ids:
        c = cols.get(str(i))
        if c:
            out.append(dict(c, id=i))
    out.sort(key=lambda c: (c.get("y") is None, c.get("y") or 0))
    return out


# ---------------------------------------------------------------------------
# Static / SPA
# ---------------------------------------------------------------------------
APP_VERSION = "7.1.0"


def _no_cache(resp):
    # index.html is the ENTIRE app (all JS/CSS inlined), if a browser ever
    # caches a stale copy, updates silently stop applying until a hard
    # refresh. That's exactly what happened before this fix, so this is
    # deliberately aggressive rather than a short max-age.
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/")
def index():
    return _no_cache(send_from_directory(STATIC_DIR, "index.html"))


@app.route("/<path:path>")
def static_files(path):
    full = os.path.join(STATIC_DIR, path)
    if os.path.exists(full) and os.path.isfile(full):
        return send_from_directory(STATIC_DIR, path)
    # SPA fallback: unknown non-api paths return the shell
    if not path.startswith("api/") and not path.startswith("userdata/"):
        return _no_cache(send_from_directory(STATIC_DIR, "index.html"))
    abort(404)


@app.route("/api/version")
def api_version():
    return jsonify({"version": APP_VERSION})


def _raw_record(world, etype, eid):
    """Raw parsed record for a world, bypassing all user overlays. The
    world's own account, which is exactly what we need to diff."""
    try:
        w = get_world(world)
    except Exception:
        return None
    tbl = {"hf": "figures", "site": "sites", "artifact": "artifacts",
           "ent": "entities", "wc": "written", "creature": "bestiary",
           "region": "regions"}.get(etype)
    if not tbl:
        return None
    return (w.get(tbl) or {}).get(str(eid))


@app.route("/api/world/<world>/update", methods=["POST"])
def api_world_update(world):
    """Re-import a world from fresh legends XML, keeping your work.

    Everything you haven't edited simply updates. Everything you have edited
    stays exactly as you left it, and where the world's own account of an
    edited thing has since changed, it goes in a review queue instead of
    being silently resolved either way.
    """
    import world_update as wu

    wd = os.path.join(WORLDS_DIR, world)
    if not os.path.isdir(wd):
        abort(404, "no such world")
    base_file = request.files.get("base")
    plus_file = request.files.get("plus")
    if not base_file or not base_file.filename or not plus_file or not plus_file.filename:
        abort(400, "both legends.xml and legends_plus.xml are required")

    # fingerprint what you've edited BEFORE anything is overwritten
    before = wu.snapshot(world, lambda t, i: _raw_record(world, t, i))

    wu.accept_upload(world, base_file, plus_file)

    def _job():
        _reimport_status[world] = "running"
        try:
            incoming = wu.stage_paths(world)[2]
            ok = dfparser.WorldImporter(wd).run(
                base=os.path.join(incoming, "legends.xml"),
                plus=os.path.join(incoming, "legends_plus.xml"))
            if ok is False:
                _reimport_status[world] = "error: the new files failed to parse, " \
                                          "your existing world is untouched"
                return
            wu.promote_incoming(world)
            evict(world)
            refresh_meta()
            conflicts = wu.diff(world, before, lambda t, i: _raw_record(world, t, i))
            wu.store(world, conflicts)
            _reimport_status[world] = f"done: {len(conflicts)} to review"
        except Exception as ex:
            _reimport_status[world] = f"error: {ex}"

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"status": "started", "edited_entities": len(before)})


@app.route("/api/world/<world>/conflicts", methods=["GET", "POST"])
def api_world_conflicts(world):
    import world_update as wu
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        act = body.get("action")
        if act == "clear":
            return jsonify(wu.clear(world))
        return jsonify(wu.resolve(world, body.get("id"), body.get("choice"),
                                  body.get("text")))
    return jsonify(wu.get(world))


@app.route("/api/image_status")
def api_image_status():
    """Whether image generation is usable, and why not if it isn't."""
    import image_provider as ip
    d = ip.PROVIDER.diagnose()
    if not d["reachable"]:
        d["advice"] = ("No image server is answering. Install Forge (or "
                       "AUTOMATIC1111), start it with the --api flag, and leave it "
                       "running while you use DwarfWiki.")
    elif not d["models"]:
        d["advice"] = ("The image server is running but has no model loaded. Put a "
                       "checkpoint in its models/Stable-diffusion folder and select it.")
    else:
        d["advice"] = "Ready."
    return jsonify(d)


@app.route("/api/image_prompts", methods=["GET", "POST"])
def api_image_prompts():
    import image_provider as ip
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        if body.get("action") == "reset":
            return jsonify(ip.reset())
        return jsonify(ip.save(body))
    out = ip.load()
    out["defaults"] = ip.DEFAULTS
    return jsonify(out)


@app.route("/api/generate_image/<world>/<etype>/<int:eid>", methods=["POST"])
def api_generate_image(world, etype, eid):
    """Draw a picture for an entity and file it in that entity's gallery.

    Generated images go through the same storage as uploads, so everything
    already built for images. Starring one as the card thumbnail, attaching
    one to a section. Works on these with no special cases.
    """
    import image_provider as ip

    body = request.get_json(silent=True) or {}
    kind = body.get("kind", "portrait")
    rec = _raw_record(world, etype, eid)
    if rec is None:
        abort(404, "no such entity")

    name = rec.get("name") or rec.get("title") or "a figure"
    if kind == "scene":
        scene = body.get("scene") or ""
        if not scene:
            # fall back to the entity's own first passage
            fl = rec.get("flavor") or []
            scene = (fl[0].get("text") if fl else "") or ""
        subject = (f"{rec.get('race','')} {rec.get('sex','')}".strip()
                   if etype == "hf" else name)
        positive, negative, seeds = ip.build_prompt(
            "scene", subject=subject, scene=scene, etype=etype)
        caption = body.get("caption") or (body.get("label") or "Scene")
    else:
        positive, negative, seeds = ip.build_prompt(
            "portrait", subject=name,
            descriptors=ip.describe_entity(etype, rec), etype=etype)
        caption = body.get("caption") or ("Portrait" if etype == "hf" else "Illustration")

    try:
        raw = ip.PROVIDER.generate(positive, negative)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    fname = ip.save_png(raw)
    key = f"{world}:{etype}:{eid}"
    gal = _gallery_all()
    items = gal.get(key, [])
    items.append({"id": uuid.uuid4().hex[:12], "filename": fname,
                  "caption": caption, "generated": True,
                  "added": time.strftime("%Y-%m-%d %H:%M:%S")})
    gal[key] = items
    _write_json(GALLERY_FILE, gal)
    return jsonify({"filename": fname, "caption": caption, "seeds": seeds,
                    "prompt": positive, "images": items})


@app.route("/api/prompts", methods=["GET", "POST"])
def api_prompts():
    """Read or write the generation prompts and style seeds. Stored in
    userdata/ so edits survive updates."""
    import prompts as _p
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        if body.get("action") == "reset":
            return jsonify(_p.reset())
        return jsonify(_p.save(body))
    out = _p.load()
    out["defaults"] = _p.DEFAULTS
    return jsonify(out)


@app.route("/api/prompts/preview")
def api_prompts_preview():
    """Show exactly what a generation would be sent right now, style seeds
    and all, so you can see the effect of an edit without spending a
    generation to find out."""
    import prompts as _p
    kind = request.args.get("kind", "biography")
    text, seeds = _p.build_system(kind)
    return jsonify({"kind": kind, "system": text, "seeds": seeds})


@app.route("/api/ai_status")
def api_ai_status():
    """Why generation isn't working, in one request. Reports what the server
    is actually configured to talk to and what that machine actually has,
    rather than leaving you to infer it from a timeout."""
    prov = ai_provider.PROVIDER
    if hasattr(prov, "diagnose"):
        d = prov.diagnose()
    else:
        d = {"host": None, "model": None, "reachable": prov.available(),
             "model_installed": None, "installed_models": []}
    d["provider"] = getattr(prov, "name", "unknown")
    if not d.get("reachable"):
        d["advice"] = ("Ollama isn't answering. Start it (run `ollama serve`, or "
                       "launch the Ollama app) and try again. Note this is an HTTP "
                       "connection to localhost. Where DwarfWiki sits on disk has "
                       "no bearing on it.")
    elif d.get("model_installed") is False:
        d["advice"] = (f"Ollama is running but has no model called '{d['model']}'. "
                       f"Either run `ollama pull {d['model']}`, or point DwarfWiki at "
                       f"one you already have by setting DWARFWIKI_MODEL.")
    else:
        d["advice"] = "Ready."
    return jsonify(d)


@app.route("/userdata/images/<path:fname>")
def user_image(fname):
    return send_from_directory(IMAGES_DIR, fname)


# ---------------------------------------------------------------------------
# API : worlds & meta
# ---------------------------------------------------------------------------
def _world_names():
    return _read_json(WORLD_NAMES_FILE, {})


def _world_slots():
    return _read_json(WORLD_SLOTS_FILE, {})


def _next_free_slot(slots, exclude=None):
    used = {s for w, s in slots.items() if w != exclude}
    n = 1
    while n in used:
        n += 1
    return n


@app.route("/api/worlds")
def api_worlds():
    refresh_meta()
    names = _world_names()
    slots = _world_slots()
    archived = _archived_worlds()
    changed = False
    out = []
    for name, meta in sorted(_meta_cache.items()):
        if name not in slots:
            slots[name] = _next_free_slot(slots)
            changed = True
        out.append({
            "name": name,
            "world_name": names.get(name, meta.get("world_name", name)),
            "year_max": meta.get("year_max"),
            "counts": meta.get("counts", {}),
            "loaded": name in _worlds,
            "slot": slots[name],
            "archived": name in archived,
        })
    if changed:
        _write_json(WORLD_SLOTS_FILE, slots)
    # also surface un-imported worlds (raw present, not parsed)
    pending = []
    for wd in dfparser.discover_worlds():
        n = os.path.basename(wd)
        if not dfparser.is_parsed(wd):
            pending.append(n)
    return jsonify({"worlds": out, "pending": pending})


def _archived_worlds():
    """Slugs the user has archived. This is purely a display flag. Nothing
    on disk is ever touched. Real deletion is left as a manual folder
    removal on purpose: this app should never be the thing that eats an
    irreplaceable import."""
    return set(_read_json(ARCHIVED_FILE, []))


@app.route("/api/world/<world>/archive", methods=["POST"])
def api_world_archive(world):
    body = request.get_json(silent=True) or {}
    archived = _archived_worlds()
    if body.get("archived", True):
        archived.add(world)
    else:
        archived.discard(world)
    _write_json(ARCHIVED_FILE, sorted(archived))
    return jsonify({"world": world, "archived": world in archived})


@app.route("/api/world_meta/<world>", methods=["POST"])
def world_meta_post(world):
    """
    body: {action:'rename', name}      -> override display name (folder/id
                                           on disk never changes, display only)
          {action:'set_slot', slot}    -> move to a specific Atlas grid slot;
                                           if occupied, swaps with the occupant
    """
    body = request.get_json(force=True)
    action = body.get("action")

    if action == "rename":
        names = _world_names()
        new_name = (body.get("name") or "").strip()
        names[world] = new_name or world
        _write_json(WORLD_NAMES_FILE, names)
        return jsonify({"world_name": names[world]})

    if action == "set_slot":
        slots = _world_slots()
        try:
            new_slot = int(body.get("slot"))
        except (TypeError, ValueError):
            abort(400, "slot must be a number")
        if new_slot < 1:
            abort(400, "slot must be 1 or higher")
        old_slot = slots.get(world)
        occupant = next((w for w, s in slots.items() if s == new_slot and w != world), None)
        slots[world] = new_slot
        if occupant:
            slots[occupant] = old_slot if old_slot is not None else _next_free_slot(slots, exclude=occupant)
        _write_json(WORLD_SLOTS_FILE, slots)
        return jsonify({"slots": slots})

    abort(400, "unknown action")


@app.route("/api/w/<world>/meta")
def api_meta(world):
    w = get_world(world)
    meta = dict(w["meta"])
    # The map view needs the world's size in tiles to compute its draw
    # rectangle. meta.json doesn't carry it (map.json does), and without it
    # the renderer computes NaN dimensions and silently paints nothing,
    # a blank map with no error anywhere. Merge it in here so every consumer
    # of /meta gets a complete picture.
    if "width" not in meta:
        mm = _load_json(world, "map") or {}
        if mm.get("width"):
            meta["width"] = mm["width"]
            meta["height"] = mm.get("height", mm["width"])
    return jsonify(meta)


@app.route("/api/w/<world>/map.png")
def api_map_png(world):
    wd = os.path.join(WORLDS_DIR, world)
    if not dfparser.is_parsed(wd):
        abort(404)
    path = os.path.join(wd, "parsed", "map.png")
    if not os.path.exists(path):
        abort(404, "this world has no rendered map (re-import to generate one)")
    return send_file(path, mimetype="image/png")


@app.route("/api/w/<world>/heightmap.png")
def api_heightmap_png(world):
    """Grayscale elevation approximation for importing into Azgaar's Fantasy
    Map Generator. Derived from real biome type (DF's own elevation export
    isn't available on Steam DF), not real elevation data. Smoothed so it
    reads as gradients rather than blocky steps."""
    wd = os.path.join(WORLDS_DIR, world)
    if not dfparser.is_parsed(wd):
        abort(404)
    path = os.path.join(wd, "parsed", "heightmap.png")
    if not os.path.exists(path):
        abort(404, "this world has no heightmap yet (re-import to generate one)")
    return send_file(path, mimetype="image/png", as_attachment=True,
                     download_name=f"{world}-heightmap.png")


@app.route("/api/w/<world>/map.json")
def api_map_json(world):
    wd = os.path.join(WORLDS_DIR, world)
    if not dfparser.is_parsed(wd):
        abort(404)
    return jsonify(_load_json(world, "map"))


@app.route("/api/w/<world>/map_sites")
def api_map_sites(world):
    """Lightweight all-sites payload for map pins (id, name, type, coords, notable)."""
    w = get_world(world)
    out = []
    for i, s in w["sites"].items():
        coords = s.get("coords")
        if not coords or "," not in coords:
            continue
        try:
            x, y = (int(v) for v in coords.split(",", 1))
        except ValueError:
            continue
        out.append({"id": int(i), "name": s.get("name") or f"site #{i}",
                    "type": s.get("type"), "x": x, "y": y,
                    "notable": bool(s.get("name")),
                    "events": s.get("n_events", 0)})
    return jsonify({"sites": out})


# ---------------------------------------------------------------------------
# API : entity detail (fully hydrated)
# ---------------------------------------------------------------------------
@app.route("/api/w/<world>/entity/<etype>/<int:eid>")
def api_entity(world, etype, eid):
    w = get_world(world)
    fname = TYPE_FILES.get(etype)
    if fname is None:
        abort(404, "unknown entity type")
    rec = w[fname].get(str(eid))
    if rec is None:
        abort(404, "not found")
    out = dict(rec)
    out["_type"] = etype

    # split this entity's events into notable vs the rest
    ev_ids = rec.get("event_ids", [])
    events = _events_for(w, ev_ids)
    notable, other = [], []
    for e in events:
        (notable if e["cat"] in dfparser.ER.NOTABLE_CATEGORIES else other).append(e)
    out["events_notable"] = notable
    out["events_other"] = other
    out["event_count"] = len(events)

    # type-specific hydration
    if etype == "hf":
        out["entity_links_h"] = [
            dict(link=l.get("type"), ent=_link(w, "ent", l.get("entity_id")))
            for l in rec.get("entity_links", []) if _link(w, "ent", l.get("entity_id"))
        ]
        out["site_links_h"] = [
            dict(link=l.get("type"), site=_link(w, "site", l.get("site_id")))
            for l in rec.get("site_links", []) if _link(w, "site", l.get("site_id"))
        ]
        rels = []
        for r in rec.get("relationships", []):
            lk = _link(w, "hf", r.get("hf"))
            if lk:
                rels.append(dict(rel=r.get("rel"), year=r.get("year"), hf=lk))
        out["relationships_h"] = rels
        out["holder_of"] = None
        # real coords for the map swatch. The person's own primary site link
        site_links = rec.get("site_links") or []
        if site_links:
            site = w["sites"].get(str(site_links[0].get("site_id")))
            out["map_coords"] = site.get("coords") if site else None

    elif etype == "site":
        out["collections_h"] = _collections_for(w, rec.get("collection_ids", []))
        # which civ(s) own this site (reverse lookup)
        owners = []
        merchant_companies = []
        for i, e in w["entities"].items():
            if eid in (e.get("owned_site_ids") or []):
                lk = _link(w, "ent", int(i))
                if lk:
                    owners.append(lk)
                    if (e.get("type") or "").lower() == "merchantcompany":
                        merchant_companies.append(lk)
        out["owners_h"] = owners
        out["merchant_companies_h"] = merchant_companies
        # real artifacts physically located at this site (site_id captured
        # from the base legends.xml. Most artifacts have it, some don't)
        goods = []
        for i, a in w["artifacts"].items():
            if a.get("site_id") == eid and a.get("name"):
                goods.append({"id": int(i), "name": a["name"], "type": a.get("item_type"),
                             "material": a.get("material"), "notable": a.get("notable")})
        goods.sort(key=lambda g: (not g["notable"]))
        out["goods_h"] = goods[:40]
        out["extra_flavor"] = _build_extra_flavor(world, "site", eid)

    elif etype == "artifact":
        out["holder_h"] = _link(w, "hf", rec.get("holder_hfid"))
        out["site_h"] = _link(w, "site", rec.get("site_id"))
        if rec.get("site_id") is not None:
            site = w["sites"].get(str(rec["site_id"]))
            out["map_coords"] = site.get("coords") if site else None
        out["extra_flavor"] = _build_extra_flavor(world, "artifact", eid)

    elif etype == "ent":
        out["owned_sites_h"] = [x for x in
                                (_link(w, "site", s) for s in rec.get("owned_site_ids", []))
                                if x]
        out["members_h"] = None  # members are large; fetched on demand
        out["children_h"] = [x for x in
                             (_link(w, "ent", c) for c in rec.get("children", []))
                             if x]
        out["extra_flavor"] = _build_extra_flavor(world, "ent", eid)
        owned = rec.get("owned_site_ids") or []
        if owned:
            site = w["sites"].get(str(owned[0]))
            out["map_coords"] = site.get("coords") if site else None

    elif etype == "wc":
        out["author_h"] = _link(w, "hf", rec.get("author_hfid"))
        out["extra_flavor"] = _build_extra_flavor(world, "wc", eid)

    elif etype == "region":
        out["extra_flavor"] = _build_extra_flavor(world, "region", eid)

    elif etype == "creature":
        out["notable_specimens_h"] = [
            dict(s, hf=_link(w, "hf", s.get("id")))
            for s in rec.get("notable_specimens", [])
        ]

    # apply any manual flavor overrides (never mutate the cached original)
    # and attach a source tag per category for the [wordbank text]/[edited]/
    # [llm text] badge next to each heading
    # sites, civs, artifacts, written works and regions get their wordbank
    # sections built on demand. They aren't baked into parsed/ the way
    # figures and creatures are, so importing a world doesn't need redoing
    if etype in flavor_entity.BY_TYPE and not rec.get("flavor"):
        try:
            rec = dict(rec)
            rec["flavor"] = flavor_entity.compute_categories(etype, eid, rec)
        except Exception:
            pass

    if rec.get("flavor"):
        ov = _flavor_overrides_get(f"{world}:{etype}:{eid}")
        deleted = _deleted_categories_get(f"{world}:{etype}:{eid}")
        out["flavor"] = []
        for c in rec["flavor"]:
            if c["key"] in deleted:
                continue
            entry = ov.get(c["key"])
            if entry:
                out["flavor"].append(dict(c, text=entry["text"], overridden=True,
                                          source=entry.get("source", "edited"),
                                          model=entry.get("model")))
            else:
                out["flavor"].append(dict(c, overridden=False, source="wordbank", model=None))

    # user data attached
    key = f"{world}:{etype}:{eid}"
    out["_tags"] = _tags_get(key)
    out["_bookmarked"] = _is_bookmarked(world, etype, eid)
    out["_gallery"] = _gallery_get(key)
    out["_vitals"] = _read_json(VITALS_FILE, {}).get(key, [])
    _bk = _read_json(BOOKS_FILE, {}).get(key)
    out["_book_pages"] = len(_bk.get("pages", [])) if _bk else 0
    return jsonify(out)


@app.route("/api/w/<world>/members/<int:eid>")
def api_members(world, eid):
    """Members of a civ (paginated). Separate because civs can have 100s."""
    w = get_world(world)
    ent = w["entities"].get(str(eid))
    if ent is None:
        abort(404)
    # gather members from figures whose entity_links include this entity
    members = []
    for i, f in w["figures"].items():
        for l in f.get("entity_links", []):
            if l.get("entity_id") == eid:
                members.append({"id": int(i), "name": f.get("name"),
                                "race": f.get("race"),
                                "link": l.get("type"),
                                "dead": f.get("death_year", -1) not in (None, -1)})
                break
    members.sort(key=lambda m: (m["dead"], m["name"] or ""))
    page = int(request.args.get("page", 0))
    per = 50
    return jsonify({"total": len(members),
                    "items": members[page * per:(page + 1) * per],
                    "page": page, "per": per})


# ---------------------------------------------------------------------------
# API : browse lists (paginated, sortable)
# ---------------------------------------------------------------------------
LIST_TYPES = {
    "hf": "figures", "site": "sites", "artifact": "artifacts",
    "ent": "entities", "wc": "written", "region": "regions", "creature": "bestiary",
}


@app.route("/api/w/<world>/list/<etype>")
def api_list(world, etype):
    w = get_world(world)
    fname = LIST_TYPES.get(etype)
    if fname is None:
        abort(404)
    q = (request.args.get("q") or "").lower().strip()
    sort = request.args.get("sort", "notable")
    only_notable = request.args.get("notable") == "1"
    page = int(request.args.get("page", 0))
    per = int(request.args.get("per", 60))
    fil = request.args.get("filter")   # e.g. race / type / form

    items = []
    for i, r in w[fname].items():
        nm = r.get("name") or r.get("title") or (r.get("race") or "").title() or None
        if not nm:
            if etype in ("hf",):  # unnamed figures still allowed via toggle
                if only_notable:
                    continue
            else:
                continue
        if q and (nm is None or q not in nm.lower()):
            continue
        if only_notable and not r.get("notable", True):
            continue
        if etype == "creature":
            sub = f"{r.get('population_named', 0)} recorded"
        else:
            sub = (r.get("race") or r.get("type") or r.get("form") or "")
        if fil and sub != fil:
            continue
        items.append({
            "id": int(i), "name": nm or f"#{i}", "sub": sub,
            "notable": r.get("notable", True),
            "events": r.get("n_events", r.get("total_events", 0)),
            "dead": (r.get("death_year", -1) not in (None, -1)) if etype == "hf" else None,
            "born": r.get("birth_year") if etype == "hf" else None,
        })

    if sort == "name":
        items.sort(key=lambda x: (x["name"] or "").lower())
    elif sort == "events":
        items.sort(key=lambda x: -x["events"])
    else:  # notable first, then event count
        items.sort(key=lambda x: (not x["notable"], -x["events"], (x["name"] or "").lower()))

    total = len(items)
    page_items = items[page * per:(page + 1) * per]
    # attach the starred thumbnail for just this page's items. Looking up the
    # gallery for every entity in a 26,000-figure world would be pointless
    # work when only 60 are on screen
    gal = _gallery_all()
    for it in page_items:
        imgs = gal.get(f"{world}:{etype}:{it['id']}")
        if not imgs:
            continue
        pick = next((im for im in imgs if im.get("starred")), imgs[0])
        it["thumb"] = pick.get("filename")
    return jsonify({"total": total, "page": page, "per": per,
                    "items": page_items})


@app.route("/api/w/<world>/events")
def api_events_batch(world):
    w = get_world(world)
    ids = [i for i in (request.args.get("ids", "").split(",")) if i]
    return jsonify(_events_for(w, ids))


# ---------------------------------------------------------------------------
# API : timeline
# ---------------------------------------------------------------------------
@app.route("/api/w/<world>/timeline")
def api_timeline(world):
    w = get_world(world)
    cat = request.args.get("cat")           # optional category filter
    kind = request.args.get("kind", "collections")  # collections | events
    page = int(request.args.get("page", 0))
    per = int(request.args.get("per", 80))

    src = w["collections"] if kind == "collections" else w["events"]
    items = []
    for i, e in src.items():
        if cat and e.get("cat") != cat:
            continue
        if kind == "events" and e.get("cat") not in dfparser.ER.NOTABLE_CATEGORIES and not cat:
            continue
        items.append(dict(e, id=int(i)))
    items.sort(key=lambda e: (e.get("y") is None, e.get("y") or 0))
    total = len(items)
    return jsonify({"total": total, "page": page, "per": per,
                    "items": items[page * per:(page + 1) * per]})


# The dwarven calendar: 12 months of 28 days = 336 days/year, and DF's
# events carry a within-year tick count ("seconds72") at 1200 ticks/day.
# Both figures confirmed against a real exported legends.xml, not assumed.
# -1 (or missing) means "no time-of-year on record" (mostly worldgen-era
# events), which the calendar just doesn't place on a day.
_TICKS_PER_DAY = 1200
_DAYS_PER_MONTH = 28


def _s72_to_month_day(s72):
    try:
        s72 = int(s72)
    except (TypeError, ValueError):
        return None, None
    if s72 < 0:
        return None, None
    day_index = s72 // _TICKS_PER_DAY
    month = day_index // _DAYS_PER_MONTH + 1
    day = day_index % _DAYS_PER_MONTH + 1
    if month > 12:
        return None, None
    return month, day


@app.route("/api/w/<world>/calendar")
def api_calendar(world):
    """Every event with a recorded time-of-year, for one year, grouped by
    month-day. What the Calendar tool's markers are built from. Reuses the
    same rendered token format as the Timeline (renderTokens on the client
    already knows how to turn these into clickable prose)."""
    w = get_world(world)
    try:
        year = int(request.args.get("year"))
    except (TypeError, ValueError):
        return jsonify({"error": "year required"}), 400

    days = {}
    for i, e in w["events"].items():
        if e.get("y") != year:
            continue
        month, day = _s72_to_month_day(e.get("s72"))
        if month is None:
            continue
        key = f"{month}-{day}"
        days.setdefault(key, []).append({
            "id": int(i), "cat": e.get("cat"), "type": e.get("type"),
            "tokens": e.get("tokens"),
        })
    return jsonify({"year": year, "days": days})


# ---------------------------------------------------------------------------
# API : search
# ---------------------------------------------------------------------------
@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").lower().strip()
    world = request.args.get("world")
    limit = int(request.args.get("limit", 40))
    if not q:
        return jsonify({"results": []})

    worlds = [world] if world else list(_meta_cache.keys())
    results = []
    for wn in worlds:
        try:
            w = get_world(wn)
        except Exception:
            continue
        for row in w["search_index"]:
            n = row["n"].lower()
            if q in n:
                score = (0 if n.startswith(q) else 1,
                         0 if row.get("notable") else 1, len(n))
                results.append((score, dict(row, world=wn)))
    results.sort(key=lambda r: r[0])
    return jsonify({"results": [r[1] for r in results[:limit]]})


# ---------------------------------------------------------------------------
# API : headlines (GTA-style randomised, weighted to narrative events)
# ---------------------------------------------------------------------------
import random


@app.route("/api/headlines")
def api_headlines():
    world = request.args.get("world")
    if not world:
        if not _meta_cache:
            return jsonify({"headlines": []})
        world = sorted(_meta_cache.keys())[0]
    w = get_world(world)
    n = int(request.args.get("n", 24))

    pool = []
    # collections weighted heavily (wars, battles, beast attacks – the juicy bits)
    for i, c in w["collections"].items():
        weight = {"war": 6, "battle": 3, "site conquered": 5, "beast attack": 5,
                  "duel": 3, "abduction": 2, "persecution": 3,
                  "entity overthrown": 5, "raid": 2}.get(c.get("type"), 1)
        if c.get("name"):
            weight += 3
        if c.get("deaths"):
            weight += min(c["deaths"], 5)
        pool.append((weight, "col", i, c))
    # notable events (deaths of notable figures, artifact creation, etc.)
    for i, e in w["events"].items():
        if e.get("cat") in (dfparser.ER.CAT_LIFE, dfparser.ER.CAT_CREATION,
                            dfparser.ER.CAT_COMBAT):
            pool.append((2, "ev", i, e))

    # weighted sample without replacement
    chosen = []
    seen = set()
    tries = 0
    total_w = sum(p[0] for p in pool) or 1
    while len(chosen) < n and tries < n * 40 and pool:
        r = random.uniform(0, total_w)
        acc = 0
        for p in pool:
            acc += p[0]
            if acc >= r:
                key = (p[1], p[2])
                if key not in seen:
                    seen.add(key)
                    chosen.append(p)
                break
        tries += 1

    out = []
    for weight, kind, i, e in chosen:
        out.append({
            "kind": "collection" if kind == "col" else "event",
            "id": int(i),
            "y": e.get("y"),
            "type": e.get("type"),
            "cat": e.get("cat"),
            "tokens": e.get("tokens"),
        })
    out.sort(key=lambda h: (h.get("y") is None, -(h.get("y") or 0)))
    return jsonify({"world": world, "headlines": out})


# ---------------------------------------------------------------------------
# API : random (homepage "Random" button) & spotlight (World Stats widgets)
# ---------------------------------------------------------------------------
_RANDOM_TYPES = {
    "hf": ("figures", lambda r: r.get("notable")),
    "site": ("sites", lambda r: bool(r.get("name"))),
    "artifact": ("artifacts", lambda r: r.get("notable")),
    "ent": ("entities", lambda r: r.get("notable")),
}


def _pick_random_entity(w):
    """Pick a random TYPE first (equal weight), then a random notable item
    of that type. Avoids figures (by far the largest pool) drowning out
    sites/artifacts/civs the way pure pooling would."""
    types = list(_RANDOM_TYPES.keys())
    random.shuffle(types)
    for t in types:
        fname, pred = _RANDOM_TYPES[t]
        pool = [i for i, r in w[fname].items() if pred(r)]
        if pool:
            i = random.choice(pool)
            rec = w[fname][i]
            return {"type": t, "id": int(i), "name": rec.get("name") or rec.get("title")}
    return None


@app.route("/api/random")
def api_random():
    """Random world (equal weight across all loaded worlds), then a random
    notable entity within it. The homepage 'Random' button."""
    refresh_meta()
    names = list(_meta_cache.keys())
    if not names:
        abort(404, "no worlds loaded")
    world = random.choice(names)
    w = get_world(world)
    pick = _pick_random_entity(w)
    if not pick:
        abort(404, "nothing notable to pick")
    pick["world"] = world
    return jsonify(pick)


@app.route("/api/w/<world>/spotlight")
def api_spotlight(world):
    """A handful of random notable picks for the World Stats page. Reshuffles
    on every request, same 'fresh each visit' spirit as headlines."""
    w = get_world(world)
    picks = []
    seen = set()
    tries = 0
    while len(picks) < 4 and tries < 20:
        p = _pick_random_entity(w)
        tries += 1
        if p and (p["type"], p["id"]) not in seen:
            seen.add((p["type"], p["id"]))
            picks.append(p)
    return jsonify({"spotlight": picks})


# ---------------------------------------------------------------------------
# API : year queries ("what happened in year 88", "deaths between 33-50")
# ---------------------------------------------------------------------------
@app.route("/api/w/<world>/year/<int:year>")
def api_year(world, year):
    """What happened in a specific year. Filters the (small, ~16.7k)
    collections list live; no index needed at this scale."""
    w = get_world(world)
    items = [dict(c, id=int(i)) for i, c in w["collections"].items() if c.get("y") == year]
    # also surface notable single events that year (deaths, creations, etc.)
    for i, e in w["events"].items():
        if e.get("y") == year and e.get("cat") in dfparser.ER.NOTABLE_CATEGORIES:
            items.append(dict(e, id=int(i), kind="event"))
    items.sort(key=lambda x: x.get("cat") != "politics")  # rough: wars/politics first
    return jsonify({"year": year, "items": items[:200], "total": len(items)})


@app.route("/api/w/<world>/year_range")
def api_year_range(world):
    """Aggregate category tallies across a year range. Reads the precomputed
    year_stats.json (one small dict lookup per year in range), not a live
    scan of 200k+ events."""
    try:
        start = int(request.args.get("start"))
        end = int(request.args.get("end"))
    except (TypeError, ValueError):
        abort(400, "start and end must be numbers")
    if end < start:
        start, end = end, start
    ys = _load_json(world, "year_stats")
    totals = defaultdict(int)
    years_present = 0
    for y in range(start, end + 1):
        row = ys.get(str(y))
        if not row:
            continue
        years_present += 1
        for cat, n in row.items():
            totals[cat] += n
    return jsonify({"start": start, "end": end, "years_with_data": years_present,
                    "totals": dict(totals)})


# ===========================================================================
# USER DATA : notes, bookmarks, tags, upload, export
# ===========================================================================
def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---- notes ----------------------------------------------------------------
def _notes_path(world, etype, eid):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", f"{etype}_{eid}")
    d = os.path.join(NOTES_DIR, re.sub(r"[^A-Za-z0-9_-]", "_", world))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, safe + ".json")


@app.route("/api/notes/<world>/<etype>/<int:eid>", methods=["GET"])
def notes_get(world, etype, eid):
    return jsonify(_read_json(_notes_path(world, etype, eid), {"notes": []}))


@app.route("/api/notes/<world>/<etype>/<int:eid>", methods=["POST"])
def notes_post(world, etype, eid):
    """
    body: {action:'add', heading, text, images?}         -> new note
          {action:'edit', id, heading, text}             -> new version (history kept)
          {action:'delete', id}                          -> remove a note
    """
    body = request.get_json(force=True)
    path = _notes_path(world, etype, eid)
    doc = _read_json(path, {"notes": []})
    action = body.get("action", "add")
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    if action == "add":
        note = {
            "id": uuid.uuid4().hex[:12],
            "created": now,
            "heading": (body.get("heading") or "").strip(),
            "images": body.get("images", []),
            "versions": [{"text": body.get("text", ""), "ts": now}],
        }
        doc["notes"].append(note)
    elif action == "edit":
        for note in doc["notes"]:
            if note["id"] == body.get("id"):
                if "heading" in body:
                    note["heading"] = (body.get("heading") or "").strip()
                # keep old version underneath; append the new one
                note.setdefault("versions", []).append(
                    {"text": body.get("text", ""), "ts": now})
                if "images" in body:
                    note["images"] = body["images"]
                break
    elif action == "delete":
        doc["notes"] = [n for n in doc["notes"] if n["id"] != body.get("id")]

    _write_json(path, doc)
    return jsonify(doc)


# ---- bookmarks ------------------------------------------------------------
def _bookmarks():
    return _read_json(BOOKMARKS_FILE, {"folders": [], "items": []})


def _is_bookmarked(world, etype, eid):
    for b in _bookmarks()["items"]:
        if b["world"] == world and b["type"] == etype and b["eid"] == eid:
            return True
    return False


@app.route("/api/bookmarks", methods=["GET"])
def bookmarks_get():
    return jsonify(_bookmarks())


@app.route("/api/bookmarks", methods=["POST"])
def bookmarks_post():
    """
    body actions:
      {action:'add', world,type,eid,title,subtitle,folder?,icon?}
      {action:'remove', id}  OR {action:'remove', world,type,eid}
      {action:'move', id, folder}
      {action:'add_folder', name, icon?}
      {action:'remove_folder', folder_id}   (items revert to no folder)
      {action:'rename_folder', folder_id, name}
    """
    body = request.get_json(force=True)
    bm = _bookmarks()
    action = body.get("action")

    if action == "add":
        # de-dupe
        for b in bm["items"]:
            if (b["world"] == body["world"] and b["type"] == body["type"]
                    and b["eid"] == body["eid"]):
                return jsonify(bm)
        bm["items"].append({
            "id": uuid.uuid4().hex[:12],
            "world": body["world"], "type": body["type"], "eid": body["eid"],
            "title": body.get("title", ""), "subtitle": body.get("subtitle", ""),
            "folder": body.get("folder"), "icon": body.get("icon", "bookmark"),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    elif action == "remove":
        if "id" in body:
            bm["items"] = [b for b in bm["items"] if b["id"] != body["id"]]
        else:
            bm["items"] = [b for b in bm["items"] if not (
                b["world"] == body.get("world") and b["type"] == body.get("type")
                and b["eid"] == body.get("eid"))]
    elif action == "move":
        for b in bm["items"]:
            if b["id"] == body["id"]:
                b["folder"] = body.get("folder")
    elif action == "set_icon":
        for b in bm["items"]:
            if b["id"] == body["id"]:
                b["icon"] = body.get("icon", "bookmark")
    elif action == "add_folder":
        bm["folders"].append({"id": uuid.uuid4().hex[:8],
                              "name": body.get("name", "Folder"),
                              "icon": body.get("icon", "folder")})
    elif action == "remove_folder":
        fid = body.get("folder_id")
        bm["folders"] = [f for f in bm["folders"] if f["id"] != fid]
        for b in bm["items"]:
            if b.get("folder") == fid:
                b["folder"] = None
    elif action == "rename_folder":
        for f in bm["folders"]:
            if f["id"] == body.get("folder_id"):
                f["name"] = body.get("name", f["name"])

    _write_json(BOOKMARKS_FILE, bm)
    return jsonify(bm)


# ---- adventurers (Adventure Mode character manager) -----------------------
# Placeholder storage, deliberately shipped ahead of the UI so the feature has
# somewhere to live and so saved characters survive from the moment it exists.
# Free-form: a character is whatever dict the client sends, plus an id. The
# schema will firm up once we design the manager properly.
ADVENTURERS_FILE = os.path.join(USERDATA_DIR, "adventurers.json")


@app.route("/api/adventurers/<world>", methods=["GET"])
def adventurers_get(world):
    return jsonify({"adventurers": _read_json(ADVENTURERS_FILE, {}).get(world, [])})


@app.route("/api/adventurers/<world>", methods=["POST"])
def adventurers_post(world):
    body = request.get_json(force=True) or {}
    action = body.get("action", "save")
    all_adv = _read_json(ADVENTURERS_FILE, {})
    lst = all_adv.get(world, [])
    if action == "save":
        ch = dict(body.get("character") or {})
        cid = ch.get("id") or uuid.uuid4().hex[:10]
        ch["id"] = cid
        for i, existing in enumerate(lst):
            if existing.get("id") == cid:
                lst[i] = ch
                break
        else:
            lst.append(ch)
    elif action == "remove":
        lst = [c for c in lst if c.get("id") != body.get("id")]
    all_adv[world] = lst
    _write_json(ADVENTURERS_FILE, all_adv)
    return jsonify({"adventurers": lst})


# ---- custom vital-record fields -------------------------------------------
# Entirely user-authored. Nothing here is generated or touched by the
# wordbank or the AI. It's a place to record things the legends export
# simply doesn't contain (titles, epithets, a headcanon cause of death) and
# have them sit in the infobox alongside the real data.
VITALS_FILE = os.path.join(USERDATA_DIR, "vital_fields.json")
BOOKS_FILE = os.path.join(USERDATA_DIR, "books.json")


@app.route("/api/vitals/<world>/<etype>/<int:eid>", methods=["GET", "POST"])
def vitals_ep(world, etype, eid):
    key = f"{world}:{etype}:{eid}"
    allv = _read_json(VITALS_FILE, {})
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        act = body.get("action", "set")
        rows = allv.get(key, [])
        if act == "set":
            label = (body.get("label") or "").strip()
            value = (body.get("value") or "").strip()
            if not label:
                abort(400, "label is required")
            idx = body.get("index")
            if idx is not None and 0 <= int(idx) < len(rows):
                rows[int(idx)] = {"label": label, "value": value}
            else:
                rows.append({"label": label, "value": value})
        elif act == "remove":
            idx = int(body.get("index", -1))
            if 0 <= idx < len(rows):
                rows.pop(idx)
        elif act == "reorder":
            order = body.get("order") or []
            if len(order) == len(rows):
                rows = [rows[i] for i in order]
        if rows:
            allv[key] = rows
        else:
            allv.pop(key, None)
        _write_json(VITALS_FILE, allv)
    return jsonify({"fields": allv.get(key, [])})


# ---- tags -----------------------------------------------------------------
def _tags_all():
    return _read_json(TAGS_FILE, {})


def _tags_get(key):
    return _tags_all().get(key, [])


@app.route("/api/tags/<world>/<etype>/<int:eid>", methods=["GET", "POST"])
def tags_ep(world, etype, eid):
    key = f"{world}:{etype}:{eid}"
    tags = _tags_all()
    if request.method == "POST":
        body = request.get_json(force=True)
        cur = set(tags.get(key, []))
        act = body.get("action", "add")
        t = (body.get("tag") or "").strip().lower()
        if act == "add" and t:
            cur.add(t)
        elif act == "remove":
            cur.discard(t)
        if cur:
            tags[key] = sorted(cur)
        else:
            tags.pop(key, None)
        _write_json(TAGS_FILE, tags)
    return jsonify({"tags": tags.get(key, [])})


@app.route("/api/tags")
def tags_index():
    """All tags -> list of entities carrying them (for the Tags browse page)."""
    tags = _tags_all()
    index = defaultdict(list)
    for key, tlist in tags.items():
        world, etype, eid = key.split(":", 2)
        for t in tlist:
            index[t].append({"world": world, "type": etype, "eid": int(eid)})
    # hydrate titles
    for t, items in index.items():
        for it in items:
            try:
                w = get_world(it["world"])
                rec = w.get(TYPE_FILES.get(it["type"], ""), {}).get(str(it["eid"]))
                it["title"] = (rec.get("name") or rec.get("title")) if rec else f"#{it['eid']}"
            except Exception:
                it["title"] = f"#{it['eid']}"
    # flag entries whose world is gone, so the page can offer to clear them
    live = set(_meta_cache.keys()) or set(dfparser.discover_worlds() or [])
    live = {os.path.basename(x) for x in live}
    for t, items in index.items():
        for it in items:
            it["orphan"] = it["world"] not in live
            it["key"] = f"{it['world']}:{it['type']}:{it['eid']}"
    return jsonify({"tags": {t: items for t, items in sorted(index.items())}})


@app.route("/api/book/<world>/<etype>/<int:eid>", methods=["GET", "POST"])
def api_book(world, etype, eid):
    """The actual contents of a written work, in pages.

    DF records that a book exists and roughly what it's about; it never
    records a word of the text. This is where you put the text you've
    written for it. Stored in userdata/, so re-importing a world can't
    touch it.
    """
    key = f"{world}:{etype}:{eid}"
    all_b = _read_json(BOOKS_FILE, {})
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        act = body.get("action", "save")
        book = all_b.get(key) or {"title": "", "pages": []}
        if act == "save":
            if "title" in body:
                book["title"] = (body.get("title") or "").strip()
            if "pages" in body:
                book["pages"] = [str(p) for p in (body.get("pages") or [])]
        elif act == "add_page":
            book.setdefault("pages", []).append(body.get("text") or "")
        elif act == "set_page":
            i = int(body.get("index", -1))
            if 0 <= i < len(book.get("pages", [])):
                book["pages"][i] = body.get("text") or ""
        elif act == "remove_page":
            i = int(body.get("index", -1))
            if 0 <= i < len(book.get("pages", [])):
                book["pages"].pop(i)
        elif act == "delete":
            all_b.pop(key, None)
            _write_json(BOOKS_FILE, all_b)
            return jsonify({"title": "", "pages": []})
        book["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        all_b[key] = book
        _write_json(BOOKS_FILE, all_b)
        return jsonify(book)
    return jsonify(all_b.get(key) or {"title": "", "pages": []})


@app.route("/api/prune_orphans", methods=["POST"])
def api_prune_orphans():
    """Delete user data pointing at worlds that no longer exist.

    Removing a world's folder leaves its bookmarks and tags behind, pointing
    at pages that can't load. They were unreachable to delete through the UI
    precisely because opening them failed, so there was no way out.
    """
    refresh_meta()
    live = {os.path.basename(x) for x in (_meta_cache.keys() or [])}
    removed = {"bookmarks": 0, "tags": 0, "gallery": 0, "vitals": 0}

    bm = _read_json(BOOKMARKS_FILE, {})
    items = bm.get("items", [])
    kept = [b for b in items if b.get("world") in live]
    removed["bookmarks"] = len(items) - len(kept)
    if removed["bookmarks"]:
        bm["items"] = kept
        _write_json(BOOKMARKS_FILE, bm)

    for path, name in ((TAGS_FILE, "tags"), (GALLERY_FILE, "gallery"),
                       (VITALS_FILE, "vitals")):
        data = _read_json(path, {})
        keep = {k: v for k, v in data.items() if k.split(":", 1)[0] in live}
        removed[name] = len(data) - len(keep)
        if removed[name]:
            _write_json(path, keep)

    return jsonify({"removed": removed, "live_worlds": sorted(live)})


# ---- gallery (per-entity images, hidden until populated) -------------------
def _gallery_all():
    return _read_json(GALLERY_FILE, {})


def _gallery_get(key):
    return _gallery_all().get(key, [])


@app.route("/api/gallery/<world>/<etype>/<int:eid>", methods=["GET"])
def gallery_get(world, etype, eid):
    key = f"{world}:{etype}:{eid}"
    return jsonify({"images": _gallery_get(key)})


@app.route("/api/gallery/<world>/<etype>/<int:eid>", methods=["POST"])
def gallery_post(world, etype, eid):
    """
    body: {action:'add', filename, caption?}   -> attach an already-uploaded
                                                    image (POST /api/upload first)
          {action:'remove', id}                -> detach + note file stays on
                                                    disk (flat folder, no cleanup
                                                    bookkeeping. Matches the
                                                    "nothing fancy" request)
          {action:'caption', id, caption}       -> edit a caption
    """
    key = f"{world}:{etype}:{eid}"
    body = request.get_json(force=True)
    gal = _gallery_all()
    items = gal.setdefault(key, [])
    action = body.get("action", "add")

    if action == "add":
        items.append({
            "id": uuid.uuid4().hex[:12],
            "filename": body.get("filename"),
            "caption": (body.get("caption") or "").strip(),
            "uploaded": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    elif action == "remove":
        gal[key] = [im for im in items if im["id"] != body.get("id")]
        if not gal[key]:
            gal.pop(key, None)
    elif action == "star":
        # exactly one starred image per entity. It's the thumbnail the
        # browse-grid card uses, so a second star would be ambiguous
        want = body.get("id")
        for im in items:
            im["starred"] = (im["id"] == want) and not im.get("starred")
    elif action == "caption":
        for im in items:
            if im["id"] == body.get("id"):
                im["caption"] = (body.get("caption") or "").strip()

    _write_json(GALLERY_FILE, gal)
    return jsonify({"images": gal.get(key, [])})


# ---- flavor overrides (surgical edit / reroll / regen on generated text) --
def _flavor_overrides_all():
    return _read_json(FLAVOR_OVERRIDES_FILE, {})


def _normalize_override_entry(entry):
    """Older versions stored a bare string per category. Newer versions
    store {"text","source","model","generated_at"}. Normalize on read so
    both shapes work. Old overrides never break, no migration script
    needed, no data loss."""
    if isinstance(entry, str):
        return {"text": entry, "source": "edited", "model": None, "generated_at": None}
    return entry


def _flavor_overrides_get(key):
    raw = _flavor_overrides_all().get(key, {})
    return {k: _normalize_override_entry(v) for k, v in raw.items()}


def _deleted_categories_all():
    return _read_json(DELETED_CATEGORIES_FILE, {})


def _deleted_categories_get(okey):
    return set(_deleted_categories_all().get(okey, []))


def _build_extra_flavor(world, etype, eid):
    """Generic extra_flavor list for any of the non-hf/creature types.
    Each category either has real generated content (from an override) or
    is null (not yet generated, frontend shows a Generate button). Deleted
    categories are dropped entirely, not just hidden."""
    cats = EXTRA_CATEGORIES.get(etype, [])
    if not cats:
        return []
    okey = f"{world}:{etype}:{eid}"
    ov = _flavor_overrides_get(okey)
    deleted = _deleted_categories_get(okey)
    out = []
    for key, label in cats:
        if key in deleted:
            continue
        entry = ov.get(key)
        if entry:
            out.append({"key": key, "label": label, "text": entry["text"],
                       "source": entry.get("source", "llm"), "model": entry.get("model")})
        else:
            out.append({"key": key, "label": label, "text": None, "source": None, "model": None})
    return out


# ---------------------------------------------------------------------------
# Context builders for LLM regen. Deliberately exclude raw event lists
# (high volume, low value-per-token, would trip up an 8B model) while
# keeping everything else: bio facts, resolved relationships, and the
# CURRENT text of every other section (through any existing overrides) so
# the model can stay consistent with what the rest of the page already says.
# ---------------------------------------------------------------------------
# A page can carry twenty sections of two paragraphs each. Feeding all of it
# back in as context was the main reason generation crawled: the prompt grew
# past the model's context window, forcing a slow prefill on every call for
# material the model barely needs. A handful of sections, trimmed, gives it
# enough to stay consistent without the cost.
_CONTEXT_SECTIONS = 6
_CONTEXT_CHARS = 260


def _other_sections_text(rec, world, etype, eid, exclude_key):
    ov = _flavor_overrides_get(f"{world}:{etype}:{eid}")
    lines = []
    for c in rec.get("flavor", []):
        if c["key"] == exclude_key:
            continue
        entry = ov.get(c["key"])
        text = (entry["text"] if entry else c["text"]) or ""
        text = " ".join(text.split())
        if len(text) > _CONTEXT_CHARS:
            text = text[:_CONTEXT_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append(f"- {c['label']}: {text}")
        if len(lines) >= _CONTEXT_SECTIONS:
            break
    return "\n".join(lines)


def _build_character_sheet_hf(rec, w, world, eid, exclude_key):
    bits = []
    name = rec.get("name") or "unknown"
    epithet = rec.get("epithet")
    race = rec.get("race") or "unknown race"
    sex = rec.get("sex") or ""
    by, dy = rec.get("birth_year"), rec.get("death_year")
    lifespan = (f"born year {by}" if isinstance(by, int) else "birth year unrecorded")
    lifespan += (f", died year {dy}" if dy not in (None, -1) else ", still living")
    header = f"{name}" + (f' ("{epithet}")' if epithet else "") + f", a {race} {sex}. {lifespan}."
    bits.append(header)

    if rec.get("spheres"):
        bits.append("Associated spheres: " + ", ".join(rec["spheres"][:5]) + ".")

    skills = sorted(rec.get("skills") or [], key=lambda s: -s.get("ip", 0))[:5]
    if skills:
        bits.append("Notable skills: " + ", ".join(s["skill"] for s in skills) + ".")

    rels = rec.get("relationships") or []
    if rels:
        rel_lines = []
        for r in rels[:8]:
            other = w["figures"].get(str(r.get("hf")))
            if other and other.get("name"):
                rel_lines.append(f"{r.get('rel','associate').replace('_',' ')} of {other['name']}")
        if rel_lines:
            bits.append("Relationships: " + "; ".join(rel_lines) + ".")

    other = _other_sections_text(rec, world, "hf", eid, exclude_key)
    if other:
        bits.append("Other established facts about them (from the rest of their page):\n" + other)
    return "\n".join(bits)


def _build_background_hf(rec, w):
    bits = []
    site_links = rec.get("site_links") or []
    if site_links:
        site = w["sites"].get(str(site_links[0].get("site_id")))
        if site and site.get("name"):
            bits.append(f"Associated with {site['name']}, a {site.get('type','settlement')}.")
    ent_links = rec.get("entity_links") or []
    if ent_links:
        ent = w["entities"].get(str(ent_links[0].get("entity_id")))
        if ent and ent.get("name"):
            bits.append(f"Affiliated with {ent['name']}, a {ent.get('race','')} {ent.get('type','group')}.".replace("  ", " "))
    return " ".join(bits)


def _build_character_sheet_creature(rec, world, eid, exclude_key):
    bits = [f"{rec.get('race','unknown').title()}, "
            f"{'a wild/monstrous creature' if rec.get('is_monster') else 'wildlife'}, "
            f"{rec.get('population_named',0)} named individuals recorded, "
            f"{rec.get('total_events',0)} recorded events total."]
    specimens = rec.get("notable_specimens") or []
    if specimens:
        names = [s["name"] for s in specimens[:5] if s.get("name")]
        if names:
            bits.append("Named specimens on record: " + ", ".join(names) + ".")
    other = _other_sections_text(rec, world, "creature", eid, exclude_key)
    if other:
        bits.append("Other established facts (from the rest of this page):\n" + other)
    return "\n".join(bits)


def _build_background_creature(rec):
    biomes = rec.get("top_biomes") or []
    if biomes:
        return "Most often sighted in " + ", ".join(b.lower() for b in biomes) + " terrain."
    return ""


# ---------------------------------------------------------------------------
# Universal generated categories. Every entity type gets its own set of
# LLM-only headers (no wordbank baseline, same as Commerce), each starting
# empty with a Generate button. Categories are just names here; there's no
# content-authoring cost to defining them, since nothing gets written until
# someone actually clicks Generate on a specific page.
# ---------------------------------------------------------------------------
EXTRA_CATEGORIES = {
    "site": [
        ("history", "History & Founding"), ("structures_desc", "Notable Structures"),
        ("defenses", "Defenses & Fortifications"), ("customs", "Local Customs"),
        ("legends", "Legends & Rumors"), ("daily_life", "Daily Life"),
        ("architecture", "Architecture & Style"), ("strategic", "Strategic Importance"),
        ("commerce", "Trade & Commerce"), ("culture", "Cultural Significance"),
    ],
    "ent": [
        ("founding", "Founding & Origins"), ("government", "Government & Leadership"),
        ("military", "Military Doctrine"), ("culture", "Culture & Customs"),
        ("religion", "Religion & Belief"), ("conflicts", "Notable Conflicts"),
        ("diplomacy", "Diplomacy & Alliances"), ("economy", "Economy & Trade"),
        ("daily_life", "Daily Life"), ("legacy", "Legacy & Influence"),
        ("territory", "Territory & Expansion"),
    ],
    "artifact": [
        ("provenance", "Provenance & Creation"), ("craftsmanship", "Craftsmanship & Design"),
        ("legendary_status", "Legendary Status"), ("owners", "Notable Owners"),
        ("whereabouts", "Current Whereabouts"), ("significance", "Cultural Significance"),
        ("rumors", "Rumors & Legends"),
    ],
    "wc": [
        ("contents", "Contents & Themes"), ("style", "Style & Structure"),
        ("reception", "Reception & Influence"), ("intent", "Author's Intent"),
        ("passages", "Notable Passages"), ("context", "Historical Context"),
    ],
    "region": [
        ("geography", "Geography & Terrain"), ("climate", "Climate & Weather"),
        ("wildlife", "Wildlife & Flora"), ("legends", "Local Legends"),
        ("strategic", "Strategic Importance"), ("notable_events", "Notable Events"),
    ],
}


def _facts_site(rec, w, eid):
    bits = [f"Type: {rec.get('type','settlement')}. Recorded events: {rec.get('n_events',0)}. "
            f"Structures: {len(rec.get('structures') or [])}."]
    owners = [w["entities"].get(str(i), {}).get("name") for i in
             (e_id for e_id, e in w["entities"].items() if eid in (e.get("owned_site_ids") or []))]
    owners = [o for o in owners if o]
    if owners:
        bits.append("Held by: " + ", ".join(owners[:5]) + ".")
    bits.append(_build_site_commerce_facts(eid, w))
    return "\n".join(bits)


def _facts_ent(rec, w):
    bits = [f"Type: {rec.get('type','group')}. Race: {rec.get('race','unknown')}. "
            f"Members: {rec.get('n_members',0)}. Recorded events: {rec.get('n_events',0)}."]
    positions = rec.get("positions") or []
    if positions:
        bits.append("Positions of authority: " + ", ".join(p["name"] for p in positions[:8]) + ".")
    owned = rec.get("owned_site_ids") or []
    if owned:
        names = [w["sites"].get(str(s), {}).get("name") for s in owned[:8]]
        names = [n for n in names if n]
        if names:
            bits.append("Sites held: " + ", ".join(names) + ".")
    children = rec.get("children") or []
    if children:
        names = [w["entities"].get(str(c), {}).get("name") for c in children[:8]]
        names = [n for n in names if n]
        if names:
            bits.append("Subsidiary/child groups: " + ", ".join(names) + ".")
    return "\n".join(bits)


def _facts_artifact(rec, w):
    bits = [f"Type: {rec.get('item_type','item')} ({rec.get('item_subtype','')}). "
            f"Material: {rec.get('material','unknown')}."]
    if rec.get("holder_hfid") is not None:
        holder = w["figures"].get(str(rec["holder_hfid"]))
        if holder and holder.get("name"):
            bits.append(f"Current holder: {holder['name']}.")
    if rec.get("site_id") is not None:
        site = w["sites"].get(str(rec["site_id"]))
        if site and site.get("name"):
            bits.append(f"Located at: {site['name']} ({site.get('type','site')}).")
    return "\n".join(bits)


def _facts_wc(rec, w):
    bits = [f"Form: {rec.get('form','written work')}."]
    if rec.get("author_hfid") is not None:
        author = w["figures"].get(str(rec["author_hfid"]))
        if author and author.get("name"):
            bits.append(f"Author: {author['name']}.")
    if rec.get("styles"):
        bits.append("Styles: " + ", ".join(rec["styles"]) + ".")
    return "\n".join(bits)


def _facts_region(rec):
    return f"Type: {rec.get('type','region')}."


_FACTS_BUILDERS = {
    "site": lambda rec, w, eid: _facts_site(rec, w, eid),
    "ent": lambda rec, w, eid: _facts_ent(rec, w),
    "artifact": lambda rec, w, eid: _facts_artifact(rec, w),
    "wc": lambda rec, w, eid: _facts_wc(rec, w),
    "region": lambda rec, w, eid: _facts_region(rec),
}

GENERIC_SYSTEM_PROMPT = """You are a scholarly encyclopedia writer, for a \
private fantasy wiki generated from a Dwarf Fortress world.

You will be given the CATEGORY (the section topic), the NAME of the real \
entity, and real FACTS about it. Rules:
- Write two paragraphs on this specific topic, grounded in the real facts given.

NAMING, this matters more than any other stylistic rule:
- The reader already knows what this article is about; the name is printed \
at the top of the page. Use the full name AT MOST ONCE in the passage, and \
often zero times is correct.
- After that use pronouns, or a short descriptor ("the fortress", "the \
order", "it", "they"). Vary it.
- Never open consecutive sentences with the name. Never restate it where a \
pronoun would be unambiguous. Repeating the subject's name every sentence \
is the clearest tell of machine-written text.
- Vary sentence length and opening construction for the same reason.

- If the facts are sparse, it's honest to write something modest and \
understated. Don't invent a rich history out of nothing.
- Do not invent new hard facts: no new named people, places, dates, or \
events beyond what you were given. General character, atmosphere, and \
plausible detail in service of the real facts are fine; new named \
specifics are not.
- Match the register of a serious historical encyclopedia. Confident, \
grounded, no throat-clearing.
- Never include disclaimers or phrases like "this is fictional", "as an \
AI", or "note that this is generated".
- No markdown formatting, no headers, no bullet points. Plain prose only."""


def generate_extra_category(etype, category_label, entity_name, facts):
    prov = ai_provider.PROVIDER
    if not prov.available():
        host = getattr(prov, "host", "localhost:11434")
        raise RuntimeError(
            f"Ollama isn't answering at {host}. Start it and try again, "
            "this is an HTTP connection to localhost, so where DwarfWiki "
            "lives on disk has no bearing on it.")
    user_prompt = (f"CATEGORY: {category_label}\nNAME: {entity_name}\n\nFACTS:\n{facts}\n\n"
                   f"Write the two-paragraph passage now.")
    import prompts as _p
    system, _seeds = _p.build_system("encyclopedia")
    text = ai_provider.PROVIDER.generate(system, user_prompt)
    return ai_provider.GenerationResult(text, source="llm", model=getattr(ai_provider.PROVIDER, "model", None))


def _build_site_commerce_facts(site_id, w):
    rec = w["sites"].get(str(site_id), {})
    bits = [f"Type: {rec.get('type','settlement')}. Recorded events: {rec.get('n_events',0)} "
            f"(a rough activity/prominence signal)."]
    merchants = []
    for i, e in w["entities"].items():
        if site_id in (e.get("owned_site_ids") or []) and (e.get("type") or "").lower() == "merchantcompany":
            if e.get("name"):
                merchants.append(e["name"])
    if merchants:
        bits.append("Merchant companies based here: " + ", ".join(merchants) + ".")
    else:
        bits.append("No merchant companies are recorded as based here.")
    goods = []
    for i, a in w["artifacts"].items():
        if a.get("site_id") == site_id and a.get("name"):
            desc = a["name"]
            if a.get("material"):
                desc += f" ({a['material']})"
            goods.append(desc)
    if goods:
        bits.append("Real named goods/artifacts recorded at this site: " + "; ".join(goods[:15]) + ".")
    else:
        bits.append("No named artifacts are recorded as located here.")
    return "\n".join(bits)


@app.route("/api/flavor_override/<world>/<etype>/<int:eid>", methods=["POST"])
def flavor_override_post(world, etype, eid):
    """
    body: {action:'edit', key, text}   -> save a manual rewrite, permanent
          {action:'randomize', key}    -> reroll fresh words, save as new override
          {action:'regen', key}        -> ask the configured AI provider to
                                           rewrite it (fails gracefully with a
                                           clear error until one is configured)
          {action:'reset', key}        -> drop the override, revert to generated
    Overrides live in userdata/, so re-importing a world never touches them.
    Same separation of concerns as notes/bookmarks/tags. Every saved entry
    carries {text, source, model, generated_at} so the UI can show a small
    [wordbank text] / [edited] / [llm text] tag per section.
    """
    body = request.get_json(force=True)
    action = body.get("action")
    ckey = body.get("key")
    if not ckey:
        abort(400, "missing key")
    okey = f"{world}:{etype}:{eid}"
    ov_all = _flavor_overrides_all()
    entry_map = ov_all.setdefault(okey, {})

    if action == "edit":
        text = (body.get("text") or "").strip()
        saved = ai_provider.GenerationResult(text, source="edited").to_dict()
        entry_map[ckey] = saved

    elif action == "randomize":
        w = get_world(world)
        if etype == "creature":
            rec = w["bestiary"].get(str(eid), {})
            text = dfparser.FLB.regenerate_text(
                ckey, population_named=rec.get("population_named"),
                top_biomes=rec.get("top_biomes"))
        elif etype == "hf":
            fig = w["figures"].get(str(eid), {})
            is_alive = fig.get("death_year") in (None, -1)
            age = None
            by, dy = fig.get("birth_year"), fig.get("death_year")
            if isinstance(by, int):
                end = dy if dy not in (None, -1) else (w["meta"] or {}).get("year_max")
                if isinstance(end, int):
                    age = max(0, end - by)
            text = dfparser.FL.regenerate_text(ckey, is_alive=is_alive, age=age)
        else:
            # sites, civilizations, artifacts, written works, regions, this
            # branch didn't exist at all before, which is why Reroll wording
            # silently did nothing on every one of those page types: every
            # non-creature reroll fell into the hf branch above regardless of
            # etype, looked up a historical figure that didn't exist for a
            # site/artifact/etc, and came back empty.
            text = flavor_entity.regenerate_text(etype, ckey)
        if text is None:
            abort(400, "unknown category")
        saved = ai_provider.GenerationResult(text, source="edited").to_dict()
        entry_map[ckey] = saved

    elif action == "regen":
        w = get_world(world)
        if etype == "site" and ckey == "commerce":
            site_name = w["sites"].get(str(eid), {}).get("name", "this site")
            facts = _build_site_commerce_facts(eid, w)
            try:
                result = ai_provider.generate_commerce(site_name, facts)
            except Exception as ex:
                return jsonify({"error": str(ex)}), 503
            saved = result.to_dict()
            entry_map[ckey] = saved
        elif etype in EXTRA_CATEGORIES:
            cats = dict(EXTRA_CATEGORIES[etype])
            if ckey not in cats:
                abort(400, "unknown category")
            fname = TYPE_FILES.get(etype)
            rec = w[fname].get(str(eid), {})
            entity_name = rec.get("name") or rec.get("title") or f"#{eid}"
            facts = _FACTS_BUILDERS[etype](rec, w, eid)
            try:
                result = generate_extra_category(etype, cats[ckey], entity_name, facts)
            except Exception as ex:
                return jsonify({"error": str(ex)}), 503
            saved = result.to_dict()
            entry_map[ckey] = saved
        else:
            fname = "bestiary" if etype == "creature" else "figures"
            rec = w[fname].get(str(eid), {})
            current = next((c["text"] for c in rec.get("flavor", []) if c["key"] == ckey), "")
            label = next((c["label"] for c in rec.get("flavor", []) if c["key"] == ckey), ckey)
            if etype == "creature":
                character_sheet = _build_character_sheet_creature(rec, world, eid, ckey)
                background = _build_background_creature(rec)
            else:
                character_sheet = _build_character_sheet_hf(rec, w, world, eid, ckey)
                background = _build_background_hf(rec, w)
            try:
                result = ai_provider.generate_category(label, current, character_sheet, background)
            except Exception as ex:
                return jsonify({"error": str(ex)}), 503
            saved = result.to_dict()
            entry_map[ckey] = saved

    elif action == "reset":
        entry_map.pop(ckey, None)
        if not entry_map:
            ov_all.pop(okey, None)
        if (etype == "site" and ckey == "commerce") or etype in EXTRA_CATEGORIES:
            saved = {"text": None, "source": None, "model": None, "generated_at": None}
        else:
            w = get_world(world)
            fname = "bestiary" if etype == "creature" else "figures"
            rec = w[fname].get(str(eid), {})
            text = next((c["text"] for c in rec.get("flavor", []) if c["key"] == ckey), None)
            saved = {"text": text, "source": "wordbank", "model": None, "generated_at": None}

    elif action == "delete":
        # permanent. Removes the header from the page entirely, not just
        # clearing its text. Only meaningful for the generated-header types;
        # hf/creature categories are structural (part of the page layout)
        # so deletion isn't offered there.
        entry_map.pop(ckey, None)
        if not entry_map:
            ov_all.pop(okey, None)
        deleted_all = _deleted_categories_all()
        deleted_list = deleted_all.setdefault(okey, [])
        if ckey not in deleted_list:
            deleted_list.append(ckey)
        _write_json(DELETED_CATEGORIES_FILE, deleted_all)
        saved = {"deleted": True}

    else:
        abort(400, "unknown action")

    _write_json(FLAVOR_OVERRIDES_FILE, ov_all)
    return jsonify(saved)


# ---- image upload ---------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        abort(400, "no file")
    f = request.files["file"]
    ext = os.path.splitext(f.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        abort(400, "unsupported image type")
    fname = uuid.uuid4().hex + ext
    f.save(os.path.join(IMAGES_DIR, fname))
    return jsonify({"filename": fname, "url": f"/userdata/images/{fname}"})


# ---- export ---------------------------------------------------------------
@app.route("/api/export")
def export_zip():
    """Zip up userdata (notes, bookmarks, tags, images) for backup."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(USERDATA_DIR):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, USERDATA_DIR)
                z.write(full, os.path.join("userdata", rel))
    buf.seek(0)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"dwarfwiki-backup-{stamp}.zip")


# ---- re-import (background) ----------------------------------------------
_reimport_status = {}


@app.route("/api/import_world", methods=["POST"])
def import_world():
    """Web-based world import: upload a legends.xml + legends_plus.xml pair
    straight from the browser instead of hand-copying files into worlds/.
    Runs the same WorldImporter auto_import() uses on startup, just
    triggered on demand and reported over the same status-poll pattern
    /api/reimport_status already uses."""
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400, "world name is required")
    base_file = request.files.get("base")
    plus_file = request.files.get("plus")
    if not base_file or not base_file.filename or not plus_file or not plus_file.filename:
        abort(400, "both legends.xml and legends_plus.xml are required")

    # slugify the display name into a safe folder name, de-duplicating
    # against anything already on disk rather than silently overwriting it
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "world"
    candidate, n = slug, 2
    while os.path.isdir(os.path.join(WORLDS_DIR, candidate)):
        candidate = f"{slug}-{n}"; n += 1
    slug = candidate

    raw_dir = os.path.join(WORLDS_DIR, slug, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    # save with guaranteed-matching names rather than trusting the browser's
    # upload filename to happen to pair correctly under discover_xml_pairs'
    # stem-matching. We already know definitively which file is which from
    # the form field itself, no need to rely on filename conventions holding
    base_file.save(os.path.join(raw_dir, "legends.xml"))
    plus_file.save(os.path.join(raw_dir, "legends_plus.xml"))

    wd = os.path.join(WORLDS_DIR, slug)

    def _job():
        _reimport_status[slug] = "running"
        try:
            ok = dfparser.WorldImporter(wd).run()
            if not ok:
                _reimport_status[slug] = "error: import failed - check the server console for details"
                return
            refresh_meta()
            _reimport_status[slug] = "done"
        except Exception as ex:
            _reimport_status[slug] = f"error: {ex}"

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"status": "started", "slug": slug})


@app.route("/api/reimport/<world>", methods=["POST"])
def reimport(world):
    wd = os.path.join(WORLDS_DIR, world)
    if not os.path.isdir(os.path.join(wd, "raw")):
        abort(404)

    def _job():
        _reimport_status[world] = "running"
        try:
            dfparser.WorldImporter(wd).run()
            evict(world)
            refresh_meta()
            _reimport_status[world] = "done"
        except Exception as ex:
            _reimport_status[world] = f"error: {ex}"

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/reimport_status/<world>")
def reimport_status(world):
    return jsonify({"status": _reimport_status.get(world, "idle")})


# ===========================================================================
# Startup
# ===========================================================================
def auto_import():
    pending = [wd for wd in dfparser.discover_worlds()
               if not dfparser.is_parsed(wd)]
    if pending:
        print(f"\nFound {len(pending)} un-imported world(s). Importing now "
              f"(one-time, ~30s each)…")
        for wd in pending:
            try:
                dfparser.WorldImporter(wd).run()
            except Exception as ex:
                print(f"   !! failed to import {os.path.basename(wd)}: {ex}")
    refresh_meta()


DEFAULT_PORT = 5000
PORT_CANDIDATES = [5000, 5050, 5173, 8000, 8080, 8765, 5001, 3000]


def pick_port():
    """Find a port we can actually bind.

    Windows reserves whole blocks of ports for Hyper-V, WSL and Docker, and
    binding inside one fails with "An attempt was made to access a socket in
    a way forbidden by its access permissions", which reads like a
    permissions problem but isn't. Rather than make the user diagnose that,
    try a short list and fall back to whatever the OS hands us.

    An explicit DWARFWIKI_PORT always wins, so you can pin it if you like.
    """
    import socket

    forced = os.environ.get("DWARFWIKI_PORT")
    if forced:
        try:
            return int(forced)
        except ValueError:
            pass

    for p in PORT_CANDIDATES:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue

    # nothing on the list worked. Let the OS choose a free one
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    print("=" * 60)
    print("  DwarfWiki,  local legends viewer")
    print("=" * 60)
    auto_import()
    names = list(_meta_cache.keys())
    if names:
        print(f"\nWorlds ready: {', '.join(names)}")
    else:
        print("\nNo worlds yet. Drop a legends.xml + legends_plus.xml pair into")
        print(f"  {os.path.join(WORLDS_DIR, '<world-name>', 'raw')}")
        print("then refresh the page (or restart).")
    port = pick_port()
    # write it where the launcher can read it, so wait_and_open.bat opens the
    # right address even when we've had to move off 5000
    try:
        with open(os.path.join(BASE_DIR, ".port"), "w") as fh:
            fh.write(str(port))
    except Exception:
        pass

    if port != DEFAULT_PORT:
        print(f"\nPort {DEFAULT_PORT} was unavailable on this machine, so DwarfWiki")
        print(f"is running on {port} instead. (Windows reserves blocks of ports for")
        print("Hyper-V/WSL/Docker, which is the usual cause.)")
    print(f"\n→ Open  http://localhost:{port}  in your browser.")
    print("  (Press Ctrl+C here to stop the server.)\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
