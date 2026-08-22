"""
parser.py  --  Dwarf Fortress legends importer
==============================================

Reads a world's `*-legends.xml` (vanilla) and `*-legends_plus.xml` (DFHack)
pair and produces a set of clean, merged JSON files the wiki server can serve.

Why two files?  They are two halves of the same record.  For the SAME id,
each file carries DIFFERENT fields (e.g. legends.xml gives a figure its name
and skills; legends_plus.xml gives it its sex).  Neither is complete alone, so
every shared entity type is merged by id, unioning the fields.  Events get
`year` from legends.xml (the plus file drops it) and richer, better-resolved
reference fields from legends_plus.xml layered on top.

Usage
-----
    python parser.py                # scan ../worlds, import any not-yet-parsed
    python parser.py <world_dir>    # (re)import one world folder
    python parser.py --force        # re-import everything

A world folder looks like:
    worlds/<name>/raw/<something>-legends.xml
    worlds/<name>/raw/<something>-legends_plus.xml
and output lands in:
    worlds/<name>/parsed/*.json
"""

import os
import sys
import re
import json
import glob
import time
import struct
import zlib
from collections import defaultdict

import lxml.etree as ET

import events_render as ER
import flavor_hf as FL
import flavor_bestiary as FLB

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SERVER_DIR)          # project root (…/DwarfWiki)
WORLDS_DIR = os.path.join(BASE_DIR, "worlds")


# ---------------------------------------------------------------------------
# World map rendering. A real per-tile biome map, built entirely from data
# already present in legends_plus.xml (each <region> carries a full list of
# every world tile it owns). Rendered with a hand-rolled PNG writer using
# only zlib/struct from the standard library, so no new pip dependency
# (like Pillow) is ever required on the user's machine.
# ---------------------------------------------------------------------------
BIOME_COLORS = {
    "Ocean":      (46, 74, 102),
    "Lake":       (94, 138, 168),
    "Glacier":    (232, 240, 244),
    "Mountains":  (118, 108, 102),
    "Hills":      (166, 148, 98),
    "Grassland":  (120, 148, 82),
    "Forest":     (55, 90, 52),
    "Wetland":    (92, 116, 100),
    "Tundra":     (196, 206, 210),   # cold blue-grey. Was olive-khaki, read as
                                     # savanna instead of ice; this is the fix
    "Desert":     (214, 178, 106),
}
BIOME_UNKNOWN = (207, 198, 176)   # unmapped tile fallback (blends with parchment bg)
WATER_TYPES = {"Ocean", "Lake"}

# Approximate elevation (0-255 grayscale) per biome, for Azgaar heightmap
# export. DF's own elevation export is what's broken on Steam (the whole
# reason this project exists), this is a defensible ORDERING derived from
# real biome type, not real elevation data, and is presented to the user as
# exactly that: a time-saving starting point, not ground truth.
ELEVATION_GRAY = {
    "Ocean":      18,
    "Lake":       46,
    "Wetland":    70,
    "Grassland":  108,
    "Forest":     116,
    "Desert":     128,
    "Tundra":     150,
    "Hills":      185,
    "Mountains":  232,
    "Glacier":    248,
}

# Site-type -> pin color, grouped by rough character rather than one color
# per DF type string (there are ~20+ distinct type strings in real data).
SITE_PIN_GROUPS = {
    "fortress": "#7a2e2e", "fort": "#7a2e2e", "castle": "#7a2e2e",
    "dark fortress": "#4a1f1f", "tower": "#4a1f1f",
    "town": "#3a5a40", "hamlet": "#3a5a40", "hillocks": "#3a5a40",
    "camp": "#8a6d33",
    "monastery": "#5c4a7a", "shrine": "#5c4a7a", "tomb": "#5c4a7a",
    "cave": "#5a5248", "mountain halls": "#5a5248", "labyrinth": "#5a5248",
    "lair": "#8a3a3a", "mysterious lair": "#8a3a3a",
    "dark pits": "#3a2a3a", "mysterious dungeon": "#3a2a3a",
    "forest retreat": "#4f6b3f",
}
SITE_PIN_DEFAULT = "#6a6154"

# Races treated as "civilized" for the epithet classifier. Everything else
# (forgotten beasts, ettins, trolls, wildlife) is fair game for monster-track
# epithets. Confirmed against real census data rather than guessed.
CIVILIZED_RACES = {"human", "dwarf", "goblin", "elf", "kobold", "gnome"}


# ---------------------------------------------------------------------------
# Terminal color. Pure stdlib, no colorama dependency. Windows 10+'s modern
# console host supports ANSI natively but needs virtual-terminal processing
# switched on first for classic cmd.exe (Windows Terminal already has it on).
# ---------------------------------------------------------------------------
def _enable_windows_ansi():
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


class C:
    _on = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False
    RESET = "\033[0m" if _on else ""
    BOLD = "\033[1m" if _on else ""
    DIM = "\033[2m" if _on else ""
    RED = "\033[91m" if _on else ""
    GREEN = "\033[92m" if _on else ""
    YELLOW = "\033[93m" if _on else ""
    BLUE = "\033[94m" if _on else ""
    MAGENTA = "\033[95m" if _on else ""
    CYAN = "\033[96m" if _on else ""
    GREY = "\033[90m" if _on else ""


def _banner():
    art = r"""
   ___                  __ _       ___ _    _
  |   \__ __ ____ _ _ _ / _\ \    / (_) |__(_)
  | |) \ V  V / _` | '_|\__ \\ /\ / /| | / /| |
  |___/ \_/\_/\__,_|_|  |___/ \/  \/ |_|_\_\|_|
"""
    print(f"{C.CYAN}{C.BOLD}{art}{C.RESET}")
    print(f"{C.GREY}  a local legends viewer{C.RESET}\n")


def _step(msg):
    print(f"{C.BLUE}▸{C.RESET} {msg}", flush=True)


def _ok(msg):
    print(f"  {C.GREEN}✓{C.RESET} {msg}", flush=True)


def _warn(msg):
    print(f"  {C.YELLOW}⚠{C.RESET} {msg}", flush=True)


def _fail(msg):
    print(f"  {C.RED}✗{C.RESET} {msg}", flush=True)


def _progress_bar(current, total, width=28, label=""):
    total = max(total, 1)
    frac = min(1.0, current / total)
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r  {C.CYAN}[{bar}]{C.RESET} {frac*100:5.1f}%  {label}", end="", flush=True)


# ---------------------------------------------------------------------------
# XML file pairing. Finds a base+plus pair by NAME CORRELATION, not by
# hunting for the literal word "legends". A file counts as the "plus" half
# of a pair if removing the token "plus" (case-insensitive, any position)
# from its name yields exactly another XML file's name in the same folder.
# This is what actually prevents World A's plus-file getting paired with
# World B's base file. Pairing is per-folder and name-exact, never "grab
# the first base file and the first plus file I see".
# ---------------------------------------------------------------------------
def _strip_plus_token(stem):
    return re.sub(r"[_\-\s]?plus[_\-\s]?", "", stem, flags=re.IGNORECASE)


