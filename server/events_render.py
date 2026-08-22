"""
events_render.py
=================
Turns a merged Dwarf Fortress historical_event dict into a list of "tokens".

A token is either:
  - a plain string  -> rendered as text
  - a dict {"t": <kind>, "id": <int>, "name": <str>}  -> rendered as a link
      kind is one of: "hf" (historical figure), "site", "ent" (entity/civ),
                      "artifact", "region", "wc" (written content)

The frontend walks the token list and renders strings as text and dicts as
clickable links.  Rendering happens ONCE at parse time so the server/browser
never has to do it.

Design notes
------------
* legends.xml and legends_plus.xml use DIFFERENT field names for the same
  concept (e.g. slayer_hfid vs slayer_hf).  Every accessor below checks a list
  of aliases so it works whether a given event was enriched by the plus file
  or not.
* Coverage: the ~40 highest-value / highest-frequency event types get bespoke
  sentences.  Everything else falls through to a generic renderer that still
  produces something readable and correctly linked, so no event is ever a dead
  end for navigation.
* Each event is also tagged with a CATEGORY so the UI can foreground the
  narratively interesting events (deaths, battles, creations, relationships)
  and tuck the noisy ones (job changes, routine settling) behind an expander,
  and so the headlines homepage can pull only the good stuff.
"""

# ---------------------------------------------------------------------------
# Categories (used for filtering + headlines weighting)
# ---------------------------------------------------------------------------
CAT_LIFE      = "life"       # birth, death, becoming undead
CAT_COMBAT    = "combat"     # battles, wounds, kills
CAT_CREATION  = "creation"   # artifacts, written works, constructions, masterpieces
CAT_SOCIAL    = "social"     # relationships, reputations, marriages
CAT_CAREER    = "career"     # positions, jobs, membership
CAT_MOVEMENT  = "movement"   # settling, site links, migration
CAT_CRIME     = "crime"      # theft, abduction, conviction, persecution
CAT_RELIGION  = "religion"   # prayer, worship, holy events
CAT_POLITICS  = "politics"   # conquest, overthrow, diplomacy, war
CAT_MISC      = "misc"

# Categories the UI treats as "notable" (shown up-front, eligible for headlines)
NOTABLE_CATEGORIES = {CAT_LIFE, CAT_COMBAT, CAT_CREATION, CAT_SOCIAL,
                      CAT_POLITICS, CAT_CRIME}


def _first(ev, *keys):
    """Return the first present, non-empty, non -1 value among keys."""
    for k in keys:
        if k in ev:
            v = ev[k]
            if v is None:
                continue
            s = str(v)
            if s == "" or s == "-1":
                continue
            return v
    return None


def _int(ev, *keys):
    v = _first(ev, *keys)
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# The resolver is supplied by the parser; it turns ids into display names.
# ---------------------------------------------------------------------------
class Resolver:
    def __init__(self, hf_names, site_names, ent_names, artifact_names,
                 region_names, wc_titles):
        self.hf_names = hf_names
        self.site_names = site_names
        self.ent_names = ent_names
        self.artifact_names = artifact_names
        self.region_names = region_names
        self.wc_titles = wc_titles

    def _tok(self, kind, table, id_):
        if id_ is None or (isinstance(id_, int) and id_ < 0):
            return None
        name = table.get(id_)
        if name is None:
            return None            # unknown id -> no link, caller omits it
        return {"t": kind, "id": id_, "name": name}

    def hf(self, id_):       return self._tok("hf", self.hf_names, id_)
    def site(self, id_):     return self._tok("site", self.site_names, id_)
    def ent(self, id_):      return self._tok("ent", self.ent_names, id_)
    def artifact(self, id_): return self._tok("artifact", self.artifact_names, id_)
    def region(self, id_):   return self._tok("region", self.region_names, id_)
    def wc(self, id_):       return self._tok("wc", self.wc_titles, id_)


# ---------------------------------------------------------------------------
# Helpers for building token lists
# ---------------------------------------------------------------------------
def _compact(tokens):
    """Merge adjacent strings; drop Nones."""
    out = []
    for t in tokens:
        if t is None:
            continue
        if isinstance(t, str) and out and isinstance(out[-1], str):
            out[-1] += t
        else:
            out.append(t)
    return out


def _hf_or_someone(R, ev, *keys):
    tok = R.hf(_int(ev, *keys))
    return tok if tok is not None else "someone"


