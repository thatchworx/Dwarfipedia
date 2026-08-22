"""
cartography.py  --  the actual map-data engine behind DFCart
=================================================================

Everything here is either REAL data (derived from DwarfWiki's already-
validated parsed output. Site ownership, real battle locations, real
years) or CLEARLY-SCOPED speculation (weather/climate, drainage) that
gets labeled as generated rather than presented as fact. See the module
docstrings on compute_weather/compute_drainage for exactly what's real
vs invented, and why.
"""
import os
import json
import math
import hashlib
import struct
import zlib
from collections import deque, defaultdict

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SERVER_DIR)
WORLDS_DIR = os.path.join(BASE_DIR, "worlds")

# ---------------------------------------------------------------------------
# Verified DF scale (dwarffortresswiki.org/index.php/Tile): world size scales
# from 20 miles (17-tile world) to 300 miles (257-tile world) across, and a
# world tile is 16x16 "local area blocks" of 48x48 tiles each. Both reference
# points agree: 300/257 ≈ 1.167 mi/tile, 20/17 ≈ 1.176 mi/tile. We use the
# real figure, not a guessed one, this is the actual documented DF scale.
# ---------------------------------------------------------------------------
MILES_PER_TILE = 1.17

# reference areas for the "about the size of X" area-tool comparison,
# smallest to largest, all real-world imperial figures
AREA_REFERENCES = [
    ("a small city block", 0.02),
    ("Central Park (NYC)", 1.3),
    ("Manhattan Island", 22.7),
    ("Washington D.C.", 68),
    ("a large US county", 600),
    ("Rhode Island", 1212),
    ("Luxembourg", 998),
    ("Delaware", 2489),
    ("Connecticut", 5543),
    ("Wales", 8023),
    ("New Jersey", 8722),
    ("a small US state (e.g. New Hampshire)", 9349),
    ("Switzerland", 15940),
    ("the Netherlands", 16040),
    ("Ireland", 32595),
    ("Austria", 32383),
    ("a large US state (e.g. Pennsylvania)", 46054),
    ("England", 50301),
    ("a medium European country (e.g. Greece)", 50949),
    ("the United Kingdom", 93628),
    ("a large US state (e.g. California)", 163696),
    ("France", 248573),
    ("Texas", 268596),
    ("Alaska", 665384),
]


def closest_area_reference(sq_miles):
    best = min(AREA_REFERENCES, key=lambda r: abs(math.log(max(r[1], 0.001)) - math.log(max(sq_miles, 0.001))))
    return best[0]


# ---------------------------------------------------------------------------
# World data loading
# ---------------------------------------------------------------------------
def world_parsed_dir(world):
    """DwarfWiki writes its parsed output to worlds/<name>/parsed/. DFCart
    used to keep a flat copy of those same files in its own worlds/<name>/
    via a sync step. Now that the two apps are one, we read DwarfWiki's
    parsed output directly and the sync step disappears entirely."""
    return os.path.join(WORLDS_DIR, world, "parsed")


