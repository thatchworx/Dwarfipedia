"""
cartography_routes.py  --  the map API, as a Flask blueprint
=========================================================================

This is the former standalone DFCart server, folded into DwarfWiki so both
live in one process on one port. It's a blueprint rather than 500 more lines
in server.py so it stays obvious which routes came from where, and so its
private helpers can't collide with server.py's similarly-named ones.

The one real change from standalone DFCart: it reads DwarfWiki's parsed
output directly (worlds/<name>/parsed/) instead of a synced flat copy, so
sync_worlds.py is gone and the map can never lag behind the wiki's data.

Routes that DwarfWiki already served (meta, map.png, heightmap.png,
map.json, worlds, version) are NOT duplicated here. The map frontend uses
DwarfWiki's existing ones.
"""
import os
import io
import json
import math
import struct
import uuid
import zlib

from flask import Blueprint, jsonify, request, send_file, abort, Response

import cartography as C

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SERVER_DIR)
WORLDS_DIR = os.path.join(BASE_DIR, "worlds")
USERDATA_DIR = os.path.join(BASE_DIR, "userdata")

CAPITALS_FILE = os.path.join(USERDATA_DIR, "capital_overrides.json")
ROUTES_FILE = os.path.join(USERDATA_DIR, "trade_routes.json")
MARKERS_FILE = os.path.join(USERDATA_DIR, "custom_markers.json")
BANNERS_FILE = os.path.join(USERDATA_DIR, "banners.json")
CONTINENTS_FILE = os.path.join(USERDATA_DIR, "continents.json")

os.makedirs(USERDATA_DIR, exist_ok=True)

cart = Blueprint("cart", __name__)

_cache = {}


def get_world(name):
    if name not in _cache:
        wd = C.WorldData(name)
        if not wd.meta:
            abort(404, f"world '{name}' not found or not yet imported")
        _cache[name] = wd
    return _cache[name]


def evict_cart_cache(world=None):
    """Called by server.py after a (re)import so the map picks up new data
    without needing a restart."""
    if world is None:
        _cache.clear()
    else:
        _cache.pop(world, None)


@cart.route("/api/w/<world>/detailed_map.png")
def api_detailed_map_png(world):
    """DFCart's own richer renderer (organic domain-warped coastlines +
    procedural texture). Generated once and cached to disk, same pattern
    as every other map asset in this project. First request after a fresh
    sync takes a real moment (~20-30s on real-world data); every request
    after that is instant."""
    wd = get_world(world)
    path = os.path.join(WORLDS_DIR, world, "detailed_map.png")
    if not os.path.exists(path):
        ok = C.generate_detailed_map(wd, path)
        if not ok:
            abort(500, "could not generate detailed map")
    return send_file(path, mimetype="image/png")


@cart.route("/api/w/<world>/map_grid.json")
def api_map_grid_json(world):
    wd = get_world(world)
    return jsonify(wd.map_grid)


# ---------------------------------------------------------------------------
# sites. Lightweight list for markers
# ---------------------------------------------------------------------------
@cart.route("/api/w/<world>/sites")
def api_sites(world):
    wd = get_world(world)
    out = []
    for i, s in wd.sites.items():
        xy = wd.site_xy(s)
        if not xy or not s.get("name"):
            continue
        out.append({"id": int(i), "name": s["name"], "type": s.get("type"),
                    "x": xy[0], "y": xy[1], "events": s.get("n_events", 0),
                    "structures": len(s.get("structures", []))})
    return jsonify({"sites": out})


# ---------------------------------------------------------------------------
# territory / political map
# ---------------------------------------------------------------------------
@cart.route("/api/w/<world>/territory")
def api_territory(world):
    wd = get_world(world)
    preset = request.args.get("preset")
    if preset == "religion":
        types = C.RELIGION_TYPES
    elif preset == "faction":
        types = C.FACTION_TYPES
    elif request.args.get("all") == "1":
        types = C.ALL_TERRITORY_TYPES
    else:
        types = C.DEFAULT_TERRITORY_TYPES
    terr = C.compute_territory(wd, types=types)
    # tile counts per civ, so the sidebar can sort by real land area rather
    # than alphabetically. A civ holding 400 tiles matters more to someone
    # reading the map than one holding 3
    tile_counts = {}
    for row in terr["owner"]:
        for v in row:
            if v:
                tile_counts[v] = tile_counts.get(v, 0) + 1
    civs = []
    for cid, name in terr["civ_names"].items():
        ent = wd.entities.get(cid, {})
        civs.append({
            "id": cid, "name": name, "color": C.civ_color(cid),
            "race": (ent.get("race") or "unknown").lower(),
            "tiles": tile_counts.get(cid, 0),
        })
    # RLE-encode the owner grid row by row. Much smaller over the wire than
    # a raw 257x257 array of ids, trivial to decode client-side
    owner_rle = []
    for row in terr["owner"]:
        rle = []
        cur, cnt = row[0], 0
        for v in row:
            if v == cur:
                cnt += 1
            else:
                rle.append([cur, cnt])
                cur, cnt = v, 1
        rle.append([cur, cnt])
        owner_rle.append(rle)
    dist_rows = terr["dist"]  # small ints, fine as plain nested arrays
    return jsonify({"civs": civs, "owner_rle": owner_rle, "dist": dist_rows,
                    "max_influence": C.MAX_INFLUENCE})