# ---------------------------------------------------------------------------
# Per-type handlers.  Each returns (tokens, category).
# `y` is the year string already computed by the caller.
# ---------------------------------------------------------------------------
def _h_hf_died(R, ev):
    victim = R.hf(_int(ev, "hfid", "victim_hf", "victim"))
    slayer = R.hf(_int(ev, "slayer_hfid", "slayer_hf"))
    cause = _first(ev, "cause", "death_cause")
    toks = [victim or "a historical figure", " died"]
    if cause and str(cause) not in ("none", "old_age"):
        pretty = str(cause).replace("_", " ")
        toks += [f" ({pretty})"]
    elif cause == "old_age":
        toks += [" of old age"]
    if slayer is not None:
        toks += [", slain by ", slayer]
    toks += ["."]
    return toks, CAT_LIFE


def _h_battle(R, ev):
    a = R.hf(_int(ev, "group_1_hfid", "attacker_hfid"))
    b = R.hf(_int(ev, "group_2_hfid", "defender_hfid"))
    site = R.site(_int(ev, "site_id", "site"))
    toks = ["A battle was fought"]
    if a is not None or b is not None:
        toks += [" between ", a or "a force", " and ", b or "another force"]
    if site is not None:
        toks += [" at ", site]
    toks += ["."]
    return toks, CAT_COMBAT


def _h_wounded(R, ev):
    wnd = R.hf(_int(ev, "woundee_hfid", "woundee"))
    wnr = R.hf(_int(ev, "wounder_hfid", "wounder"))
    part = _first(ev, "body_part")
    toks = [wnd or "someone", " was wounded"]
    if wnr is not None:
        toks += [" by ", wnr]
    toks += ["."]
    return toks, CAT_COMBAT


def _h_artifact_created(R, ev):
    art = R.artifact(_int(ev, "artifact_id", "artifact"))
    maker = R.hf(_int(ev, "hfid", "creator_hfid"))
    site = R.site(_int(ev, "site_id", "site"))
    toks = ["The artifact ", art or "an artifact", " was created"]
    if maker is not None:
        toks += [" by ", maker]
    if site is not None:
        toks += [" at ", site]
    toks += ["."]
    return toks, CAT_CREATION


def _h_written(R, ev):
    wc = R.wc(_int(ev, "wc_id", "wcid"))
    author = R.hf(_int(ev, "hfid"))
    toks = [author or "an author", " composed ", wc or "a written work", "."]
    return toks, CAT_CREATION


def _h_devoured(R, ev):
    eater = R.hf(_int(ev, "eater", "hfid"))
    victim = R.hf(_int(ev, "victim", "victim_hf"))
    toks = [eater or "a creature", " devoured ", victim or "a victim", "."]
    return toks, CAT_COMBAT


def _h_item_stolen(R, ev):
    thief = R.hf(_int(ev, "hfid", "snatcher_hfid"))
    site = R.site(_int(ev, "site_id", "stash_site", "site"))
    toks = [thief or "someone", " stole an item"]
    if site is not None:
        toks += [" from ", site]
    toks += ["."]
    return toks, CAT_CRIME


def _h_hf_hf_link(R, ev, added=True):
    a = R.hf(_int(ev, "hfid", "hf"))
    b = R.hf(_int(ev, "hfid_target", "hf_target", "target_hfid"))
    link = _first(ev, "link_type", "link")
    pretty = str(link).replace("_", " ") if link else "a relationship"
    if added:
        toks = [a or "someone", " formed a bond (", pretty, ") with ", b or "someone", "."]
    else:
        toks = [a or "someone", " ended a bond (", pretty, ") with ", b or "someone", "."]
    return toks, CAT_SOCIAL


def _h_hf_entity_link(R, ev, added=True):
    hf = R.hf(_int(ev, "hfid"))
    ent = R.ent(_int(ev, "entity_id", "civ_id", "entity"))
    link = _first(ev, "link_type", "link")
    pretty = str(link).replace("_", " ") if link else "member"
    verb = "became affiliated with" if added else "left"
    toks = [hf or "someone", f" {verb} ", ent or "a group",
            f" (as {pretty})" if link else "", "."]
    return toks, CAT_CAREER


def _h_hf_site_link(R, ev, added=True):
    hf = R.hf(_int(ev, "hfid"))
    site = R.site(_int(ev, "site_id", "site"))
    link = _first(ev, "link_type", "link")
    pretty = str(link).replace("_", " ") if link else None
    verb = "took up residence at" if added else "left"
    toks = [hf or "someone", f" {verb} ", site or "a site"]
    if pretty:
        toks += [f" ({pretty})"]
    toks += ["."]
    return toks, CAT_MOVEMENT