def discover_xml_pairs(raw_dir):
    """
    Returns (pairs, orphan_base, orphan_plus, ambiguous):
      pairs        -> list of (base_path, plus_path)
      orphan_base  -> base-looking files with no matching plus file
      orphan_plus  -> plus-looking files with no matching base file
      ambiguous    -> plus files that matched more than one base candidate
    """
    if not os.path.isdir(raw_dir):
        return [], [], [], []
    xmls = [f for f in os.listdir(raw_dir) if f.lower().endswith(".xml")]
    base_candidates = {}   # stem -> full path
    plus_candidates = []   # (stem, stripped_stem, full path)
    for fname in xmls:
        stem = os.path.splitext(fname)[0]
        full = os.path.join(raw_dir, fname)
        if re.search(r"plus", stem, re.IGNORECASE):
            plus_candidates.append((stem, _strip_plus_token(stem), full))
        else:
            base_candidates[stem.lower()] = full

    pairs = []
    orphan_plus = []
    ambiguous = []
    used_bases = set()
    for stem, stripped, full in plus_candidates:
        matches = [v for k, v in base_candidates.items() if k == stripped.lower()]
        if len(matches) == 1:
            pairs.append((matches[0], full))
            used_bases.add(matches[0])
        elif len(matches) == 0:
            orphan_plus.append(full)
        else:
            ambiguous.append(full)
    orphan_base = [p for p in base_candidates.values() if p not in used_bases]
    return pairs, orphan_base, orphan_plus, ambiguous


# ---------------------------------------------------------------------------
# Fast content validation. A lightweight, count-only pass (no field
# extraction) over the four major sections. Verified against real matched
# legends.xml/legends_plus.xml files: a genuine pair has EXACTLY identical
# counts on all four, every time, because they're two exports of the same
# simulated world. Any mismatch means these files did not come from the
# same world, full stop, not a "probably fine, continue anyway" situation.
# ---------------------------------------------------------------------------
_VALIDATE_SECTIONS = ("historical_figures", "sites", "entities", "artifacts")


def fast_section_counts(path):
    counts = {s: 0 for s in _VALIDATE_SECTIONS}
    try:
        ctx = ET.iterparse(path, events=("start", "end"), recover=True, huge_tree=True)
        depth = 0
        section = None
        for ev, el in ctx:
            if ev == "start":
                depth += 1
                if depth == 2:
                    section = el.tag
            else:
                if depth == 3 and section in counts:
                    counts[section] += 1
                if depth <= 2:
                    el.clear()
                depth -= 1
    except Exception as ex:
        counts["_error"] = str(ex)
    return counts


def validate_pair(base_path, plus_path):
    base_counts = fast_section_counts(base_path)
    plus_counts = fast_section_counts(plus_path)
    if "_error" in base_counts or "_error" in plus_counts:
        return False, {"error": base_counts.get("_error") or plus_counts.get("_error"),
                       "base_counts": base_counts, "plus_counts": plus_counts}
    if sum(base_counts.values()) == 0:
        return False, {"error": "base file has no recognizable legends data. Is it empty or corrupt?",
                       "base_counts": base_counts, "plus_counts": plus_counts}
    mismatches = {s: (base_counts[s], plus_counts[s])
                 for s in _VALIDATE_SECTIONS if base_counts[s] != plus_counts[s]}
    ok = not mismatches
    return ok, {"base_counts": base_counts, "plus_counts": plus_counts, "mismatches": mismatches}


def print_import_preview(world_name, base_path, plus_path, ok, report):
    print(f"\n{C.BOLD}IMPORT PREVIEW{C.RESET}  {C.GREY}({world_name}){C.RESET}")
    print(f"  {C.GREY}Base:{C.RESET}       {os.path.basename(base_path)}")
    print(f"  {C.GREY}Extension:{C.RESET}  {os.path.basename(plus_path)}")
    print()
    if "error" in report:
        _fail(f"Compatibility:  {report['error']}")
        print(f"\n{C.RED}{C.BOLD}WARNING: Possible dataset mismatch detected.{C.RESET}")
        print(f"{C.RED}Import cancelled for '{world_name}'.{C.RESET}\n")
        return
    bc, pc = report["base_counts"], report["plus_counts"]
    if ok:
        _ok("Compatibility:  Valid pair")
        print()
        for s in _VALIDATE_SECTIONS:
            print(f"  {C.GREY}{s.replace('_',' ').title():20s}{C.RESET} {bc[s]:>8,}")
        print(f"\n{C.GREEN}Proceeding automatically. All checks passed.{C.RESET}\n")
    else:
        _fail("Compatibility:  MISMATCH")
        print()
        for s, (b, p) in report["mismatches"].items():
            print(f"  {C.RED}{s.replace('_',' ').title():20s} base={b:,}  extension={p:,}  ✗{C.RESET}")
        print(f"\n{C.RED}{C.BOLD}WARNING: Possible dataset mismatch detected.{C.RESET}")
        print(f"{C.GREY}These two files most likely come from DIFFERENT worlds, "
              f"pairing them would corrupt the encyclopedia data.{C.RESET}")
        print(f"{C.RED}Import cancelled for '{world_name}'.{C.RESET}\n")


