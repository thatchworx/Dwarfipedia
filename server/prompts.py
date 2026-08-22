"""
prompts.py  --  editable prompts, and the style-seed system
=============================================================================

Two jobs.

1. PROMPTS YOU CAN EDIT
   The system prompts used to be string literals buried in two source files.
   They now live in userdata/prompts.json, which means they survive updates,
   can be edited in the app, and can be reset to the shipped defaults without
   touching code.

2. STYLE SEEDS. The fix for everything sounding the same
   Given an identical system prompt and a similar seed text, a model will
   reach for the same imagery every time. That's why a dozen generated pages
   all end up "in the frosty crags". Nothing in the prompt was WRONG; it was
   just constant, so the output was too.

   Every generation now picks a few directives at random from a pool and
   appends them to the system prompt. Two passages over the same figure get
   different instructions about voice, focus and structure, so they diverge
   at the source rather than being de-duplicated afterwards.

   The pool is editable too. Add your own, delete ones you dislike.
"""
import json
import os
import random

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USERDATA_DIR = os.path.join(BASE_DIR, "userdata")
PROMPTS_FILE = os.path.join(USERDATA_DIR, "prompts.json")


# ---------------------------------------------------------------------------
# Shipped defaults
# ---------------------------------------------------------------------------
DEFAULT_BIOGRAPHY = """You are a skilled biographer expanding a short draft note \
into a polished encyclopedia passage, for a private fantasy wiki generated \
from a Dwarf Fortress world.

You will be given a SEED TEXT (a terse draft), CHARACTER FACTS (real \
biographical information), and optionally BACKGROUND (light setting \
context). Rules:
- Write exactly two paragraphs of vivid, human, narrative prose.
- The seed text is your foundation: every concrete detail it mentions must \
still be recognizable in your output. You are elaborating and dramatizing \
it, not replacing it or contradicting it.

NAMING, this matters more than any other stylistic rule:
- The reader already knows whose article this is. It is printed at the top \
of the page. Assume that knowledge completely.
- Use the subject's full name AT MOST ONCE in the whole passage, and only \
if it genuinely helps. Very often the right number is zero.
- After that, refer to the subject with pronouns, or occasionally by role, \
craft, or standing ("the engraver", "the young smith", "she"). Vary it, and \
lean on pronouns by default.
- Never open consecutive sentences with the subject's name.
- Write the way a real encyclopedia entry reads once past its opening line.

- Weave in the character facts naturally where relevant to this section's \
topic. Do not just list them.
- Vary sentence length and opening. A run of identically-shaped sentences is \
the clearest tell of machine writing.
- Do not invent new hard facts: no new names, dates, relationships, deaths, \
or events beyond what you were given. Atmosphere and interiority are fine to \
invent; biographical facts are not.
- Never write a war record or political career for a child or a solitary \
wild creature.
- Never include disclaimers or meta-commentary.
- No markdown, no headers, no bullet points. Plain prose only."""

DEFAULT_ENCYCLOPEDIA = """You are a scholarly encyclopedia writer, for a \
private fantasy wiki generated from a real Dwarf Fortress world.

You will be given a CATEGORY (the section heading), the NAME of the subject, \
and FACTS drawn from the world's real recorded history. Rules:
- Write two paragraphs on this specific topic, grounded in the real facts given.

NAMING, this matters more than any other stylistic rule:
- The reader already knows what this article is about; the name is printed \
at the top of the page. Use the full name AT MOST ONCE, and often zero times \
is correct.
- After that use pronouns, or a short descriptor ("the fortress", "the \
order", "it", "they"). Vary it.
- Never open consecutive sentences with the name.
- Vary sentence length and opening construction.

- If the facts are sparse, it's honest to write something modest and \
understated. Don't invent a rich history out of nothing.
- Stay strictly consistent with the facts. Invent atmosphere, not events.
- Never include disclaimers or meta-commentary.
- No markdown, no headers, no bullet points. Plain prose only."""

DEFAULT_COMMERCE = """You are a trade historian writing a short passage about \
one settlement's commerce, for a private fantasy wiki built from a real \
Dwarf Fortress world.

- Two paragraphs, grounded strictly in the real trade facts given.
- Name the settlement itself at most once; after that use "the town", "the \
site", "it". Repeating the place name every sentence reads as machine \
writing. Vary sentence length and opening construction too.
- If real named goods or merchant companies are given, reference them by \
name naturally.
- If the facts are thin, write something modest rather than inventing a \
bustling entrepot.
- Never include disclaimers or meta-commentary.
- No markdown, no headers, no bullet points. Plain prose only."""


