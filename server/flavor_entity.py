"""
flavor_entity.py  --  wordbank prose for sites, civilizations, artifacts,
                      written works and regions
=============================================================================

Same machinery as flavor_hf: a bank of short fragments per category, stitched
into sentences with a lead-in and rotating connectors. Deterministic per
entity id, so a given site reads the same every time you visit it. The text
is part of that place's identity, not a slot machine.

Sections only appear when the record actually supports them. A site with no
recorded structures shouldn't grow a "Notable Structures" passage out of
nothing, and an artifact with no strange properties shouldn't get a "Powers"
section. That gate is what keeps this honest: the prose is invented, but
whether a topic is discussed at all follows the real data.
"""
import hashlib
import json
import os
import random

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                    "entity_wordbanks.json")

try:
    with open(DATA, encoding="utf-8") as fh:
        BANKS = json.load(fh)
except Exception:
    BANKS = {}


# ---------------------------------------------------------------------------
# Assembly (mirrors flavor_hf so the two read alike)
# ---------------------------------------------------------------------------
_CONNECTORS = [
    "Accounts also mention {j}.",
    "There is talk of {j} as well.",
    "Some point to {j}.",
    "Others recall {j}.",
    "It is also described as {j}.",
    "The record notes {j}.",
    "Travellers speak of {j}.",
    "It is remembered too for {j}.",
    "Mention is made of {j}.",
    "Years later, it was still remembered for {j}.",
    "There is more: {j}.",
    "Some link it to {j}.",
]

_LEN_WEIGHTS = [(1, 18), (2, 46), (3, 28), (4, 8)]