def write_png(path, width, height, get_rgb):
    """
    Minimal pure-stdlib PNG writer (RGB, 8-bit, no interlace).
    get_rgb(x, y) -> (r, g, b) is called once per pixel.
    Avoids any new pip dependency (e.g. Pillow) on the user's machine.
    """
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: None
        for x in range(width):
            r, g, b = get_rgb(x, y)
            raw += bytes((r, g, b))
    compressed = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", compressed))
        f.write(chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# Streaming driver
# ---------------------------------------------------------------------------
def peek_world_name(plus_path):
    """Read just the world's <name>/<altname>. The first two elements in
    legends_plus.xml. Without touching the rest of the (often huge) file.
    Used both by WorldImporter itself and, standalone, by the web upload
    route in server.py so it can name a world straight from the file the
    person just picked instead of asking them to type one in first."""
    world_name, world_altname = None, None
    try:
        ctx = ET.iterparse(plus_path, events=("end",), recover=True, huge_tree=True)
        for _, el in ctx:
            if el.tag == "name" and world_name is None:
                world_name = el.text
            elif el.tag == "altname":
                world_altname = el.text
                break
            elif el.tag in ("landmasses", "regions"):
                break
    except Exception:
        pass
    return world_name, world_altname


def stream_sections(path, handlers, progress_label=""):
    """
    Walk a huge legends XML once, dispatching each top-level list *item*
    (depth 3: e.g. a <site>, <historical_figure>) to handlers[section_name].

    Memory stays flat: after each item we clear it AND drop already-processed
    siblings so the parent list never accumulates.
    """
    ctx = ET.iterparse(path, events=("start", "end"), recover=True, huge_tree=True)
    depth = 0
    section = None
    section_elem = None
    seen = 0
    last_report = time.time()
    spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    spin_i = 0

    for event, el in ctx:
        if event == "start":
            depth += 1
            if depth == 2:
                section = el.tag
                section_elem = el
        else:
            if depth == 3:
                if section in handlers:
                    handlers[section](el)
                seen += 1
                el.clear()
                prev = el.getprevious()
                while prev is not None:
                    section_elem.remove(prev)
                    prev = el.getprevious()
                if progress_label and seen % 5000 == 0:
                    now = time.time()
                    if now - last_report > 0.12:
                        spin_i = (spin_i + 1) % len(spinner)
                        print(f"\r  {C.CYAN}{spinner[spin_i]}{C.RESET} {progress_label}: "
                              f"{C.BOLD}{seen:,}{C.RESET} items processed", end="", flush=True)
                        last_report = now
            elif depth == 2:
                el.clear()
            depth -= 1
    if progress_label and seen:
        print(f"\r  {C.GREEN}✓{C.RESET} {progress_label}: {C.BOLD}{seen:,}{C.RESET} items processed" + " " * 10)


def txt(el, tag, default=None):
    child = el.find(tag)
    if child is None or child.text is None:
        return default
    return child.text


def itxt(el, tag):
    v = txt(el, tag)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def prettify_code(code):
    """HYDRA -> hydra, CAVE_DRAGON -> cave dragon."""
    if code is None:
        return None
    return str(code).replace("_", " ").lower()


# ---------------------------------------------------------------------------
# The importer
# ---------------------------------------------------------------------------
def _box_blur(vals, W, H, passes=2):
    """Simple averaging blur over a 2D grid of ints. Smooths the hard
    biome-edge transitions into gradients, which matters for a heightmap
    (Azgaar wants smooth elevation, not blocky steps) but not for the
    biome color map (which stays crisp on purpose)."""
    for _ in range(passes):
        new = [[0] * W for _ in range(H)]
        for y in range(H):
            for x in range(W):
                total = 0
                count = 0
                for dy in (-1, 0, 1):
                    ny = y + dy
                    if ny < 0 or ny >= H:
                        continue
                    for dx in (-1, 0, 1):
                        nx = x + dx
                        if 0 <= nx < W:
                            total += vals[ny][nx]
                            count += 1
                new[y][x] = total // count
        vals = new
    return vals


def render_world_map(grid, W, H, parsed_dir):
    """
    grid: 2D list [y][x] of biome-type strings (or None for unmapped).
    Renders map.png (crisp biome colors), heightmap.png (smoothed grayscale
    elevation approximation for Azgaar import), map.json (legend + dims),
    and map_grid.json (compact persisted grid so a future palette tweak can
    re-render from here instead of re-parsing the source XML).
    Shared by both the full importer and the standalone --recolor fast path.
    """
    def blend(c, factor):
        return tuple(max(0, int(ch * factor)) for ch in c)

    def rgb_for(x, y):
        t = grid[y][x]
        base = BIOME_COLORS.get(t, BIOME_UNKNOWN)
        if t is None or t in WATER_TYPES:
            return base
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] in WATER_TYPES:
                return blend(base, 0.82)
        return base

    write_png(os.path.join(parsed_dir, "map.png"), W, H, rgb_for)

    # heightmap. Elevation approximated from biome type. Deliberately NOT
    # blurred/smoothed: Azgaar's Image Converter asks the user to manually
    # assign a height to every DISTINCT color it finds in the image. A
    # smoothed gradient explodes 10 clean bands into 200+ near-duplicate
    # grays, turning import into exactly the tile-by-tile manual painting
    # this feature exists to avoid. Flat discrete bands keep it to ~10
    # colors. A couple of minutes of one-time setup in Azgaar, not hours.
    def gray_for(x, y):
        v = ELEVATION_GRAY.get(grid[y][x], 90)
        return (v, v, v)

    write_png(os.path.join(parsed_dir, "heightmap.png"), W, H, gray_for)

    legend = [{"type": t, "color": "#%02x%02x%02x" % c} for t, c in BIOME_COLORS.items()]
    dims = {"width": W, "height": H, "legend": legend}
    _dump(parsed_dir, "map.json", dims)

    # persist the raw grid compactly (type-index table + flat rows) so a
    # future palette-only change can re-render without touching the XML
    types = sorted({t for row in grid for t in row if t is not None})
    tidx = {t: i for i, t in enumerate(types)}
    flat = [[tidx[t] if t is not None else -1 for t in row] for row in grid]
    _dump(parsed_dir, "map_grid.json", {"width": W, "height": H, "types": types, "grid": flat})

    return dims


def recolor_world(world_dir):
    """Re-render map.png/heightmap.png from a previously-persisted
    map_grid.json. No XML re-parse. Used by `python parser.py --recolor`."""
    parsed_dir = os.path.join(world_dir, "parsed")
    grid_path = os.path.join(parsed_dir, "map_grid.json")
    if not os.path.exists(grid_path):
        print(f"   !! no map_grid.json for {os.path.basename(world_dir)}, "
              f"needs one full import first")
        return False
    with open(grid_path, encoding="utf-8") as f:
        data = json.load(f)
    W, H, types, flat = data["width"], data["height"], data["types"], data["grid"]
    grid = [[(types[v] if v >= 0 else None) for v in row] for row in flat]
    render_world_map(grid, W, H, parsed_dir)
    print(f"   ✓ Recolored '{os.path.basename(world_dir)}' from cached grid (no XML re-parse)")
    return True