def _h_change_state(R, ev):
    hf = R.hf(_int(ev, "hfid"))
    state = _first(ev, "state")
    site = R.site(_int(ev, "site_id", "site"))
    region = R.region(_int(ev, "subregion_id", "region"))
    pretty = str(state).replace("_", " ") if state else "changed state"
    toks = [hf or "someone", " became a ", pretty]
    if site is not None:
        toks += [" at ", site]
    elif region is not None:
        toks += [" in ", region]
    toks += ["."]
    return toks, CAT_MOVEMENT


def _h_change_job(R, ev):
    hf = R.hf(_int(ev, "hfid"))
    new = _first(ev, "new_job")
    old = _first(ev, "old_job")
    np = str(new).replace("_", " ") if new else "a new profession"
    toks = [hf or "someone", " became a ", np, "."]
    return toks, CAT_CAREER


def _h_create_position(R, ev):
    hf = R.hf(_int(ev, "hfid"))
    ent = R.ent(_int(ev, "civ_id", "entity_id", "entity"))
    pos = _first(ev, "position_id", "position")
    toks = [ent or "an entity", " created a new position"]
    if hf is not None:
        toks += [", first held by ", hf]
    toks += ["."]
    return toks, CAT_POLITICS


def _h_add_position(R, ev):
    hf = R.hf(_int(ev, "hfid"))
    ent = R.ent(_int(ev, "civ_id", "entity_id", "entity"))
    toks = [hf or "someone", " took a position of authority in ",
            ent or "an entity", "."]
    return toks, CAT_POLITICS


def _h_assume_identity(R, ev):
    hf = R.hf(_int(ev, "trickster_hfid", "trickster", "hfid"))
    toks = [hf or "someone", " assumed a false identity."]
    return toks, CAT_CRIME


def _h_reputation(R, ev):
    a = R.hf(_int(ev, "hfid1", "hfid"))
    b = R.hf(_int(ev, "hfid2", "hfid_target"))
    toks = [a or "someone", " and ", b or "someone",
            " formed a reputation with one another."]
    return toks, CAT_SOCIAL


def _h_masterpiece(R, ev):
    hf = R.hf(_int(ev, "hfid", "maker_hfid"))
    toks = [hf or "an artisan", " created a masterpiece."]
    return toks, CAT_CREATION


def _h_hf_wounded_undead(R, ev):
    hf = R.hf(_int(ev, "changee_hfid", "changee", "hfid"))
    toks = [hf or "someone", " was transformed."]
    return toks, CAT_LIFE


def _h_created_building(R, ev):
    hf = R.hf(_int(ev, "builder_hfid", "builder_hf", "hfid"))
    site = R.site(_int(ev, "site_id", "site"))
    toks = [hf or "someone", " constructed a building"]
    if site is not None:
        toks += [" at ", site]
    toks += ["."]
    return toks, CAT_CREATION


def _h_abducted(R, ev):
    snatcher = R.hf(_int(ev, "snatcher_hfid", "hfid"))
    target = R.hf(_int(ev, "target_hfid", "target"))
    toks = [snatcher or "someone", " abducted ", target or "a victim", "."]
    return toks, CAT_CRIME


def _h_artifact_stored(R, ev):
    art = R.artifact(_int(ev, "artifact_id", "artifact"))
    hf = R.hf(_int(ev, "hist_figure_id", "hfid"))
    site = R.site(_int(ev, "site_id", "site"))
    toks = [art or "an artifact", " was stored"]
    if site is not None:
        toks += [" at ", site]
    toks += ["."]
    return toks, CAT_MISC


def _h_artifact_possessed(R, ev):
    art = R.artifact(_int(ev, "artifact_id", "artifact"))
    hf = R.hf(_int(ev, "hist_figure_id", "hfid"))
    toks = [hf or "someone", " came to possess ", art or "an artifact", "."]
    return toks, CAT_MISC


def _h_conquered(R, ev):
    attacker = R.ent(_int(ev, "attacker_civ_id", "attacker_enid"))
    defender = R.ent(_int(ev, "defender_civ_id", "defender_enid"))
    site = R.site(_int(ev, "site_id", "site"))
    toks = [site or "a site", " was conquered"]
    if attacker is not None:
        toks += [" by ", attacker]
    toks += ["."]
    return toks, CAT_POLITICS


