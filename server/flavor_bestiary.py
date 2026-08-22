"""
flavor_bestiary.py  --  deterministic flavor-text engine for the Bestiary
===========================================================================

Same architecture as flavor_hf.py (deterministic hash-seeded picks, variable
sentence length, true-random reroll support) but keyed by RACE SLUG (a
string) instead of a numeric figure id, since a Bestiary entry is one page
per species, not per individual.

Two categories lead with REAL data before the generated flavor kicks in:
  - Overview: real count of named individuals in the historical record
  - Habitat & Range: real biome types, derived from where this race's named
    individuals actually had site associations in the legends data
Notable Specimens is entirely real (links to actual named historical
figures of this race). The word bank only supplies a one-line flavor lead-in.
"""
import hashlib
import random
import os
import json

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bestiary_wordbanks.json")
with open(_DATA_PATH, encoding="utf-8") as _f:
    BANKS = json.load(_f)


def _rng(seed_key, salt):
    seed = int(hashlib.md5(f"{seed_key}|{salt}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _pick(seed_key, category, n=2, salt="", rng=None):
    pool = BANKS.get(category, [])
    if not pool:
        return []
    r = rng if rng is not None else _rng(seed_key, category + salt)
    n = min(n, len(pool))
    return r.sample(pool, n)


def _join(words):
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


_LEN_POPULATION = [1, 2, 3, 4, 5, 6, 7, 8]
_LEN_WEIGHTS =    [38, 24, 15, 9, 6, 4, 2, 2]

_CONNECTORS = [
    "It's also described as {j}.",
    "Others recall {j}.",
    "There's talk of {j} as well.",
    "Some point to {j}.",
    "Further accounts mention {j}.",
    "Not to be overlooked: {j}.",
    "Accounts also mention {j}.",
    "Stories add {j} to the picture.",
    "Years later, it's still remembered for {j}.",
    "There's more: {j}.",
    "It's remembered too for {j}.",
    "Some link it to {j}.",
]


def _weighted_len(seed_key, category, rng=None):
    r = rng if rng is not None else _rng(seed_key, category + "_len")
    return r.choices(_LEN_POPULATION, weights=_LEN_WEIGHTS, k=1)[0]


def _generate(seed_key, category_key, leadin_template, rng=None):
    n = _weighted_len(seed_key, category_key, rng=rng)
    first_words = _pick(seed_key, category_key, 2, salt="s0", rng=rng)
    sentences = [leadin_template.format(j=_join(first_words))]
    last_conn = None
    for k in range(1, n):
        words = _pick(seed_key, category_key, 2, salt=f"s{k}", rng=rng)
        r = rng if rng is not None else _rng(seed_key, category_key + f"_conn{k}")
        choices = [c for c in _CONNECTORS if c != last_conn] or _CONNECTORS
        connector = r.choice(choices)
        last_conn = connector
        sentences.append(connector.format(j=_join(words)))
    return " ".join(sentences)


_LEADINS = {
    "OVERVIEW":           "Known for {j}.",
    "APPEARANCE":         "Described as {j}.",
    "HABITAT_RANGE":      "Typically found in terrain best described as {j}.",
    "DIET":               "Feeds primarily by way of {j}.",
    "TEMPERAMENT":        "Behaviorally, {j}.",
    "HUNTERS_NOTES":      "Those who've hunted it describe {j}.",
    "FOLK_BELIEFS":       "Local folklore holds it as {j}.",
    "NOTABLE_SPECIMENS":  "Individual specimens have been remembered for {j}.",
    "CUISINE_TRADE":      "In trade and kitchen alike, known for {j}.",
    "TRIVIA":             "Worth noting: {j}.",
}

CATEGORY_LABELS = {
    "OVERVIEW": "Overview", "APPEARANCE": "Appearance", "HABITAT_RANGE": "Habitat & Range",
    "DIET": "Diet", "TEMPERAMENT": "Temperament", "HUNTERS_NOTES": "Hunter's Notes",
    "FOLK_BELIEFS": "Folk Beliefs", "NOTABLE_SPECIMENS": "Notable Specimens",
    "CUISINE_TRADE": "In Cuisine & Trade", "TRIVIA": "Trivia",
}

# order matters, this is the page's reading order
CATEGORY_ORDER = ["OVERVIEW", "APPEARANCE", "HABITAT_RANGE", "DIET", "TEMPERAMENT",
                  "HUNTERS_NOTES", "NOTABLE_SPECIMENS", "FOLK_BELIEFS", "CUISINE_TRADE", "TRIVIA"]


def _plural_ind(n):
    return "individual" if n == 1 else "individuals"


def compute_categories(slug, signals):
    out = []
    for key in CATEGORY_ORDER:
        if key == "NOTABLE_SPECIMENS" and not signals.get("has_specimens"):
            continue  # conditional. Only if real named specimens exist

        text = _generate(slug, key, _LEADINS[key])

        if key == "OVERVIEW" and signals.get("population_named"):
            n = signals["population_named"]
            real = f"{n} named {_plural_ind(n)} of this kind appear in the historical record."
            text = real + " " + text
        elif key == "HABITAT_RANGE" and signals.get("top_biomes"):
            biomes = _join([b.lower() for b in signals["top_biomes"]])
            real = f"Historically sighted most often in {biomes} terrain."
            text = real + " " + text

        out.append({"key": key.lower(), "label": CATEGORY_LABELS[key], "text": text})
    return out


# ---------------------------------------------------------------------------
# Manual reroll support (same pattern as flavor_hf.py)
# ---------------------------------------------------------------------------
def regenerate_text(key, population_named=None, top_biomes=None):
    key_u = key.upper()
    leadin = _LEADINS.get(key_u)
    if leadin is None:
        return None
    rng = random.Random()
    text = _generate(None, key_u, leadin, rng=rng)
    if key_u == "OVERVIEW" and population_named:
        n = population_named
        text = f"{n} named {_plural_ind(n)} of this kind appear in the historical record. " + text
    elif key_u == "HABITAT_RANGE" and top_biomes:
        biomes = _join([b.lower() for b in top_biomes])
        text = f"Historically sighted most often in {biomes} terrain. " + text
    return text