@cart.route("/api/w/<world>/race_layer")
def api_race_layer(world):
    wd = get_world(world)
    broaden = request.args.get("all") == "1"
    types = C.ALL_TERRITORY_TYPES if broaden else C.DEFAULT_TERRITORY_TYPES
    r = C.compute_race_layer(wd, types=types)
    owner_rle = []
    for row in r["owner"]:
        rle = []
        cur, cnt = row[0], 0
        for v in row:
            if v == cur:
                cnt += 1
            else:
                rle.append([cur, cnt])
                cur, cnt = v, 1
        rle.append([cur, cnt])
        owner_rle.append(rle)
    return jsonify({"owner_rle": owner_rle, "dist": r["dist"], "race_by_civ": r["race_by_civ"],
                    "legend": r["legend"], "max_influence": r["max_influence"]})


@cart.route("/api/w/<world>/activity_points")
def api_activity_points(world):
    wd = get_world(world)
    return jsonify({"points": C.compute_activity_points(wd)})


@cart.route("/api/w/<world>/trade_hubs")
def api_trade_hubs(world):
    wd = get_world(world)
    return jsonify({"hubs": C.compute_trade_hubs(wd)})


@cart.route("/api/w/<world>/capitals")
def api_capitals(world):
    wd = get_world(world)
    broaden = request.args.get("all") == "1"
    types = C.ALL_TERRITORY_TYPES if broaden else C.DEFAULT_TERRITORY_TYPES
    caps = dict(C.compute_capitals(wd, types=types))
    overrides = _read_json(CAPITALS_FILE, {}).get(world, {})
    for cid, sid in overrides.items():
        caps[cid] = sid
    out = {}
    for cid, sid in caps.items():
        site = wd.sites.get(str(sid))
        if site:
            xy = wd.site_xy(site)
            out[cid] = {"site_id": sid, "name": site.get("name"),
                       "x": xy[0] if xy else None, "y": xy[1] if xy else None,
                       "overridden": cid in overrides}
    return jsonify({"capitals": out})


@cart.route("/api/w/<world>/capitals", methods=["POST"])
def api_capitals_set(world):
    body = request.get_json(force=True)
    cid, sid = str(body.get("civ_id")), body.get("site_id")
    all_ov = _read_json(CAPITALS_FILE, {})
    world_ov = all_ov.setdefault(world, {})
    if sid is None:
        world_ov.pop(cid, None)
    else:
        world_ov[cid] = sid
    _write_json(CAPITALS_FILE, all_ov)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# campaigns (real war -> battle paths) & factions
# ---------------------------------------------------------------------------
@cart.route("/api/w/<world>/campaigns")
def api_campaigns(world):
    wd = get_world(world)
    return jsonify({"campaigns": C.compute_campaigns(wd)})


@cart.route("/api/w/<world>/factions")
def api_factions(world):
    wd = get_world(world)
    return jsonify({"factions": C.compute_factions(wd)})


# ---------------------------------------------------------------------------
# speculative layers. Climate & drainage, clearly labeled generated (see
# cartography.py docstrings for exactly what's real vs invented here)
# ---------------------------------------------------------------------------
def _write_png(path_or_buf, width, height, get_rgba):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b, a = get_rgba(x, y)
            raw += bytes((r, g, b, a))
    compressed = zlib.compress(bytes(raw), 6)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # color type 6 = RGBA
    buf = path_or_buf if hasattr(path_or_buf, "write") else open(path_or_buf, "wb")
    buf.write(b"\x89PNG\r\n\x1a\n")
    buf.write(chunk(b"IHDR", ihdr))
    buf.write(chunk(b"IDAT", compressed))
    buf.write(chunk(b"IEND", b""))
    if not hasattr(path_or_buf, "write"):
        buf.close()