# ---------------------------------------------------------------------------
# Style seeds
#
# Each generation draws a few of these at random. They deliberately pull in
# different directions. Some are about voice, some about what to foreground,
# some about structure, so that two passages about the same subject don't
# converge on the same imagery.
#
# Note what is NOT here: setting-specific scenery. Telling the model to write
# about crags is exactly how you get every page mentioning crags. These steer
# HOW it writes, not WHAT it describes.
# ---------------------------------------------------------------------------
DEFAULT_STYLE_SEEDS = [
    "Open in the middle of things, as though the reader already knows the outline and wants the detail.",
    "Favour concrete, physical specifics over abstract summary. One real object beats three adjectives.",
    "Write with the measured detachment of a chronicler who has outlived their subject.",
    "Let one small, odd, human detail carry more weight than the grand summary.",
    "Prefer plain words. Resist the ornate synonym when a common word is truer.",
    "Structure this as cause and consequence rather than a list of attributes.",
    "Allow one sentence to run long and unspooling; keep the others short around it.",
    "Write as if quoting from a source that is no longer extant, without saying so.",
    "Foreground what this cost them, or what it cost others.",
    "Attend to work and craft. What hands did, what was made or ruined.",
    "Note what was ordinary about them as carefully as what was remarkable.",
    "Give the passage a sense of duration: things that took years, not moments.",
    "Where the record is thin, let the prose be spare rather than padding it out.",
    "Use the language of record and testimony. What is attested, what is merely said.",
    "Avoid weather and landscape as scene-setting; find atmosphere in people and objects instead.",
    "Close on an unresolved note rather than a summarising verdict.",
    "Write the second paragraph in a noticeably different register from the first.",
    "Let a specific number, date, or quantity do real work in the passage.",
    "Treat rumour and disputed accounts as worth reporting, flagged as such.",
    "Resist grandeur. Even significant lives are made of small, awkward particulars.",
]

# Repeated imagery the model reaches for by default. Named explicitly because
# a general "be original" instruction does far less than a concrete ban.
DEFAULT_BANNED_PHRASES = [
    "frosty crags", "windswept", "time immemorial", "little did they know",
    "testament to", "tapestry of", "indomitable spirit", "shrouded in mystery",
    "echoes through the ages", "left an indelible mark", "whispered in hushed tones",
    "stood as a beacon", "the annals of history", "forged in fire",
]

DEFAULTS = {
    "biography": DEFAULT_BIOGRAPHY,
    "encyclopedia": DEFAULT_ENCYCLOPEDIA,
    "commerce": DEFAULT_COMMERCE,
    "style_seeds": DEFAULT_STYLE_SEEDS,
    "banned_phrases": DEFAULT_BANNED_PHRASES,
    "seeds_per_generation": 3,
}


# ---------------------------------------------------------------------------
def load():
    """User settings layered over the shipped defaults, so a partial or older
    prompts.json can never leave a key missing."""
    out = dict(DEFAULTS)
    try:
        with open(PROMPTS_FILE, encoding="utf-8") as fh:
            out.update(json.load(fh) or {})
    except Exception:
        pass
    return out


def save(data):
    os.makedirs(USERDATA_DIR, exist_ok=True)
    keep = {k: data[k] for k in DEFAULTS if k in data}
    tmp = PROMPTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keep, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PROMPTS_FILE)
    return load()


def reset():
    try:
        os.remove(PROMPTS_FILE)
    except OSError:
        pass
    return load()


def build_system(kind, rng=None):
    """The prompt actually sent for one generation: the base prompt for this
    kind, plus a fresh random handful of style directives.

    Returns (prompt_text, seeds_used) so the caller can record which seeds
    produced a given passage. Useful when one turns out to read especially
    well, or especially badly.
    """
    cfg = load()
    base = cfg.get(kind) or DEFAULTS.get(kind) or ""
    pool = list(cfg.get("style_seeds") or [])
    banned = list(cfg.get("banned_phrases") or [])
    n = int(cfg.get("seeds_per_generation") or 3)

    rng = rng or random
    seeds = rng.sample(pool, min(n, len(pool))) if pool else []

    extra = ""
    if seeds:
        extra += ("\n\nFOR THIS PASSAGE SPECIFICALLY (these change every time, "
                  "follow them even where they cut against your instincts):\n"
                  + "\n".join("- " + s for s in seeds))
    if banned:
        extra += ("\n\nDo not use any of these worn phrases, or close variants:\n"
                  + ", ".join(banned) + ".")
    return base + extra, seeds