def _rng(eid, salt):
    h = hashlib.sha256(f"{eid}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _weighted_len(eid, key, rng=None):
    r = rng if rng is not None else _rng(eid, key + "_len")
    total = sum(w for _, w in _LEN_WEIGHTS)
    x = r.randrange(total)
    for n, w in _LEN_WEIGHTS:
        if x < w:
            return n
        x -= w
    return 2


def _pick(eid, bank, n, salt="", rng=None):
    pool = BANKS.get(bank) or []
    if not pool:
        return []
    r = rng if rng is not None else _rng(eid, bank + salt)
    n = min(n, len(pool))
    return r.sample(pool, n)


def _join(words):
    if not words:
        return "little that is certain"
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def _generate(eid, bank, leadin, rng=None):
    n = _weighted_len(eid, bank, rng=rng)
    first = _pick(eid, bank, 2, salt="s0", rng=rng)
    if not first:
        return ""
    out = [leadin.format(j=_join(first))]
    last = None
    for k in range(1, n):
        words = _pick(eid, bank, 2, salt=f"s{k}", rng=rng)
        if not words:
            break
        r = rng if rng is not None else _rng(eid, bank + f"_c{k}")
        choices = [c for c in _CONNECTORS if c != last] or _CONNECTORS
        conn = r.choice(choices)
        last = conn
        out.append(conn.format(j=_join(words)))
    return " ".join(out)


# ---------------------------------------------------------------------------
# Categories.  (bank, key, label, leadin, gate)
# gate(rec) -> bool decides whether the section appears at all.
# ---------------------------------------------------------------------------
def _always(rec):
    return True


def _has(field):
    def g(rec):
        v = rec.get(field)
        return bool(v)
    return g


def _has_any(*fields):
    def g(rec):
        return any(rec.get(f) for f in fields)
    return g


def _events_over(n):
    def g(rec):
        return (rec.get("event_count") or 0) > n
    return g


SITE_CATS = [
    ("SITES_OVERVIEW", "overview", "Overview",
     "The place is {j}.", _always),
    ("SITES_FOUNDING", "founding", "Founding",
     "Its beginnings were {j}.", _always),
    ("SITES_LAYOUT", "layout", "Layout & Architecture",
     "Built as {j}.", _always),
    ("SITES_NOTABLESTRUCTURES", "structures", "Notable Structures",
     "Among its buildings stand {j}.", _has("structures")),
    ("SITES_DEFENCE", "defence", "Defences",
     "Its defences amount to {j}.", _always),
    ("SITES_DAILYLIFE", "dailylife", "Daily Life",
     "Day to day, it is {j}.", _always),
    ("SITES_TRADE", "trade", "Trade & Craft",
     "Its trade runs to {j}.", _always),
    ("SITES_SURROUNDINGS", "surroundings", "Surroundings",
     "The country about it is {j}.", _always),
    ("SITES_CUSTOMS", "customs", "Local Customs",
     "Locally they keep {j}.", _always),
    ("SITES_REPUTATION", "reputation", "Reputation",
     "Elsewhere it is known for {j}.", _events_over(2)),
    ("SITES_TROUBLES", "troubles", "Troubles",
     "It has suffered {j}.", _events_over(4)),
]

CIV_CATS = [
    ("CIV_OVERVIEW", "overview", "Overview",
     "They are {j}.", _always),
    ("CIV_ORIGINS", "origins", "Origins",
     "They began as {j}.", _always),
    ("CIV_TERRITORY", "territory", "Territory",
     "Their holdings are {j}.", _always),
    ("CIV_GOVERNMENT", "government", "Governance",
     "They are governed by {j}.", _always),
    ("CIV_CULTURE", "culture", "Culture",
     "Their manner is {j}.", _always),
    ("CIV_RELIGION", "religion", "Religion",
     "In worship they hold to {j}.", _always),
    ("CIV_WARFARE", "warfare", "Warfare",
     "In war they favour {j}.", _always),
    ("CIV_TRADE", "trade", "Trade",
     "They trade in {j}.", _always),
    ("CIV_RELATIONS", "relations", "Relations",
     "With their neighbours there is {j}.", _always),
    ("CIV_NOTABLES", "notables", "Notable Members",
     "They have produced {j}.", _events_over(2)),
    ("CIV_TRAJECTORY", "trajectory", "Ascent or Decline",
     "Their fortunes run to {j}.", _events_over(3)),
]

ARTIFACT_CATS = [
    ("ARTIFACTS_OVERVIEW", "overview", "Overview",
     "The object is {j}.", _always),
    ("ARTIFACTS_MATERIALS", "materials", "Materials",
     "It is {j}.", _always),
    ("ARTIFACTS_CRAFTSMANSHIP", "craftsmanship", "Craftsmanship",
     "The work shows {j}.", _always),
    ("ARTIFACTS_DECORATION", "decoration", "Decoration",
     "It bears {j}.", _always),
    ("ARTIFACTS_HISTORY", "history", "History",
     "Its passage has been {j}.", _events_over(1)),
    ("ARTIFACTS_POWERS", "powers", "Powers & Properties",
     "It is credited with {j}.", _has_any("is_magical", "spheres")),
    ("ARTIFACTS_WHEREABOUTS", "whereabouts", "Whereabouts",
     "It rests {j}.", _always),
    ("ARTIFACTS_LEGENDS", "legends", "Legends",
     "They tell of {j}.", _events_over(2)),
]

WC_CATS = [
    ("WRITTENWORKS_OVERVIEW", "overview", "Overview",
     "The work is {j}.", _always),
    ("WRITTENWORKS_CONTENTS", "contents", "Contents",
     "It sets down {j}.", _always),
    ("WRITTENWORKS_AUTHORSHIP", "authorship", "Authorship",
     "It was written under {j}.", _always),
    ("WRITTENWORKS_STYLE", "style", "Style",
     "It reads as {j}.", _always),
    ("WRITTENWORKS_RECEPTION", "reception", "Reception",
     "It was met with {j}.", _always),
    ("WRITTENWORKS_COPIES", "copies", "Copies & Fate",
     "Of its copies there is {j}.", _always),
    ("WRITTENWORKS_INFLUENCE", "influence", "Influence",
     "Its mark shows in {j}.", _events_over(0)),
]

REGION_CATS = [
    ("REGION_OVERVIEW", "overview", "Overview",
     "The country is {j}.", _always),
    ("REGION_TERRAIN", "terrain", "Terrain",
     "The ground is {j}.", _always),
    ("REGION_CLIMATE", "climate", "Climate",
     "Its weather runs to {j}.", _always),
    ("REGION_FLORAFAUNA", "florafauna", "Flora & Fauna",
     "Living there are {j}.", _always),
    ("REGION_RESOURCES", "resources", "Resources",
     "It yields {j}.", _always),
    ("REGION_TRAVEL", "travel", "Travel",
     "Crossing it means {j}.", _always),
    ("REGION_DANGERS", "dangers", "Dangers",
     "The danger here is {j}.", _always),
    ("REGION_LORE", "lore", "Lore",
     "They say of it {j}.", _always),
]

BY_TYPE = {
    "site": SITE_CATS,
    "ent": CIV_CATS,
    "artifact": ARTIFACT_CATS,
    "wc": WC_CATS,
    "region": REGION_CATS,
}


def has_support(etype):
    return etype in BY_TYPE and bool(BANKS)


def compute_categories(etype, eid, rec):
    """Sections for one entity, in order. Empty list if this type isn't
    supported or the banks failed to load."""
    cats = BY_TYPE.get(etype)
    if not cats or not BANKS:
        return []
    out = []
    for bank, key, label, leadin, gate in cats:
        try:
            if not gate(rec):
                continue
        except Exception:
            continue
        text = _generate(eid, bank, leadin)
        if text:
            out.append({"key": key, "label": label, "text": text})
    return out


_META = {}
for _t, _cats in BY_TYPE.items():
    for _bank, _key, _label, _leadin, _ in _cats:
        _META[(_t, _key)] = (_bank, _label, _leadin)


def regenerate_text(etype, key):
    """The [reroll] button. Deliberately unseeded, since the caller stores
    the result as a permanent override."""
    meta = _META.get((etype, key))
    if not meta:
        return None
    bank, _label, leadin = meta
    return _generate(None, bank, leadin, rng=random.Random())
