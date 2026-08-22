"""
flavor_hf.py  --  deterministic flavor-text engine for historical figures
===========================================================================

Every word bank came from the person's own curated lists (hfWordbank2.txt +
hfpatch.txt). This module turns those flat word pools into short, readable
blurbs, picked DETERMINISTICALLY per figure so the same person always shows
the same text on every visit, forever, with zero runtime cost. The pick
happens once at import time and is baked into figures.json.

No randomness at request time. No LLM calls. No network. Just a stable hash
seeding Python's random module, exactly like the biome map used a lookup
table instead of guessing colors.

This content is deliberately not sourced from the simulated legends data.
It is invented local color, same visual weight as any other section, with
no disclaimers. Where real data exists, the parser prefers it; this engine
only fills in categories DF has no data for at all.
"""
import hashlib
import random
import os
import json

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hf_wordbanks.json")
with open(_DATA_PATH, encoding="utf-8") as _f:
    BANKS = json.load(_f)


def _rng(entity_id, salt):
    seed = int(hashlib.md5(f"{entity_id}|{salt}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _pick(entity_id, category, n=2, salt="", rng=None):
    pool = BANKS.get(category, [])
    if not pool:
        return []
    r = rng if rng is not None else _rng(entity_id, category + salt)
    n = min(n, len(pool))
    return r.sample(pool, n)


def _join(words):
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


# ---------------------------------------------------------------------------
# Variable-length prose engine.
#
# Every category gets ONE opening sentence (topic-specific lead-in), then a
# deterministically-chosen number of CONTINUATION sentences drawn from a
# shared connector pool + fresh word picks from the same bank. Length is
# weighted toward short (most sections stay brief) with an occasional long
# outlier, "faking the illusion of depth" in one area per page, same way a
# real wiki has a few sections that run long and most that don't.
#
# When `rng` is supplied (the manual "reroll" button), generation uses TRUE
# randomness instead of the deterministic fid-seeded hash. The result then
# gets saved verbatim as a permanent override, so determinism resumes from
# that point on (same as a manual edit).
# ---------------------------------------------------------------------------
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

_DEATH_LEN_POPULATION = [1, 2, 3, 4]
_DEATH_LEN_WEIGHTS =    [55, 25, 12, 8]
_DEATH_CONNECTORS = [
    "Some accounts add: it happened {j}.",
    "Other tellings place it {j}.",
    "It's also said to have unfolded {j}.",
    "Years later, other accounts still recalled {j}.",
    "Some tellings connect it to {j}.",
]


def _weighted_len(fid, category, population=_LEN_POPULATION, weights=_LEN_WEIGHTS, rng=None):
    r = rng if rng is not None else _rng(fid, category + "_len")
    return r.choices(population, weights=weights, k=1)[0]


def _generate(fid, category_key, leadin_template, bank_name=None, rng=None):
    """Build a variable-length blurb: one lead-in sentence + N-1 connector
    sentences reusing the same bank with fresh, non-repeating word picks.
    fid may be None when rng is supplied (true-random reroll path)."""
    bank_name = bank_name or category_key
    n = _weighted_len(fid, category_key, rng=rng)
    first_words = _pick(fid, bank_name, 2, salt="s0", rng=rng)
    sentences = [leadin_template.format(j=_join(first_words))]
    last_conn = None
    for k in range(1, n):
        words = _pick(fid, bank_name, 2, salt=f"s{k}", rng=rng)
        r = rng if rng is not None else _rng(fid, category_key + f"_conn{k}")
        choices = [c for c in _CONNECTORS if c != last_conn] or _CONNECTORS
        connector = r.choice(choices)
        last_conn = connector
        sentences.append(connector.format(j=_join(words)))
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Lead-in templates. One topic-establishing sentence per category. {j} is a
# comma-joined phrase from that category's word bank.
# ---------------------------------------------------------------------------
_LEADINS = {
    "OVERVIEW":       "Remembered chiefly for a life marked by {j}.",
    "ORIGINS":        "Their origins were {j}.",
    "EARLY_LIFE":     "Early life was shaped by {j}.",
    "FAMILY":         "Family life was {j}.",
    "APPRENTICESHIP": "Their training was {j}.",
    "WANDERINGS":     "Known for wanderings that were {j}.",
    "TRAVELS":        "Their travels were {j}.",
    "MILITARY_CAREER":"A military record marked by being {j}.",
    "POLITICAL_CAREER":"Politically, remembered as {j}.",
    "RELIGIOUS_BELIEF":"Their faith was {j}.",
    "DISCOVERIES":    "Credited with discoveries that were {j}.",
    "CREATIONS":      "What they made tended to be {j}.",
    "RELATIONSHIPS":  "Relationships were generally {j}.",
    "RIVALRIES_AND_ALLIES":"Rivalries and alliances alike were {j}.",
    "PERSONALITY":    "Known to be {j}.",
    "BELIEFS":        "Held convictions that were {j}.",
    "REPUTATION":     "Widely regarded as {j}.",
    "LEADERSHIP":     "As a figure of authority: {j}.",
    "MAJOR_DEEDS":    "Their major deeds were {j}.",
    "TURNING_POINTS": "A defining turning point was {j}.",
    "CAPTIVITY":      "A period of captivity best described as {j}.",
    "APPEARANCE":     "Remembered as {j}.",
    "SKILLS":         "Skilled in ways best described as {j}.",
    "HOBBIES":        "Known to spend spare time on {j}.",
    "PERSONAL_ITEMS": "Rarely seen without {j}.",
    "DREAMS":         "Privately said to dream of {j}.",
    "SECRETS":        "Kept a secret, something like {j}.",
    "WEALTH":         "Financially, known for {j}.",
    "DECLINE":        "Later years brought {j}.",
}


_VIOLENT_DEATH_WORDS = ("battle", "combat", "siege", "duel", "execution",
                        "assassination", "murder", "war ", " war")


def _death_manner_pool(child_safe):
    pool = BANKS.get("DEATH_MANNER", [])
    if not child_safe:
        return pool
    return [w for w in pool if not any(k in w for k in _VIOLENT_DEATH_WORDS)] or pool


def _tmpl_death(fid, alive, child_safe, rng=None):
    if alive:
        if rng is not None:
            manner = rng.choice(BANKS.get('DEATH_MANNER', ['uncertain']))
        else:
            manner = _pick(fid, 'DEATH_MANNER', 1, salt="alive")[0] if BANKS.get('DEATH_MANNER') else "uncertain"
        return f"Still living, though already spoken of with a sense of {manner}."
    pool = _death_manner_pool(child_safe)
    if rng is not None:
        manner = rng.choice(pool) if pool else "unknown causes"
        scene = rng.choice(BANKS.get('DEATH_SCENE', [''])) if BANKS.get('DEATH_SCENE') else ""
    else:
        r = _rng(fid, "DEATH_MANNER")
        manner = _join(r.sample(pool, min(1, len(pool)))) if pool else "unknown causes"
        scene = _join(_pick(fid, 'DEATH_SCENE', 1, salt="s0"))
    n = _weighted_len(fid, "DEATH", _DEATH_LEN_POPULATION, _DEATH_LEN_WEIGHTS, rng=rng)
    sentences = [f"Died {manner}, {scene}."]
    for k in range(1, n):
        if rng is not None:
            words_j = rng.choice(BANKS.get('DEATH_SCENE', [''])) if BANKS.get('DEATH_SCENE') else ""
            connector = rng.choice(_DEATH_CONNECTORS)
        else:
            words_j = _join(_pick(fid, 'DEATH_SCENE', 1, salt=f"s{k}"))
            r2 = _rng(fid, "DEATH" + f"_conn{k}")
            connector = r2.choice(_DEATH_CONNECTORS)
        sentences.append(connector.format(j=words_j))
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Relevance rules
# ---------------------------------------------------------------------------
def _t_family(s):      return s["has_family_rel"]
def _t_apprentice(s):  return s["has_skills"]
def _t_wander(s):      return s["n_site_links"] >= 2
def _t_military(s):    return s["has_combat"]
def _t_political(s):   return s["has_politics"] or s["assoc_leader"]
def _t_religion(s):    return s["has_spheres"] or s["has_religion_event"]
def _t_discoveries(s): return s["n_events"] >= 5
def _t_creations(s):   return s["has_creation"]
def _t_relations(s):   return s["has_any_rel"]
def _t_rivalries(s):   return s["has_any_rel"] or s["has_enemy_rel"]
def _t_leadership(s):  return s["assoc_leader"] or s["has_politics"]
def _t_deeds(s):       return s["n_events"] >= 3
def _t_captivity(s):   return s["has_crime"]

CATEGORIES = [
    ("OVERVIEW",      "Overview",            True,  None),
    ("ORIGINS",       "Origins",             True,  None),
    ("EARLY_LIFE",    "Early Life",          True,  None),
    ("FAMILY",        "Family",              False, _t_family),
    ("APPRENTICESHIP","Apprenticeship",      False, _t_apprentice),
    ("WANDERINGS",    "Wanderings",          False, _t_wander),
    ("TRAVELS",       "Travels",             False, _t_wander),
    ("MILITARY_CAREER","War Record",         False, _t_military),
    ("POLITICAL_CAREER","Political Career",  False, _t_political),
    ("RELIGIOUS_BELIEF","Faith & Devotion",  False, _t_religion),
    ("DISCOVERIES",   "Discoveries",         False, _t_discoveries),
    ("CREATIONS",     "Creations",           False, _t_creations),
    ("RELATIONSHIPS", "Relationships",       False, _t_relations),
    ("RIVALRIES_AND_ALLIES","Rivalries & Allies", False, _t_rivalries),
    ("PERSONALITY",   "Personality",         True,  None),
    ("BELIEFS",       "Beliefs",             True,  None),
    ("REPUTATION",    "Reputation",          True,  None),
    ("LEADERSHIP",    "Leadership",          False, _t_leadership),
    ("MAJOR_DEEDS",   "Major Deeds",         False, _t_deeds),
    ("TURNING_POINTS","Turning Points",      False, _t_deeds),
    ("CAPTIVITY",     "Captivity",           False, _t_captivity),
    ("APPEARANCE",    "Appearance",          True,  None),
    ("SKILLS",        "Skills",              True,  None),
    ("HOBBIES",       "Hobbies",             True,  None),
    ("PERSONAL_ITEMS","Personal Items",      True,  None),
    ("DREAMS",        "Dreams",              True,  None),
    ("SECRETS",       "Secrets",             True,  None),
    ("WEALTH",        "Wealth",              True,  None),
    ("DECLINE",       "Later Years",         True,  None),
]

# ---------------------------------------------------------------------------
# Prohibitions. Some categories don't make sense for some figures no matter
# how "forced" they normally are. Age gates stop children from getting
# adult-coded flavor (a war record, a political career); monster exclusions
# stop solitary beasts from getting institutional flavor (a bronze colossus
# doesn't hold military rank). This runs BEFORE forced/trigger checks, so it
# overrides even normally-always-shown categories.
# ---------------------------------------------------------------------------
AGE_MIN = {
    "MILITARY_CAREER": 14,
    "POLITICAL_CAREER": 16,
    "LEADERSHIP": 16,
    "WEALTH": 12,
    "DISCOVERIES": 12,
    "APPRENTICESHIP": 6,
}
MONSTER_EXCLUDED = {"MILITARY_CAREER", "POLITICAL_CAREER", "LEADERSHIP", "APPRENTICESHIP"}


def _prohibited(key, signals):
    if signals.get("is_monster") and key in MONSTER_EXCLUDED:
        return True
    min_age = AGE_MIN.get(key)
    age = signals.get("age")
    if min_age is not None and age is not None and age < min_age:
        return True
    return False


def compute_categories(fid, signals):
    out = []
    for key, label, forced, trigger in CATEGORIES:
        if _prohibited(key, signals):
            continue
        if not forced and not trigger(signals):
            continue
        text = _generate(fid, key, _LEADINS[key])
        out.append({"key": key.lower(), "label": label, "text": text})

    age = signals.get("age")
    child_safe = age is not None and age < 10
    out.append({"key": "death", "label": "Death" if not signals["is_alive"] else "Status",
               "text": _tmpl_death(fid, signals["is_alive"], child_safe)})
    return out


# ---------------------------------------------------------------------------
# Manual reroll (the "[reroll]" button). True-random, not fid-deterministic,
# since the caller saves the result as a permanent override afterward.
# ---------------------------------------------------------------------------
_CATEGORY_META = {key: (label, _LEADINS[key]) for key, label, _, _ in CATEGORIES}


def regenerate_text(key, is_alive=None, age=None):
    key_u = key.upper()
    rng = random.Random()  # unseeded = true randomness, not reproducible on purpose
    if key_u == "DEATH":
        child_safe = age is not None and age < 10
        return _tmpl_death(None, bool(is_alive), child_safe, rng=rng)
    meta = _CATEGORY_META.get(key_u)
    if meta is None:
        return None
    label, leadin = meta
    return _generate(None, key_u, leadin, rng=rng)


# ---------------------------------------------------------------------------
# Epithets. A rule-based classifier reading REAL computed signals, not word
# banks. Same figure -> same rule -> same epithet forever. Priority-ordered;
# first matching rule wins. A small option list per rule (chosen
# deterministically) keeps repeat matches from feeling copy-pasted.
# ---------------------------------------------------------------------------
_EPITHET_OPTIONS = {
    "monster_slayer":  ["The Ravager", "The Devourer", "The Bloodletter", "The Terror"],
    "self_made":       ["The Self-Made", "From Nothing", "The Upstart", "Risen from the Ranks"],
    "fallen_leader":   ["The Fallen", "Who Fell From Power", "The Deposed"],
    "artificer":       ["The Artificer", "The Maker", "The Craftsman"],
    "war_hero":        ["The Undefeated", "The War-Forged", "The Blooded"],
    "long_reign":      ["The Enduring", "The Elder", "The Ever-Present"],
    "slain":           ["The Slain", "Who Was Struck Down", "The Betrayed"],
    "prolific":        ["Of Many Deeds", "The Storied", "Whose Name Spread Far"],
    "obscure":         [],  # no epithet. Most figures, and that's fine
}

def compute_epithet(fid, signals):
    if signals["is_monster"] and signals["has_combat"] and signals["n_events"] >= 4:
        rule = "monster_slayer"
    elif signals["assoc_leader"] and signals["was_commoner_origin"]:
        rule = "self_made"
    elif signals["assoc_leader"] and not signals["is_alive"] and signals["has_politics"]:
        rule = "fallen_leader"
    elif signals["has_creation"] and signals["n_events"] >= 3 and not signals["has_combat"]:
        rule = "artificer"
    elif signals["has_combat"] and signals["n_events"] >= 8:
        rule = "war_hero"
    elif signals["is_alive"] and signals["n_events"] >= 10:
        rule = "long_reign"
    elif not signals["is_alive"] and signals["died_violently"]:
        rule = "slain"
    elif signals["n_events"] >= 15:
        rule = "prolific"
    else:
        rule = "obscure"

    opts = _EPITHET_OPTIONS[rule]
    if not opts:
        return None
    rng = _rng(fid, "epithet")
    return rng.choice(opts)