def _temp_color(f):
    # blue (cold) -> green -> yellow -> red (hot). Fully opaque. The
    # 'multiply' blend mode on the frontend is what lets terrain show
    # through, so stacking a second semi-transparent alpha on top of that
    # was cutting effective visibility roughly in half for no reason.
    f = max(0, min(100, f))
    if f < 33:
        t = f / 33
        return (int(20 + t * 40), int(70 + t * 110), 235, 255)
    elif f < 66:
        t = (f - 33) / 33
        return (int(60 + t * 175), 225, int(190 - t * 170), 255)
    else:
        t = (f - 66) / 34
        return (245, int(215 - t * 180), int(20), 255)


@cart.route("/api/w/<world>/overlay/climate.png")
def api_climate_png(world):
    wd = get_world(world)
    buf = io.BytesIO()

    def px(x, y):
        c = C.compute_climate_cell(wd, x, y)
        if c is None:
            return (0, 0, 0, 0)
        pct = max(0, min(100, (c["temp_f"] + 20) / 1.2))
        return _temp_color(pct)

    _write_png(buf, wd.width, wd.height, px)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@cart.route("/api/w/<world>/overlay/drainage.png")
def api_drainage_png(world):
    wd = get_world(world)
    buf = io.BytesIO()

    def px(x, y):
        d = C.compute_drainage_cell(wd, x, y)
        if d is None:
            return (0, 0, 0, 0)
        v = int(50 + d * 1.8)
        return (20, 70, min(255, v + 90), 255)

    _write_png(buf, wd.width, wd.height, px)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ---------------------------------------------------------------------------
# measurement (imperial, verified DF scale)
# ---------------------------------------------------------------------------
@cart.route("/api/measure/distance")
def api_measure_distance():
    x1, y1 = float(request.args["x1"]), float(request.args["y1"])
    x2, y2 = float(request.args["x2"]), float(request.args["y2"])
    tiles = C.tile_distance((x1, y1), (x2, y2))
    miles = tiles * C.MILES_PER_TILE
    return jsonify({"tiles": round(tiles, 1), "miles": round(miles, 1),
                    "miles_per_tile": C.MILES_PER_TILE})


@cart.route("/api/measure/area", methods=["POST"])
def api_measure_area():
    points = request.get_json(force=True).get("points", [])
    if len(points) < 3:
        abort(400, "need at least 3 points")
    tiles_sq = C.polygon_area_tiles([(p["x"], p["y"]) for p in points])
    sq_miles = tiles_sq * (C.MILES_PER_TILE ** 2)
    return jsonify({"tiles_sq": round(tiles_sq, 1), "sq_miles": round(sq_miles, 1),
                    "reference": C.closest_area_reference(sq_miles)})


# ---------------------------------------------------------------------------
# generic userdata read/write helpers
# ---------------------------------------------------------------------------
def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# trade routes (manual editor. DF has no real trade-agreement data, so
# these are explicitly user-authored, not claimed as historically real)
# ---------------------------------------------------------------------------
@cart.route("/api/w/<world>/routes", methods=["GET"])
def routes_get(world):
    all_routes = _read_json(ROUTES_FILE, {})
    return jsonify({"routes": all_routes.get(world, [])})


@cart.route("/api/w/<world>/routes", methods=["POST"])
def routes_post(world):
    body = request.get_json(force=True)
    action = body.get("action")
    all_routes = _read_json(ROUTES_FILE, {})
    lst = all_routes.setdefault(world, [])
    if action == "add":
        lst.append({"id": uuid.uuid4().hex[:10], "from_site": body["from_site"],
                    "to_site": body["to_site"], "label": body.get("label", "")})
    elif action == "remove":
        all_routes[world] = [r for r in lst if r["id"] != body.get("id")]
    _write_json(ROUTES_FILE, all_routes)
    return jsonify({"routes": all_routes.get(world, [])})


# ---------------------------------------------------------------------------
# custom markers
# ---------------------------------------------------------------------------
@cart.route("/api/w/<world>/markers", methods=["GET"])
def markers_get(world):
    all_m = _read_json(MARKERS_FILE, {})
    return jsonify({"markers": all_m.get(world, [])})


@cart.route("/api/w/<world>/markers", methods=["POST"])
def markers_post(world):
    body = request.get_json(force=True)
    action = body.get("action")
    all_m = _read_json(MARKERS_FILE, {})
    lst = all_m.setdefault(world, [])
    if action == "add":
        lst.append({"id": uuid.uuid4().hex[:10], "x": body["x"], "y": body["y"],
                    "label": body.get("label", ""), "icon": body.get("icon", "pin"),
                    "color": body.get("color", "#7a2e2e")})
    elif action == "remove":
        all_m[world] = [m for m in lst if m["id"] != body.get("id")]
    _write_json(MARKERS_FILE, all_m)
    return jsonify({"markers": all_m.get(world, [])})