def _load(world, name, default=None):
    path = os.path.join(world_parsed_dir(world), name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def discover_worlds():
    if not os.path.isdir(WORLDS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(WORLDS_DIR)):
        if os.path.exists(os.path.join(WORLDS_DIR, name, "parsed", "meta.json")):
            out.append(name)
    return out


class WorldData:
    """Loads and caches one world's synced data + derived cartography."""
    def __init__(self, world):
        self.world = world
        self.meta = _load(world, "meta.json", {})
        self.sites = _load(world, "sites.json", {})
        self.entities = _load(world, "entities.json", {})
        self.map_meta = _load(world, "map.json", {})
        self.map_grid = _load(world, "map_grid.json", {})
        self.collections = _load(world, "collections.json", {})

    @property
    def width(self):
        return self.map_grid.get("width", 0)

    @property
    def height(self):
        return self.map_grid.get("height", 0)

    def biome_at(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        idx = self.map_grid["grid"][y][x]
        types = self.map_grid["types"]
        return types[idx] if idx >= 0 else None

    def site_xy(self, site):
        coords = site.get("coords")
        if not coords or "," not in coords:
            return None
        try:
            x, y = (int(v) for v in coords.split(",", 1))
            return x, y
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Civilization color palette. Deterministic per civ id, not random per load,
# since borders need to read consistently every time you open the map.
# ---------------------------------------------------------------------------
CIV_PALETTE = [
    "#d43838", "#3878c8", "#3c9c48", "#d4972a", "#8a3cc8",
    "#20a8a0", "#d4389c", "#a8a028", "#3850c8", "#d4602a",
    "#28b858", "#c82860", "#5828c8", "#c8a020", "#2888c0",
    "#a02838",
]


def civ_color(civ_id):
    h = int(hashlib.md5(str(civ_id).encode()).hexdigest()[:8], 16)
    return CIV_PALETTE[h % len(CIV_PALETTE)]


# ---------------------------------------------------------------------------
# Territory. Multi-source BFS from every civ's OWNED sites (real data:
# entities.json's owned_site_ids, itself derived from real event
# co-occurrence in DwarfWiki). Each land tile is claimed by whichever
# civ's nearest owned site reaches it first; distance is kept too, so the
# frontend can render either hard "Political Lines" (solid up to the
# boundary) or the default "Boundary Bleed" (alpha fades out with distance,
# reads as fading influence rather than a hard drawn line). Water tiles are
# never claimed. Settlements don't own the ocean.
# ---------------------------------------------------------------------------
MAX_INFLUENCE = 42       # tiles. Beyond this a land tile stays wilderness
WATER_TYPES = {"Ocean", "Lake"}
# "civilization" is the real kingdoms/major powers. sitegovernment fires for
# almost every single settlement individually (a settlement's own tiny local
# government "owns" just itself). Including those by default turns the
# political map into 1000+ overlapping single-site claims instead of a
# readable map of real powers. Off by default; the UI can turn it on.
DEFAULT_TERRITORY_TYPES = {"civilization"}
ALL_TERRITORY_TYPES = {"civilization", "sitegovernment", "religion",
                       "outcast", "guild", "nomadicgroup", "merchantcompany",
                       "militaryunit"}


def compute_territory(wd, max_influence=MAX_INFLUENCE, types=None):
    types = types or DEFAULT_TERRITORY_TYPES
    cache_key = tuple(sorted(types))
    if not hasattr(wd, "_territory_cache"):
        wd._territory_cache = {}
    if cache_key in wd._territory_cache:
        return wd._territory_cache[cache_key]
    W, H = wd.width, wd.height
    if not W or not H:
        result = {"owner": [], "dist": [], "civ_names": {}}
        wd._territory_cache[cache_key] = result
        return result

    owner = [[-1] * W for _ in range(H)]
    dist = [[-1] * W for _ in range(H)]
    q = deque()

    civ_names = {}
    for cid, ent in wd.entities.items():
        if (ent.get("type") or "").lower() not in types:
            continue
        owned = ent.get("owned_site_ids") or []
        if not owned or not ent.get("name"):
            continue
        civ_names[cid] = ent["name"]
        for sid in owned:
            site = wd.sites.get(str(sid))
            if not site:
                continue
            xy = wd.site_xy(site)
            if not xy:
                continue
            x, y = xy
            if not (0 <= x < W and 0 <= y < H):
                continue
            if owner[y][x] == -1:
                owner[y][x] = cid
                dist[y][x] = 0
                q.append((x, y))

    while q:
        x, y = q.popleft()
        d = dist[y][x]
        if d >= max_influence:
            continue
        cid = owner[y][x]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and owner[ny][nx] == -1:
                t = wd.map_grid["types"][wd.map_grid["grid"][ny][nx]] if wd.map_grid["grid"][ny][nx] >= 0 else None
                if t in WATER_TYPES:
                    continue
                owner[ny][nx] = cid
                dist[ny][nx] = d + 1
                q.append((nx, ny))

    result = {"owner": owner, "dist": dist, "civ_names": civ_names}
    wd._territory_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Capitals. Real heuristic (most eventful owned site), with manual override
# support handled by the server layer (overrides live in userdata, not here).
# ---------------------------------------------------------------------------
def compute_capitals(wd, types=None):
    types = types or DEFAULT_TERRITORY_TYPES
    cache_key = tuple(sorted(types))
    if not hasattr(wd, "_capitals_cache"):
        wd._capitals_cache = {}
    if cache_key in wd._capitals_cache:
        return wd._capitals_cache[cache_key]
    capitals = {}
    for cid, ent in wd.entities.items():
        if (ent.get("type") or "").lower() not in types:
            continue
        owned = ent.get("owned_site_ids") or []
        if not owned:
            continue
        best_id, best_score = None, -1
        for sid in owned:
            site = wd.sites.get(str(sid))
            if not site:
                continue
            score = site.get("n_events", 0)
            if score > best_score:
                best_score = score
                best_id = sid
        if best_id is not None:
            capitals[cid] = best_id
    wd._capitals_cache[cache_key] = capitals
    return capitals


# ---------------------------------------------------------------------------
# Campaigns. Real: for every named war, its child battles (linked via each
# battle's real war_id parent reference) in year order, connected as a path.
# Not invented troop movement. Just "these battles, in this order, with
# real years and real site locations."
# ---------------------------------------------------------------------------
def compute_campaigns(wd):
    wars = {}
    battles_by_war = defaultdict(list)
    for cid, c in wd.collections.items():
        cid_i = int(cid)
        if c.get("type") == "war":
            wars[cid_i] = c
        elif c.get("type") == "battle" and c.get("war_id") is not None:
            battles_by_war[c["war_id"]].append(dict(c, id=cid_i))

    campaigns = []
    for wid, w in wars.items():
        battles = battles_by_war.get(wid, [])
        battles.sort(key=lambda b: (b.get("y") is None, b.get("y") or 0))
        path = []
        for b in battles:
            if b.get("site_id") is None:
                continue
            site = wd.sites.get(str(b["site_id"]))
            if not site:
                continue
            xy = wd.site_xy(site)
            if xy:
                path.append({"x": xy[0], "y": xy[1], "battle_id": b["id"],
                            "name": b.get("name"), "year": b.get("y"),
                            "deaths": b.get("deaths")})
        campaigns.append({
            "id": wid, "name": w.get("name"), "year": w.get("y"),
            "end_year": w.get("end_year"), "n_battles": len(battles),
            "path": path,
        })
    campaigns.sort(key=lambda c: -c["n_battles"])
    return campaigns


# ---------------------------------------------------------------------------
# Factions & Guilds. Real: entities whose type marks them as smaller/
# non-territorial groups, grouped by their site ties.
# ---------------------------------------------------------------------------
FACTION_TYPES = {"guild", "merchantcompany", "outcast", "performancetroupe",
                 "nomadicgroup", "militaryunit"}
RELIGION_TYPES = {"religion"}


def compute_factions(wd):
    out = []
    for cid, ent in wd.entities.items():
        etype = (ent.get("type") or "").lower()
        if etype in FACTION_TYPES and ent.get("name"):
            out.append({
                "id": cid, "name": ent["name"], "type": ent.get("type"),
                "n_members": ent.get("n_members", 0),
                "owned_site_ids": ent.get("owned_site_ids", []),
            })
    out.sort(key=lambda f: -f["n_members"])
    return out


# ---------------------------------------------------------------------------
# Race density, NOT a new engine. Reuses the exact same territory BFS grid
# (real site ownership), just recolors each claimed tile by the OWNING
# ENTITY'S RACE (a real field on every entity) instead of by civ identity.
# Same reason this doesn't need per-figure tracking: race is a property of
# the controlling entity, not of individuals. Consistent with DFCart's
# original "sites and locations only" scope.
# ---------------------------------------------------------------------------
RACE_PALETTE = {
    "dwarf": "#d43838", "human": "#3878c8", "elf": "#3c9c48",
    "goblin": "#8a3cc8", "kobold": "#d4972a", "gnome": "#20a8a0",
}


def race_color(race):
    r = (race or "").lower()
    if r in RACE_PALETTE:
        return RACE_PALETTE[r]
    h = int(hashlib.md5(r.encode()).hexdigest()[:8], 16)
    return CIV_PALETTE[h % len(CIV_PALETTE)]


def compute_race_layer(wd, types=None):
    """Same owner/dist grids as compute_territory, relabeled by race. Cheap:
    just a lookup pass over the already-computed territory result."""
    terr = compute_territory(wd, types=types)
    race_by_civ = {}
    races_seen = {}
    for cid in terr["civ_names"]:
        ent = wd.entities.get(cid, {})
        race = (ent.get("race") or "unknown").lower()
        race_by_civ[cid] = race
        races_seen[race] = races_seen.get(race, 0) + 1
    legend = [{"race": r, "color": race_color(r)} for r in races_seen]
    return {"owner": terr["owner"], "dist": terr["dist"], "race_by_civ": race_by_civ,
           "legend": legend, "max_influence": terr.get("max_influence", MAX_INFLUENCE)}


# ---------------------------------------------------------------------------
# Activity / population-proxy heatmap. DF's legends export has no real
# per-site population figures, so this is explicitly an ACTIVITY heatmap:
# real recorded-event density around each site, radiating outward. It's a
# genuine signal (how much real history happened here), just not literally
# "population," and the UI labels it that way rather than overclaiming.
# ---------------------------------------------------------------------------
def compute_activity_points(wd):
    pts = []
    for i, s in wd.sites.items():
        xy = wd.site_xy(s)
        if not xy:
            continue
        w = s.get("n_events", 0)
        if w > 0:
            pts.append({"x": xy[0], "y": xy[1], "weight": w})
    return pts


# ---------------------------------------------------------------------------
# Trade / Commerce. Real merchant-company entities + their real site ties,
# used as the Commerce tab (added because the Wars tab reads empty on
# worlds with sparse recorded war history, this gives every world a
# populated tab regardless). Trade ROUTES between hubs are still your own
# manual annotation (drawn with the route tool) since DF has no real
# trade-agreement data to automate from.
# ---------------------------------------------------------------------------
def compute_trade_hubs(wd):
    hubs = []
    for cid, ent in wd.entities.items():
        if (ent.get("type") or "").lower() != "merchantcompany":
            continue
        for sid in ent.get("owned_site_ids", []):
            site = wd.sites.get(str(sid))
            if not site:
                continue
            xy = wd.site_xy(site)
            hubs.append({"site_id": sid, "site_name": site.get("name"),
                        "company": ent.get("name"), "x": xy[0] if xy else None,
                        "y": xy[1] if xy else None, "events": site.get("n_events", 0)})
    # also surface the busiest civilian settlement types as likely markets,
    # even without a merchant-company tie. Real site type + real activity
    market_types = {"town", "hamlet", "hillocks", "camp"}
    for i, s in wd.sites.items():
        if (s.get("type") or "") in market_types and s.get("n_events", 0) >= 3:
            xy = wd.site_xy(s)
            if xy:
                hubs.append({"site_id": int(i), "site_name": s.get("name"),
                            "company": None, "x": xy[0], "y": xy[1],
                            "events": s.get("n_events", 0)})
    hubs.sort(key=lambda h: -h["events"])
    # dedupe by site_id, keep richest entry
    seen = {}
    for h in hubs:
        if h["site_id"] not in seen or h["company"]:
            seen[h["site_id"]] = h
    return list(seen.values())[:60]


# ---------------------------------------------------------------------------
# Weather / Climate. CLEARLY SPECULATIVE. DF's legends export has no real
# rainfall/temperature/wind fields (the same gap that made Steam DF's own
# map export break), this is generated from real biome type + a north/south
# latitude proxy so it's at least internally consistent with the real map,
# not random noise, but it is not simulated data and the UI must label it
# as generated, not measured.
# ---------------------------------------------------------------------------
_TEMP_BASE = {
    "Glacier": 5, "Tundra": 25, "Mountains": 35, "Hills": 55, "Forest": 60,
    "Grassland": 65, "Wetland": 68, "Desert": 85, "Lake": 60, "Ocean": 55,
}
_RAIN_BASE = {
    "Desert": 5, "Tundra": 15, "Mountains": 25, "Grassland": 35, "Hills": 40,
    "Ocean": 50, "Lake": 55, "Forest": 65, "Wetland": 85, "Glacier": 10,
}


def compute_climate_cell(wd, x, y):
    biome = wd.biome_at(x, y)
    if biome is None:
        return None
    lat_factor = abs((y / max(wd.height, 1)) - 0.5) * 2  # 0 at equator-row, 1 at poles
    temp = _TEMP_BASE.get(biome, 55) - lat_factor * 35
    rain = _RAIN_BASE.get(biome, 40)
    return {"temp_f": round(temp), "rain_pct": rain}


# ---------------------------------------------------------------------------
# Drainage. Also speculative for the same reason (real river PATHS exist in
# the source XML but use a coordinate encoding we haven't fully cracked yet;
# see project notes. Deferred to v2 rather than shipped half-right). This
# approximates a drainage tendency from real biome type only.
# ---------------------------------------------------------------------------
_DRAINAGE_BASE = {
    "Ocean": 100, "Lake": 95, "Wetland": 80, "Forest": 55, "Grassland": 45,
    "Hills": 35, "Tundra": 30, "Desert": 5, "Mountains": 20, "Glacier": 15,
}


def compute_drainage_cell(wd, x, y):
    biome = wd.biome_at(x, y)
    if biome is None:
        return None
    return _DRAINAGE_BASE.get(biome, 40)


# ---------------------------------------------------------------------------
# Pure-stdlib PNG writer. No PIL dependency, same proven pattern used
# throughout this whole project.
# ---------------------------------------------------------------------------
def write_png(path, width, height, get_rgb):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b = get_rgb(x, y)
            raw += bytes((r, g, b))
    compressed = zlib.compress(bytes(raw), 6)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", compressed))
        f.write(chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# DETAILED MAP. DFCart's own richer renderer, separate from DwarfWiki's
# flat map.png. Same real per-tile biome data, but rendered at real
# up-resolution with two noise passes:
#   1. Domain warping. SOURCE SAMPLING coordinates get perturbed by a
#      coarse noise field before looking up the biome tile, so coastlines
#      and borders come out as organic curves instead of a razor-straight
#      grid stair-step. This is the key trick for "full definition without
#      blur": no pixel ever gets averaged/softened, every pixel is still a
#      single crisp, saturated real biome color. The ORGANIC SHAPE comes
#      from where we look, not from smearing what we find.
#   2. Fine per-pixel color jitter. Small RGB variation within each biome
#      region so flat color fields read as textured terrain, not paint fill.
# Cached to disk once per world, same pattern as everything else.
# ---------------------------------------------------------------------------
DETAILED_RES = 1536

DETAIL_COLORS = {
    "Ocean":      (38, 68, 98),
    "Lake":       (78, 128, 160),
    "Glacier":    (228, 238, 244),
    "Mountains":  (112, 100, 92),
    "Hills":      (168, 146, 92),
    "Grassland":  (110, 142, 68),
    "Forest":     (44, 82, 42),
    "Wetland":    (82, 110, 96),
    "Tundra":     (188, 200, 204),
    "Desert":     (216, 178, 100),
}
DETAIL_UNKNOWN = (60, 90, 118)
WATER_SET = {"Ocean", "Lake"}


def _dm_hash(x, y):
    s = math.sin(x * 127.1 + y * 311.7) * 43758.5453
    return s - math.floor(s)


def _dm_noise(x, y):
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    a, b = _dm_hash(xi, yi), _dm_hash(xi + 1, yi)
    c, d = _dm_hash(xi, yi + 1), _dm_hash(xi + 1, yi + 1)
    u = xf * xf * (3 - 2 * xf)
    v = yf * yf * (3 - 2 * yf)
    return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v


def _compute_water_depth(wd):
    """Multi-source BFS from every LAND tile, expanding into water. Gives
    a real 'distance to nearest shore' value per water tile. Real geometry
    from the real biome grid, not decoration: this is what makes shallows
    near a coast and open, deep water further out look genuinely different
    instead of one flat ocean color everywhere."""
    W, H = wd.width, wd.height
    dist = [[-1] * W for _ in range(H)]
    q = deque()
    grid = wd.map_grid["grid"]
    types = wd.map_grid["types"]
    for y in range(H):
        for x in range(W):
            idx = grid[y][x]
            t = types[idx] if idx >= 0 else None
            if t is not None and t not in WATER_SET:
                dist[y][x] = 0
                q.append((x, y))
    MAX_D = 16
    while q:
        x, y = q.popleft()
        d = dist[y][x]
        if d >= MAX_D:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and dist[ny][nx] == -1:
                dist[ny][nx] = d + 1
                q.append((nx, ny))
    return dist, MAX_D


SHALLOW_COLOR = (72, 138, 148)
DEEP_COLOR = (18, 42, 78)


def generate_detailed_map(wd, out_path):
    W, H = wd.width, wd.height
    if not W or not H:
        return False
    R = DETAILED_RES
    depth_field, max_d = _compute_water_depth(wd)

    def biome_at(tx, ty):
        tx = max(0, min(W - 1, int(tx)))
        ty = max(0, min(H - 1, int(ty)))
        idx = wd.map_grid["grid"][ty][tx]
        return wd.map_grid["types"][idx] if idx >= 0 else None

    def depth_at(tx, ty):
        tx = max(0, min(W - 1, int(tx)))
        ty = max(0, min(H - 1, int(ty)))
        d = depth_field[ty][tx]
        return d if d >= 0 else max_d

    warp_strength = 2.6   # in TILE units. How far a sample can bend from its true position
    scale_to_tiles_x = W / R
    scale_to_tiles_y = H / R

    def px(ox, oy):
        # coarse warp field. Low frequency, big organic bends (coastlines, borders)
        wnx = _dm_noise(ox * 0.006, oy * 0.006) * 2 - 1
        wny = _dm_noise(ox * 0.006 + 91.7, oy * 0.006 + 41.3) * 2 - 1
        tx = ox * scale_to_tiles_x + wnx * warp_strength
        ty = oy * scale_to_tiles_y + wny * warp_strength
        biome = biome_at(tx, ty)

        if biome in WATER_SET:
            # real shallow-to-deep gradient, not a flat fill. Genuine
            # bathymetry from real distance-to-shore, softened with a touch
            # of noise so the shading bands don't read as hard rings
            d = depth_at(tx, ty) + (_dm_noise(ox * 0.05, oy * 0.05) - 0.5) * 2.5
            t = max(0.0, min(1.0, d / max_d))
            t = t ** 0.7   # bias toward the shallow end so most visible water still reads blue-green, not black
            base = tuple(int(SHALLOW_COLOR[i] + (DEEP_COLOR[i] - SHALLOW_COLOR[i]) * t) for i in range(3))
        else:
            base = DETAIL_COLORS.get(biome, DETAIL_UNKNOWN)
            # coastal darkening. Checked on the WARPED (visually-real)
            # position, not the raw grid, so it follows the organic
            # coastline we just drew
            if biome is not None:
                for dtx, dty in ((3, 0), (-3, 0), (0, 3), (0, -3)):
                    if biome_at(tx + dtx, ty + dty) in WATER_SET:
                        base = tuple(max(0, int(c * 0.82)) for c in base)
                        break

        # fine per-pixel texture jitter. Higher frequency, small amplitude,
        # gives mottled terrain texture instead of flat paint-fill color
        jitter = (_dm_noise(ox * 0.09, oy * 0.09) - 0.5) * (16 if biome in WATER_SET else 26)
        return tuple(max(0, min(255, int(c + jitter))) for c in base)

    write_png(out_path, R, R, px)
    return True


# ---------------------------------------------------------------------------
# Distance / area math (imperial, using the verified MILES_PER_TILE)
# ---------------------------------------------------------------------------
def tile_distance(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def polygon_area_tiles(points):
    """Shoelace formula."""
    n = len(points)
    if n < 3:
        return 0
    area = 0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2