class WorldImporter:
    def __init__(self, world_dir):
        self.world_dir = world_dir
        self.name = os.path.basename(world_dir.rstrip("/\\"))
        self.raw_dir = os.path.join(world_dir, "raw")
        self.parsed_dir = os.path.join(world_dir, "parsed")

        # merged records keyed by id
        self.figures = {}
        self.sites = {}
        self.artifacts = {}
        self.entities = {}
        self.regions = {}
        self.uregions = {}
        self.written = {}
        self.identities = {}
        self.creatures = {}          # CODE -> singular name
        self.landmasses = {}
        self.peaks = {}
        self.constructions = {}

        # events keyed by id; value is a plain dict of raw fields (both files)
        self.events = {}
        self.collections = {}
        self.eras = []
        self.relationships = []      # list of (src_hf, tgt_hf, rel, year, event)

        # world map: tile (x,y) -> region biome type string, filled from
        # legends_plus.xml <region><coords>, colored using self.regions[id]['type']
        self.tile_region_type = {}
        self.max_tile_x = 0
        self.max_tile_y = 0

        # world-level
        self.world_name = None
        self.world_altname = None

        # cross-reference: entity id -> set of event ids, etc.
        self.hf_events = defaultdict(list)
        self.site_events = defaultdict(list)
        self.ent_events = defaultdict(list)
        self.art_events = defaultdict(list)

    # -- locate the two xml files (fallback path; main() normally passes
    #    already-discovered-and-validated paths in directly) --------------
    def find_xml(self):
        pairs, orphan_base, orphan_plus, ambiguous = discover_xml_pairs(self.raw_dir)
        if len(pairs) == 1:
            return pairs[0]
        return None, None

    # =====================================================================
    # PASS 1 : legends.xml  (canonical structure, names, years)
    # =====================================================================
    def _h_region(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        self.regions[i] = {"id": i, "name": txt(el, "name"),
                           "type": txt(el, "type")}

    def _h_uregion(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        self.uregions[i] = {"id": i, "type": txt(el, "type"),
                            "depth": itxt(el, "depth")}

    def _h_site(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        structures = []
        s_parent = el.find("structures")
        if s_parent is not None:
            for s in s_parent.findall("structure"):
                structures.append({
                    "local_id": itxt(s, "local_id"),
                    "type": txt(s, "type"),
                    "name": txt(s, "name"),
                })
        self.sites[i] = {
            "id": i,
            "type": txt(el, "type"),
            "name": txt(el, "name"),
            "coords": txt(el, "coords"),
            "rectangle": txt(el, "rectangle"),
            "structures": structures,
        }

    def _h_artifact(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        item = el.find("item")
        name = None
        if item is not None:
            name = txt(item, "name_string")
        rec = self.artifacts.setdefault(i, {"id": i})
        rec["name"] = name or txt(el, "name")
        rec["holder_hfid"] = itxt(el, "holder_hfid")
        site_id = itxt(el, "site_id")
        if site_id is not None:
            rec["site_id"] = site_id

    def _h_figure(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        entity_links = []
        for e in el.findall("entity_link"):
            entity_links.append({
                "type": txt(e, "link_type"),
                "entity_id": itxt(e, "entity_id"),
            })
        site_links = []
        for s in el.findall("site_link"):
            site_links.append({
                "type": txt(s, "link_type"),
                "site_id": itxt(s, "site_id"),
            })
        spheres = [s.text for s in el.findall("sphere") if s.text]
        skills = []
        for sk in el.findall("hf_skill"):
            skills.append({"skill": prettify_code(txt(sk, "skill")),
                           "ip": itxt(sk, "total_ip")})
        rec = self.figures.setdefault(i, {"id": i})
        rec.update({
            "name": txt(el, "name"),
            "race": prettify_code(txt(el, "race")),
            "race_code": txt(el, "race"),
            "caste": (txt(el, "caste") or "").lower() or None,
            "birth_year": itxt(el, "birth_year"),
            "death_year": itxt(el, "death_year"),
            "appeared": itxt(el, "appeared"),
            "associated_type": (txt(el, "associated_type") or "").lower() or None,
            "entity_links": entity_links,
            "site_links": site_links,
            "spheres": spheres,
            "skills": skills,
        })

    def _h_entity(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        honors = []
        for h in el.findall("honor"):
            honors.append({"id": itxt(h, "id"), "name": txt(h, "name")})
        rec = self.entities.setdefault(i, {"id": i})
        rec["name"] = txt(el, "name")
        if honors:
            rec["honors"] = honors

    def _h_written(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        styles = [s.text for s in el.findall("style") if s.text]
        self.written[i] = {
            "id": i,
            "title": txt(el, "title"),
            "author_hfid": itxt(el, "author_hfid"),
            "form": txt(el, "form"),
            "form_id": itxt(el, "form_id"),
            "styles": styles,
        }

    def _h_era(self, el):
        self.eras.append({"name": txt(el, "name"),
                          "start_year": itxt(el, "start_year")})

    def _event_dict(self, el):
        d = {}
        for c in el:
            # keep last value if repeated 'event'/'eventcol'. Those go elsewhere
            d[c.tag] = c.text
        return d

    def _h_event(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        d = self._event_dict(el)
        # normalise the important bits
        ev = self.events.setdefault(i, {})
        # legends.xml wins for type (spaced) and year
        ev["type"] = d.get("type")
        y = d.get("year")
        ev["year"] = int(y) if (y not in (None, "") and y.lstrip("-").isdigit()) else None
        for k, v in d.items():
            if k in ("type", "year"):
                continue
            ev[k] = v

    def _h_collection(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        rec = {
            "id": i,
            "type": txt(el, "type"),
            "name": txt(el, "name"),                 # wars & battles are named
            "start_year": itxt(el, "start_year"),
            "end_year": itxt(el, "end_year"),
            "site_id": itxt(el, "site_id"),
            "subregion_id": itxt(el, "subregion_id"),
            "civ_id": itxt(el, "civ_id"),
            "parent": itxt(el, "parent_eventcol"),
            "war_eventcol": itxt(el, "war_eventcol"),  # battle -> parent war
            "n_events": len(el.findall("event")),
            # belligerents (field names vary by collection type)
            "aggressor_ent": itxt(el, "aggressor_ent_id"),
            "defender_ent": itxt(el, "defender_ent_id"),
            "attacking_enid": itxt(el, "attacking_enid"),
            "defending_enid": itxt(el, "defending_enid"),
            "attacking_hfid": itxt(el, "attacking_hfid"),
            "defending_hfid": itxt(el, "defending_hfid"),
            "outcome": txt(el, "outcome"),
            "atk_deaths": itxt(el, "attacking_squad_deaths"),
            "def_deaths": itxt(el, "defending_squad_deaths"),
        }
        self.collections[i] = rec

    def parse_base(self, path):
        _step(f"[1/2] Reading base file ({_mb(path)})…")
        # world name lives at the very top of legends.xml as <name> under df_world?
        # (It's actually only reliably in the plus file; grab there.)
        handlers = {
            "regions": self._h_region,
            "underground_regions": self._h_uregion,
            "sites": self._h_site,
            "artifacts": self._h_artifact,
            "historical_figures": self._h_figure,
            "entities": self._h_entity,
            "written_contents": self._h_written,
            "historical_eras": self._h_era,
            "historical_events": self._h_event,
            "historical_event_collections": self._h_collection,
        }
        stream_sections(path, handlers, progress_label="events")

    # =====================================================================
    # PASS 2 : legends_plus.xml  (extra sections + field enrichment)
    # =====================================================================
    def _hp_creature(self, el):
        code = txt(el, "creature_id")
        if code is None:
            return
        self.creatures[code] = txt(el, "name_singular") or prettify_code(code)

    def _hp_figure(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        rec = self.figures.setdefault(i, {"id": i})
        sex = itxt(el, "sex")
        if sex is not None:
            rec["sex"] = {0: "female", 1: "male"}.get(sex)
        # race here is already lower-case; only fill if base missing
        if not rec.get("race"):
            rec["race"] = txt(el, "race")

    def _hp_site(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        # plus site is usually a bare <id>; nothing extra worth merging today,
        # but keep the hook so a future DFHack version that adds fields works.
        self.sites.setdefault(i, {"id": i})

    def _hp_artifact(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        rec = self.artifacts.setdefault(i, {"id": i})
        rec["item_type"] = txt(el, "item_type")
        rec["item_subtype"] = txt(el, "item_subtype")
        rec["material"] = txt(el, "mat")

    def _hp_entity(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        rec = self.entities.setdefault(i, {"id": i})
        rec["race"] = txt(el, "race")
        rec["type"] = txt(el, "type")
        rec["worship_id"] = itxt(el, "worship_id")
        # members
        member_ids = [c.text for c in el.findall("histfig_id") if c.text]
        rec["n_members"] = len(member_ids)
        # child entities (a civ's sub-groups)
        children = []
        for lk in el.findall("entity_link"):
            if (txt(lk, "type") or "").upper() == "CHILD":
                t = itxt(lk, "target")
                if t is not None:
                    children.append(t)
        if children:
            rec["children"] = children
        # positions
        positions = []
        for p in el.findall("entity_position"):
            positions.append({"id": itxt(p, "id"), "name": txt(p, "name")})
        if positions:
            rec["positions"] = positions

    def _hp_identity(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        self.identities[i] = {
            "id": i,
            "name": txt(el, "name"),
            "histfig_id": itxt(el, "histfig_id"),
            "entity_id": itxt(el, "entity_id"),
        }

    def _hp_landmass(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        self.landmasses[i] = {"id": i, "name": txt(el, "name"),
                              "coord_1": txt(el, "coord_1"),
                              "coord_2": txt(el, "coord_2")}

    def _hp_peak(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        self.peaks[i] = {"id": i, "name": txt(el, "name"),
                         "coords": txt(el, "coords"),
                         "height": itxt(el, "height")}

    def _hp_construction(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        self.constructions[i] = {"id": i, "name": txt(el, "name"),
                                 "type": txt(el, "type")}

    def _hp_event(self, el):
        i = itxt(el, "id")
        if i is None:
            return
        ev = self.events.get(i)
        if ev is None:
            # event only in plus (shouldn't happen: plus ⊆ base). Keep anyway
            ev = self.events.setdefault(i, {})
            ev["type"] = (txt(el, "type") or "").replace("_", " ")
            ev["year"] = None
        # enrich with plus fields, but NEVER clobber canonical type/year
        for c in el:
            if c.tag in ("type", "year"):
                continue
            if c.text is not None:
                ev[c.tag] = c.text

    def _hp_relationship(self, el):
        src = itxt(el, "source_hf")
        tgt = itxt(el, "target_hf")
        if src is None or tgt is None:
            return
        self.relationships.append({
            "src": src, "tgt": tgt,
            "rel": txt(el, "relationship"),
            "year": itxt(el, "year"),
            "event": itxt(el, "event"),
        })

    def _hp_worldname(self, el):
        # <name> / <altname> are direct children of df_world in plus
        pass

    def _hp_region_coords(self, el):
        """
        legends_plus.xml's <region> carries a full pipe-delimited list of
        every world tile it owns, this is the raw material for the world
        map. legends.xml (parsed earlier, in parse_base) already gave us
        this region's biome TYPE, so we can color tiles immediately.
        """
        i = itxt(el, "id")
        coords = txt(el, "coords")
        if i is None or not coords:
            return
        rtype = self.regions.get(i, {}).get("type")
        for pair in coords.split("|"):
            if "," not in pair:
                continue
            xs, ys = pair.split(",", 1)
            try:
                x, y = int(xs), int(ys)
            except ValueError:
                continue
            if x > self.max_tile_x:
                self.max_tile_x = x
            if y > self.max_tile_y:
                self.max_tile_y = y
            self.tile_region_type[(x, y)] = rtype

    def parse_plus(self, path):
        _step(f"[2/2] Reading extension file ({_mb(path)})…")
        # world name: read the leading <name>/<altname> quickly
        self._read_world_name(path)
        handlers = {
            "creature_raw": self._hp_creature,
            "historical_figures": self._hp_figure,
            "sites": self._hp_site,
            "artifacts": self._hp_artifact,
            "entities": self._hp_entity,
            "identities": self._hp_identity,
            "landmasses": self._hp_landmass,
            "mountain_peaks": self._hp_peak,
            "world_constructions": self._hp_construction,
            "historical_events": self._hp_event,
            "historical_event_relationships": self._hp_relationship,
            "regions": self._hp_region_coords,
        }
        stream_sections(path, handlers, progress_label="events(+)")

    def _read_world_name(self, path):
        # name/altname are the first two elements; read a small prefix
        try:
            self.world_name, self.world_altname = peek_world_name(path)
        except Exception:
            pass

    # =====================================================================
    # POST : resolve races, cross-ref events, render, derive notability
    # =====================================================================
    def resolve_races(self):
        for f in self.figures.values():
            code = f.get("race_code")
            if code and code in self.creatures:
                f["race"] = self.creatures[code]
            elif f.get("race"):
                f["race"] = prettify_code(f["race"]) if f["race"].isupper() else f["race"]
            f.pop("race_code", None)

    _HF_REF_FIELDS = [
        "hfid", "hist_figure_id", "hfid_target", "target_hfid", "slayer_hfid",
        "slayer_hf", "victim_hf", "victim", "eater", "group_1_hfid",
        "group_2_hfid", "woundee_hfid", "woundee", "wounder_hfid", "wounder",
        "convicted_hfid", "snatcher_hfid", "attacker_hfid", "changee_hfid",
        "changer_hfid", "winner_hfid", "competitor_hfid", "builder_hfid",
        "builder_hf", "trickster_hfid", "trickster", "corruptor_hfid",
        "group_hfid", "teacher_hfid", "student_hfid", "speaker_hfid",
        "new_leader_hfid", "hfid1", "hfid2", "hf", "hf_target", "target",
        "creator_hfid", "maker_hfid",
    ]
    _SITE_REF_FIELDS = ["site_id", "site", "site_id1", "site_id2",
                        "source_site_id", "dest_site_id", "stash_site"]
    _ENT_REF_FIELDS = ["civ_id", "entity_id", "entity", "target_enid",
                       "defender_civ_id", "attacker_civ_id", "site_civ_id",
                       "site_civ", "defending_enid", "attacking_enid"]
    _ART_REF_FIELDS = ["artifact_id", "artifact"]

    def _collect_ref(self, ev, fields):
        out = set()
        for k in fields:
            v = ev.get(k)
            if v not in (None, "", "-1"):
                try:
                    out.add(int(v))
                except (ValueError, TypeError):
                    pass
        return out

    def crossref_and_render(self):
        # Build resolver name tables
        hf_names = {i: (f.get("name") or f"{f.get('race','creature')} (unnamed)")
                    for i, f in self.figures.items()}
        site_names = {i: (s.get("name") or f"site #{i}") for i, s in self.sites.items()}
        ent_names = {i: (e.get("name") or f"entity #{i}") for i, e in self.entities.items()}
        art_names = {i: (a.get("name") or f"artifact #{i}") for i, a in self.artifacts.items()}
        region_names = {i: (r.get("name") or f"region #{i}") for i, r in self.regions.items()}
        wc_titles = {i: (w.get("title") or f"work #{i}") for i, w in self.written.items()}
        R = ER.Resolver(hf_names, site_names, ent_names, art_names,
                        region_names, wc_titles)

        # site -> owning entities (derived from co-occurring ids in events)
        site_owner = defaultdict(set)

        rendered = {}
        for eid, ev in self.events.items():
            hfs = self._collect_ref(ev, self._HF_REF_FIELDS)
            sites = self._collect_ref(ev, self._SITE_REF_FIELDS)
            ents = self._collect_ref(ev, self._ENT_REF_FIELDS)
            arts = self._collect_ref(ev, self._ART_REF_FIELDS)

            for h in hfs:
                self.hf_events[h].append(eid)
            for s in sites:
                self.site_events[s].append(eid)
            for e in ents:
                self.ent_events[e].append(eid)
            for a in arts:
                self.art_events[a].append(eid)
            # ownership signal: any event tying a site to a civ
            for s in sites:
                for e in ents:
                    site_owner[s].add(e)

            rendered[eid] = ER.render_event(ev, R)

        # collections -> render headline tokens + site cross-ref.
        # Wars/battles carry real names; use them.  Belligerent fields differ
        # by type: wars use entity ids, battles use figure ids (+outcome),
        # conquests use entity ids.
        rendered_cols = {}
        for cid, c in self.collections.items():
            ctype = (c.get("type") or "an event")
            site = R.site(c.get("site_id"))
            name = c.get("name")
            toks = []

            if ctype == "war":
                atk = R.ent(c.get("aggressor_ent"))
                dfk = R.ent(c.get("defender_ent"))
                if name:
                    toks = [name.title()]
                else:
                    toks = ["A war"]
                if atk or dfk:
                    toks += [": ", atk or "an unknown power", " against ",
                             dfk or "an unknown power"]
            elif ctype == "battle":
                atk = R.hf(c.get("attacking_hfid"))
                dfk = R.hf(c.get("defending_hfid"))
                if name:
                    toks = [name.title()]
                else:
                    toks = ["A battle"]
                if atk or dfk:
                    toks += [", ", atk or "a force", " versus ", dfk or "a force"]
                out = c.get("outcome")
                if out:
                    toks += [f" ({out.replace('_', ' ')})"]
            elif ctype == "site conquered":
                atk = R.ent(c.get("attacking_enid"))
                toks = ["The conquest of ", site or "a site"]
                if atk is not None:
                    toks += [" by ", atk]
                site = None  # already placed
            else:
                toks = [ctype.replace("_", " ")]

            if site is not None:
                toks += [" at ", site]
            if c.get("site_id") is not None and c.get("site_id") >= 0:
                self.site_events[c["site_id"]].append(("col", cid))

            rendered_cols[cid] = {
                "y": c.get("start_year"), "type": c.get("type"),
                "name": name,
                "cat": _collection_cat(c.get("type")),
                "tokens": ER._compact(toks + ["."]),
                "end_year": c.get("end_year"),
                "deaths": (c.get("atk_deaths") or 0) + (c.get("def_deaths") or 0)
                          if (c.get("atk_deaths") is not None or c.get("def_deaths") is not None)
                          else None,
                # raw structured refs (additive. Kept alongside the prose
                # tokens above, not instead of them) so downstream tools
                # like DFCart can plot real locations and link a battle to
                # its parent war without having to scrape rendered prose
                "site_id": c.get("site_id") if (c.get("site_id") is not None and c.get("site_id") >= 0) else None,
                "war_id": c.get("war_eventcol"),
                "aggressor_ent": c.get("aggressor_ent"),
                "defender_ent": c.get("defender_ent"),
                "attacking_ent": c.get("attacking_enid"),
                "defending_ent": c.get("defending_enid"),
            }

        self.rendered_events = rendered
        self.rendered_collections = rendered_cols

        # entity owned sites (reverse of site_owner)
        ent_sites = defaultdict(set)
        for s, owners in site_owner.items():
            for o in owners:
                ent_sites[o].add(s)
        for i, e in self.entities.items():
            owned = sorted(ent_sites.get(i, ()))
            if owned:
                e["owned_site_ids"] = owned

        self.hf_names = hf_names  # reuse later

    def derive_notability(self):
        REAL_ENTITY_TYPES = {
            "civilization", "religion", "sitegovernment", "site government",
            "nomadicgroup", "nomadic group", "religious organization",
            "militaryunit", "military unit", "outcast group", "guild",
            "performancetroupe", "merchantcompany", "merchant company",
        }
        for i, e in self.entities.items():
            has_name = bool(e.get("name"))
            etype = (e.get("type") or "").lower()
            owns = bool(e.get("owned_site_ids"))
            members = e.get("n_members", 0) or 0
            e["notable"] = bool(has_name and (owns or members >= 3 or
                                              etype in REAL_ENTITY_TYPES))
            e["n_events"] = len(self.ent_events.get(i, ()))

        for i, a in self.artifacts.items():
            n = len(self.art_events.get(i, ()))
            a["n_events"] = n
            a["notable"] = bool(a.get("name") and n >= 1)

        for i, f in self.figures.items():
            n = len(self.hf_events.get(i, ()))
            f["n_events"] = n
            # a figure is "notable" if it has a name and did anything of note,
            # or holds a leadership/deity role
            assoc = f.get("associated_type")
            f["notable"] = bool(f.get("name") and
                                (n >= 2 or assoc in ("deity", "force", "leader")))

        for i, s in self.sites.items():
            s["n_events"] = len(self.site_events.get(i, ()))

    # =====================================================================
    # WORLD MAP
    # =====================================================================
    def compute_world_map(self):
        W = self.max_tile_x + 1
        H = self.max_tile_y + 1
        if W <= 1 or H <= 1:
            self.map_dims = None
            return
        grid = [[self.tile_region_type.get((x, y)) for x in range(W)]
                for y in range(H)]
        self.map_dims = render_world_map(grid, W, H, self.parsed_dir)

    # =====================================================================
    # PERSON FLAVOR (deterministic word-bank text, gated by real signals)
    # =====================================================================
    _FAMILY_RELS = {"spouse", "child", "parent", "sibling", "grandparent",
                    "husband", "wife", "mother", "father", "son", "daughter"}

    def compute_hf_flavor(self):
        # world's current/latest year, for computing a living figure's age
        if not hasattr(self, "_year_max_cache"):
            years = [e.get("year") for e in self.events.values()
                     if isinstance(e.get("year"), int)]
            self._year_max_cache = max(years) if years else None
        current_year = self._year_max_cache

        for i, f in self.figures.items():
            ev_ids = f.get("event_ids", [])
            cats = set()
            died_violently = False
            for eid in ev_ids:
                rend = self.rendered_events.get(eid)
                if rend:
                    cats.add(rend.get("cat"))
                raw = self.events.get(eid)
                if raw and str(raw.get("type", "")) == "hf died":
                    victim = raw.get("hfid") or raw.get("victim_hf") or raw.get("victim")
                    try:
                        is_victim = victim is not None and int(victim) == i
                    except (ValueError, TypeError):
                        is_victim = False
                    slayer = raw.get("slayer_hfid") or raw.get("slayer_hf")
                    if is_victim and slayer not in (None, "", "-1"):
                        died_violently = True

            entity_links = f.get("entity_links", []) or []
            has_religion_link = False
            for el in entity_links:
                ent = self.entities.get(el.get("entity_id"))
                if ent and "religio" in (ent.get("type") or "").lower():
                    has_religion_link = True
                    break

            relationships = f.get("relationships", []) or []
            has_family_rel = any((r.get("rel") or "").replace("former_", "") in self._FAMILY_RELS
                                 for r in relationships)
            has_enemy_rel = (any("enemy" in (r.get("rel") or "").lower() for r in relationships) or
                             any((el.get("type") or "").lower() == "enemy" for el in entity_links))

            race = (f.get("race") or "").lower()
            birth_year = f.get("birth_year")
            death_year = f.get("death_year")
            age = None
            if isinstance(birth_year, int):
                end_year = death_year if death_year not in (None, -1) else current_year
                if isinstance(end_year, int):
                    age = max(0, end_year - birth_year)

            signals = {
                "has_combat": ER.CAT_COMBAT in cats,
                "has_creation": ER.CAT_CREATION in cats,
                "has_politics": ER.CAT_POLITICS in cats,
                "has_religion_event": has_religion_link or ER.CAT_RELIGION in cats,
                "has_crime": ER.CAT_CRIME in cats,
                "n_events": len(ev_ids),
                "has_family_rel": has_family_rel,
                "has_any_rel": bool(relationships),
                "has_enemy_rel": has_enemy_rel,
                "n_site_links": len(f.get("site_links", []) or []),
                "has_skills": bool(f.get("skills")),
                "has_spheres": bool(f.get("spheres")),
                "assoc_leader": f.get("associated_type") == "leader",
                "is_alive": f.get("death_year") in (None, -1),
                "is_monster": race not in CIVILIZED_RACES,
                "was_commoner_origin": len(entity_links) <= 1,
                "died_violently": died_violently,
                "age": age,
            }
            f["flavor"] = FL.compute_categories(i, signals)
            epithet = FL.compute_epithet(i, signals)
            if epithet:
                f["epithet"] = epithet

    # =====================================================================
    # YEAR STATS (precomputed per-year category tallies, for fast range
    # queries like "how many deaths between year 33 and 50" without
    # scanning all 200k+ events on every request)
    # =====================================================================
    def compute_year_stats(self):
        stats = defaultdict(lambda: defaultdict(int))
        for ev in self.rendered_events.values():
            y = ev.get("y")
            if not isinstance(y, int):
                continue
            cat = ev.get("cat") or "misc"
            stats[y][cat] += 1
            stats[y]["total"] += 1
        # plain dict, sorted, ready to dump
        self.year_stats = {str(y): dict(cats) for y, cats in sorted(stats.items())}

    # =====================================================================
    # BESTIARY (one entry per wildlife race with at least one named figure.
    # Civilized races are excluded, they already have the Civilizations system)
    # =====================================================================
    def compute_bestiary(self):
        by_race_figs = defaultdict(list)
        for i, f in self.figures.items():
            race = f.get("race")
            if race and f.get("name"):
                by_race_figs[race].append((i, f))

        self.bestiary = {}
        next_id = 0
        for race, figs in by_race_figs.items():
            if race.lower() in CIVILIZED_RACES:
                continue

            biome_tally = defaultdict(int)
            total_events = 0
            specimens = []
            for i, f in figs:
                total_events += f.get("n_events", 0)
                for sl in (f.get("site_links") or []):
                    site = self.sites.get(sl.get("site_id"))
                    coords = site.get("coords") if site else None
                    if coords and "," in coords:
                        try:
                            x, y = (int(v) for v in coords.split(",", 1))
                        except ValueError:
                            continue
                        biome = self.tile_region_type.get((x, y))
                        if biome:
                            biome_tally[biome] += 1
                if f.get("notable"):
                    specimens.append({
                        "id": i, "name": f.get("name"),
                        "epithet": f.get("epithet"),
                        "events": f.get("n_events", 0),
                    })
            specimens.sort(key=lambda s: -s["events"])

            signals = {
                "population_named": len(figs),
                "top_biomes": [b for b, _ in sorted(biome_tally.items(), key=lambda kv: -kv[1])[:3]],
                "has_specimens": bool(specimens),
            }
            self.bestiary[next_id] = {
                "id": next_id,
                "race": race,
                "population_named": len(figs),
                "total_events": total_events,
                "top_biomes": signals["top_biomes"],
                "notable_specimens": specimens[:8],
                "is_monster": race.lower() not in CIVILIZED_RACES,
                "flavor": FLB.compute_categories(str(next_id), signals),
            }
            next_id += 1

    # =====================================================================
    # WRITE
    # =====================================================================
    def write(self):
        os.makedirs(self.parsed_dir, exist_ok=True)

        # attach event id lists to each entity for the detail pages
        for i, f in self.figures.items():
            f["event_ids"] = self.hf_events.get(i, [])
        for i, s in self.sites.items():
            s["event_ids"] = [e for e in self.site_events.get(i, [])
                              if not isinstance(e, tuple)]
            s["collection_ids"] = [e[1] for e in self.site_events.get(i, [])
                                   if isinstance(e, tuple)]
        for i, e in self.entities.items():
            e["event_ids"] = self.ent_events.get(i, [])
        for i, a in self.artifacts.items():
            a["event_ids"] = self.art_events.get(i, [])

        # relationships per figure. DF emits the same pair flipping between
        # e.g. lover / former_lover many times.  Collapse to the FINAL state
        # per (figure, other person): keep the entry with the highest year.
        rel_latest = defaultdict(dict)   # hf -> {other_hf: (year, rel)}
        for r in self.relationships:
            yr = r["year"] if r["year"] is not None else -1
            for a, b in ((r["src"], r["tgt"]), (r["tgt"], r["src"])):
                cur = rel_latest[a].get(b)
                if cur is None or yr >= cur[0]:
                    rel_latest[a][b] = (yr, r["rel"])
        for i, f in self.figures.items():
            if i in rel_latest:
                rels = []
                for other, (yr, rel) in rel_latest[i].items():
                    rels.append({"hf": other, "rel": rel,
                                 "year": (yr if yr != -1 else None)})
                # family/spouse first, then the rest, alphabetical by rel
                order = {"spouse": 0, "child": 1, "parent": 2, "sibling": 3,
                         "grandparent": 4, "deity": 5, "master": 6, "apprentice": 7}
                rels.sort(key=lambda r: (order.get((r["rel"] or "").replace("former_", ""), 9),
                                         r["rel"] or ""))
                f["relationships"] = rels

        self.compute_hf_flavor()
        self.compute_bestiary()
        _dump(self.parsed_dir, "figures.json", self.figures)
        _dump(self.parsed_dir, "bestiary.json", self.bestiary)
        _dump(self.parsed_dir, "sites.json", self.sites)
        _dump(self.parsed_dir, "artifacts.json", self.artifacts)
        _dump(self.parsed_dir, "entities.json", self.entities)
        _dump(self.parsed_dir, "regions.json", self.regions)
        _dump(self.parsed_dir, "underground_regions.json", self.uregions)
        _dump(self.parsed_dir, "written.json", self.written)
        _dump(self.parsed_dir, "identities.json", self.identities)
        _dump(self.parsed_dir, "creatures.json", self.creatures)
        _dump(self.parsed_dir, "landmasses.json", self.landmasses)
        _dump(self.parsed_dir, "peaks.json", self.peaks)
        _dump(self.parsed_dir, "constructions.json", self.constructions)
        _dump(self.parsed_dir, "events.json", self.rendered_events)
        _dump(self.parsed_dir, "collections.json", self.rendered_collections)
        _dump(self.parsed_dir, "year_stats.json", self.year_stats)

        self._write_search_index()
        self._write_meta()

    def _write_search_index(self):
        idx = []
        for i, f in self.figures.items():
            if f.get("name"):
                idx.append({"t": "hf", "id": i, "n": f["name"],
                            "sub": f.get("race"), "notable": f.get("notable", False)})
        for i, s in self.sites.items():
            if s.get("name"):
                idx.append({"t": "site", "id": i, "n": s["name"],
                            "sub": s.get("type"), "notable": True})
        for i, a in self.artifacts.items():
            if a.get("name"):
                idx.append({"t": "artifact", "id": i, "n": a["name"],
                            "sub": a.get("item_type"), "notable": a.get("notable", False)})
        for i, e in self.entities.items():
            if e.get("name"):
                idx.append({"t": "ent", "id": i, "n": e["name"],
                            "sub": e.get("type"), "notable": e.get("notable", False)})
        for i, w in self.written.items():
            if w.get("title"):
                idx.append({"t": "wc", "id": i, "n": w["title"],
                            "sub": w.get("form"), "notable": True})
        for i, r in self.regions.items():
            if r.get("name"):
                idx.append({"t": "region", "id": i, "n": r["name"],
                            "sub": r.get("type"), "notable": False})
        for i, b in self.bestiary.items():
            idx.append({"t": "creature", "id": i, "n": b["race"].title(),
                        "sub": f"{b['population_named']} recorded", "notable": True})
        _dump(self.parsed_dir, "search_index.json", idx)

    def _write_meta(self):
        # census: population by race (living figures), counts, era, etc.
        race_counts = defaultdict(int)
        living = 0
        for f in self.figures.values():
            if f.get("death_year") in (None, -1):
                living += 1
            if f.get("race"):
                race_counts[f["race"]] += 1

        site_type_counts = defaultdict(int)
        for s in self.sites.values():
            if s.get("type"):
                site_type_counts[s["type"]] += 1

        ent_type_counts = defaultdict(int)
        for e in self.entities.values():
            if e.get("notable") and e.get("type"):
                ent_type_counts[e["type"]] += 1

        coll_type_counts = defaultdict(int)
        for c in self.collections.values():
            if c.get("type"):
                coll_type_counts[c["type"]] += 1

        written_form_counts = defaultdict(int)
        for w in self.written.values():
            if w.get("form"):
                written_form_counts[w["form"]] += 1

        # year span from events
        years = [e.get("year") for e in self.events.values()
                 if isinstance(e.get("year"), int)]
        year_min = min(years) if years else None
        year_max = max(years) if years else None

        meta = {
            "name": self.name,
            "world_name": self.world_name or self.name,
            "world_altname": self.world_altname,
            "eras": self.eras,
            "year_min": year_min,
            "year_max": year_max,
            "counts": {
                "figures": len(self.figures),
                "figures_named": sum(1 for f in self.figures.values() if f.get("name")),
                "figures_notable": sum(1 for f in self.figures.values() if f.get("notable")),
                "figures_living": living,
                "sites": len(self.sites),
                "artifacts": len(self.artifacts),
                "artifacts_notable": sum(1 for a in self.artifacts.values() if a.get("notable")),
                "entities": len(self.entities),
                "entities_notable": sum(1 for e in self.entities.values() if e.get("notable")),
                "written": len(self.written),
                "events": len(self.events),
                "collections": len(self.collections),
                "regions": len(self.regions),
                "identities": len(self.identities),
                "bestiary": len(self.bestiary),
            },
            "census": {
                "by_race": dict(sorted(race_counts.items(), key=lambda kv: -kv[1])),
                "site_types": dict(sorted(site_type_counts.items(), key=lambda kv: -kv[1])),
                "entity_types": dict(sorted(ent_type_counts.items(), key=lambda kv: -kv[1])),
                "collection_types": dict(sorted(coll_type_counts.items(), key=lambda kv: -kv[1])),
                "written_forms": dict(sorted(written_form_counts.items(), key=lambda kv: -kv[1])),
            },
            "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _dump(self.parsed_dir, "meta.json", meta)

    # =====================================================================
    def run(self, base=None, plus=None):
        os.makedirs(self.parsed_dir, exist_ok=True)
        if base is None and plus is None:
            base, plus = self.find_xml()
        if not base and not plus:
            _fail(f"no legends XML found in {self.raw_dir}")
            return False
        t0 = time.time()
        if base:
            self.parse_base(base)
        if plus:
            self.parse_plus(plus)
        _step("Merging & resolving races…")
        self.resolve_races()
        _step("Cross-referencing events & rendering…")
        self.crossref_and_render()
        self.derive_notability()
        _step("Rendering world map…")
        self.compute_world_map()
        self.compute_year_stats()
        _step("Writing JSON…")
        self.write()
        _ok(f"Imported '{self.name}' in {time.time()-t0:.1f}s "
            f"({len(self.figures):,} figures, {len(self.events):,} events)")
        return True


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def prettify_or_type(t):
    return (t or "an event").replace("_", " ")


def _collection_cat(t):
    t = (t or "").lower()
    if t in ("war", "battle", "site conquered", "duel", "raid"):
        return ER.CAT_COMBAT if t in ("battle", "duel") else ER.CAT_POLITICS
    if t in ("beast attack",):
        return ER.CAT_COMBAT
    if t in ("abduction", "theft", "persecution"):
        return ER.CAT_CRIME
    if t in ("ceremony", "procession", "performance", "competition", "occasion", "journey"):
        return ER.CAT_MISC
    if t in ("entity overthrown",):
        return ER.CAT_POLITICS
    return ER.CAT_MISC


def _mb(path):
    return f"{os.path.getsize(path)/1024/1024:.0f} MB"


def _dump(folder, name, obj):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))


def is_parsed(world_dir):
    meta = os.path.join(world_dir, "parsed", "meta.json")
    return os.path.exists(meta)


def discover_worlds():
    if not os.path.isdir(WORLDS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(WORLDS_DIR)):
        wd = os.path.join(WORLDS_DIR, name)
        if not os.path.isdir(wd):
            continue
        has_raw = os.path.isdir(os.path.join(wd, "raw"))
        has_parsed = os.path.exists(os.path.join(wd, "parsed", "meta.json"))
        if has_raw or has_parsed:
            out.append(wd)
    return out


def main(argv):
    _enable_windows_ansi()
    force = "--force" in argv
    recolor = "--recolor" in argv
    args = [a for a in argv if not a.startswith("--")]

    _banner()

    if args:
        targets = [os.path.abspath(a) for a in args]
    else:
        targets = discover_worlds()

    if not targets:
        print(f"{C.GREY}No worlds found. Create worlds/<name>/raw/ and drop your two "
              f"legends XML files in, then run again.{C.RESET}")
        return

    if recolor:
        print(f"{C.BOLD}Recoloring from cached grids (no XML re-parse){C.RESET}")
        for wd in targets:
            recolor_world(wd)
        return

    for wd in targets:
        name = os.path.basename(wd)
        raw_dir = os.path.join(wd, "raw")

        if is_parsed(wd) and not force and not args:
            _ok(f"{name} already imported {C.GREY}(skip; use --force to redo){C.RESET}")
            continue

        pairs, orphan_base, orphan_plus, ambiguous = discover_xml_pairs(raw_dir)

        if not pairs and not orphan_base and not orphan_plus:
            continue  # empty raw/. Nothing to say, not an error

        if orphan_base:
            for p in orphan_base:
                _warn(f"{name}: '{os.path.basename(p)}' has no matching Plus file. Skipped")
        if orphan_plus:
            for p in orphan_plus:
                _warn(f"{name}: '{os.path.basename(p)}' has no matching base file. Skipped")
        if ambiguous:
            for p in ambiguous:
                _warn(f"{name}: '{os.path.basename(p)}' matches more than one possible "
                      f"base file. Too ambiguous to guess, skipped")

        if len(pairs) > 1:
            _warn(f"{name}: found {len(pairs)} candidate pairs in one raw/ folder, "
                  f"a world should only have one. Refusing to guess which is correct.")
            for b, p in pairs:
                print(f"    {C.GREY}- {os.path.basename(b)}  +  {os.path.basename(p)}{C.RESET}")
            continue

        if not pairs:
            continue

        base_path, plus_path = pairs[0]
        ok, report = validate_pair(base_path, plus_path)
        print_import_preview(name, base_path, plus_path, ok, report)
        if not ok:
            continue

        print(f"{C.BOLD}=== Importing {name} ==={C.RESET}")
        try:
            WorldImporter(wd).run(base=base_path, plus=plus_path)
        except Exception as ex:
            import traceback
            _fail(f"FAILED: {ex}")
            traceback.print_exc()


if __name__ == "__main__":
    main(sys.argv[1:])