def _h_learns_secret(R, ev):
    student = R.hf(_int(ev, "student_hfid", "student", "hfid"))
    teacher = R.hf(_int(ev, "teacher_hfid", "teacher"))
    toks = [student or "someone", " learned a secret"]
    if teacher is not None:
        toks += [" from ", teacher]
    toks += ["."]
    return toks, CAT_MISC


# Map canonical (legends.xml, spaces) type -> handler
_HANDLERS = {
    "hf died": _h_hf_died,
    "hf simple battle event": _h_battle,
    "hf wounded": _h_wounded,
    "artifact created": _h_artifact_created,
    "written content composed": _h_written,
    "creature devoured": _h_devoured,
    "item stolen": _h_item_stolen,
    "add hf hf link": lambda R, ev: _h_hf_hf_link(R, ev, True),
    "remove hf hf link": lambda R, ev: _h_hf_hf_link(R, ev, False),
    "add hf entity link": lambda R, ev: _h_hf_entity_link(R, ev, True),
    "remove hf entity link": lambda R, ev: _h_hf_entity_link(R, ev, False),
    "add hf site link": lambda R, ev: _h_hf_site_link(R, ev, True),
    "remove hf site link": lambda R, ev: _h_hf_site_link(R, ev, False),
    "change hf state": _h_change_state,
    "change hf job": _h_change_job,
    "create entity position": _h_create_position,
    "add hf entity honor": _h_add_position,
    "assume identity": _h_assume_identity,
    "hfs formed reputation relationship": _h_reputation,
    "hf reunion": _h_reputation,
    "created building": _h_created_building,
    "change hf body state": _h_hf_wounded_undead,
    "hf abducted": _h_abducted,
    "artifact stored": _h_artifact_stored,
    "artifact possessed": _h_artifact_possessed,
    "site conquered": _h_conquered,
    "hf learns secret": _h_learns_secret,
    "masterpiece item": _h_masterpiece,
    "masterpiece engraving": _h_masterpiece,
}


def _generic(R, ev, type_pretty):
    """Fallback: name the event and link whatever references we can find."""
    refs = []
    for tok in (R.hf(_int(ev, "hfid")),
                R.hf(_int(ev, "hfid_target", "target_hfid")),
                R.site(_int(ev, "site_id", "site")),
                R.ent(_int(ev, "civ_id", "entity_id", "entity")),
                R.artifact(_int(ev, "artifact_id", "artifact"))):
        if tok is not None:
            refs.append(tok)
    toks = [type_pretty.capitalize()]
    if refs:
        toks += [". Involving "]
        for i, r in enumerate(refs):
            if i:
                toks += [", "]
            toks.append(r)
    toks += ["."]
    # crude category guess from keywords
    t = type_pretty
    cat = CAT_MISC
    if "die" in t or "death" in t:
        cat = CAT_LIFE
    elif "battle" in t or "attack" in t or "kill" in t or "war" in t:
        cat = CAT_COMBAT
    elif "creat" in t or "built" in t or "compose" in t:
        cat = CAT_CREATION
    elif "steal" in t or "stolen" in t or "abduct" in t or "crim" in t:
        cat = CAT_CRIME
    elif "pray" in t or "worship" in t or "temple" in t:
        cat = CAT_RELIGION
    elif "conquer" in t or "overthr" in t or "diploma" in t:
        cat = CAT_POLITICS
    return toks, cat


def render_event(ev, R):
    """
    ev : merged event dict (from both files), must contain 'type' (canonical,
         spaced) and ideally 'year'.
    R  : Resolver
    returns dict {"y": year, "type": pretty_type, "cat": category, "tokens": [...]}
    """
    etype = str(ev.get("type", "")).strip()
    year = ev.get("year")
    handler = _HANDLERS.get(etype)
    if handler is not None:
        try:
            tokens, cat = handler(R, ev)
        except Exception:
            tokens, cat = _generic(R, ev, etype)
    else:
        tokens, cat = _generic(R, ev, etype)

    return {
        "y": year,
        "type": etype,
        "cat": cat,
        "tokens": _compact(tokens),
        # DF's own within-year tick counter. 1200 ticks/day, 28 days/month
        # (see server.py's _s72_to_month_day), this is what lets the
        # calendar tool place an event on an actual day instead of just a
        # year. -1/None means "no time-of-year recorded" (e.g. worldgen
        # events), which the calendar treats as "not shown on a specific day".
        "s72": ev.get("seconds72"),
    }