# ---------------------------------------------------------------------------
# faction banners (homebrew designer. Color + charge icon, purely decorative)
# ---------------------------------------------------------------------------
@cart.route("/api/banners", methods=["GET"])
def banners_get():
    return jsonify({"banners": _read_json(BANNERS_FILE, {})})


@cart.route("/api/banners", methods=["POST"])
def banners_post():
    body = request.get_json(force=True)
    key = body.get("key")
    if not key:
        abort(400, "missing key")
    all_b = _read_json(BANNERS_FILE, {})
    if body.get("action") == "remove":
        all_b.pop(key, None)
    else:
        all_b[key] = {"primary": body.get("primary", "#7a2e2e"),
                      "secondary": body.get("secondary", "#e7dcc4"),
                      "charge": body.get("charge", "star")}
    _write_json(BANNERS_FILE, all_b)
    return jsonify({"banners": all_b})



# ---------------------------------------------------------------------------
# CONTINENTS. The map wall
#
# A "continent" is a saved arrangement: which regions sit where on a shared
# tile grid, which rectangles are procedural ocean, and every tile the user
# has hand-painted to smooth the seams between them.
#
# Coordinates are in DF overworld tiles (1 tile ~= 1873m), NOT in cells, so a
# Pocket region (17 tiles) can sit in a bay off a Large region (257 tiles) at
# its true relative size instead of being forced into an identical grid slot.
#
# Paint is stored sparsely ({"x,y": biome_index})because a wall is mostly
# untouched real data with edits only along the seams. Ocean rectangles store
# a seed rather than pixels, so a 257x257 sea costs ~40 bytes instead of
# 66,000 tile entries.
# ---------------------------------------------------------------------------

@cart.route("/api/continents", methods=["GET"])
def continents_list():
    all_c = _read_json(CONTINENTS_FILE, {})
    # summaries only. The paint dict on a big continent is large and the
    # picker doesn't need it
    out = []
    for cid, c in all_c.items():
        out.append({
            "id": cid,
            "name": c.get("name", "Untitled"),
            "regions": len(c.get("placements", [])),
            "oceans": len(c.get("oceans", [])),
            "painted": len(c.get("paint", {})),
            "labels": len(c.get("labels", [])),
            "updated": c.get("updated"),
        })
    out.sort(key=lambda x: x.get("updated") or "", reverse=True)
    return jsonify({"continents": out})


@cart.route("/api/continents/<cid>", methods=["GET"])
def continent_get(cid):
    all_c = _read_json(CONTINENTS_FILE, {})
    c = all_c.get(cid)
    if not c:
        abort(404, "no such continent")
    return jsonify(c)


@cart.route("/api/continents", methods=["POST"])
def continent_save():
    """Whole-document save. The wall is edited locally and committed on
    demand, so there's no partial-update protocol to get out of sync."""
    body = request.get_json(force=True) or {}
    all_c = _read_json(CONTINENTS_FILE, {})
    cid = body.get("id") or uuid.uuid4().hex[:10]
    doc = {
        "id": cid,
        "name": (body.get("name") or "Untitled").strip()[:80],
        "placements": body.get("placements") or [],
        "oceans": body.get("oceans") or [],
        "paint": body.get("paint") or {},
        "labels": body.get("labels") or [],
        "updated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    }
    all_c[cid] = doc
    _write_json(CONTINENTS_FILE, all_c)
    return jsonify(doc)


@cart.route("/api/continents/<cid>", methods=["DELETE"])
def continent_delete(cid):
    all_c = _read_json(CONTINENTS_FILE, {})
    all_c.pop(cid, None)
    _write_json(CONTINENTS_FILE, all_c)
    return jsonify({"ok": True})


@cart.route("/api/palette")
def palette():
    """The exact biome colours the map renderer uses, so a hand-painted tile
    is pixel-identical to a generated one. Sourced from the parser rather
    than duplicated, so a future palette tweak can't silently desync the
    painting tools from the maps."""
    import parser as dfparser
    order = ["Ocean", "Lake", "Wetland", "Grassland", "Forest", "Desert",
             "Tundra", "Hills", "Mountains", "Glacier"]
    out = []
    for name in order:
        rgb = dfparser.BIOME_COLORS.get(name)
        if not rgb:
            continue
        out.append({
            "name": name,
            "rgb": list(rgb),
            "hex": "#%02x%02x%02x" % rgb,
            # the renderer darkens a land tile that touches water, which is
            # what gives coastlines their subtle edge. Painting needs the
            # same variant to blend in
            "coast_hex": "#%02x%02x%02x" % tuple(max(0, int(ch * 0.82)) for ch in rgb),
            "water": name in ("Ocean", "Lake"),
        })
    return jsonify({"palette": out})
