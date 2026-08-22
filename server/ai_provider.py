"""
ai_provider.py  --  clean abstraction for future LLM-backed content generation
=================================================================================

Nothing in this file calls a real model yet. This exists so that when a real
provider (Ollama, most likely) gets wired in later:
  - prompts live in ONE place, separate from server.py / UI code
  - swapping providers or models is a one-line change (PROVIDER = ...)
  - every generated result has a consistent shape (text/source/model/time)
    from day one, so the badge system and override storage never need to
    change again when a real backend arrives
"""
import os
import time


class GenerationResult:
    def __init__(self, text, source, model=None):
        self.text = text
        self.source = source      # "edited" | "llm"  (wordbank = no override at all)
        self.model = model        # e.g. "llama3.1:8b". None for non-LLM sources
        self.generated_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        return {"text": self.text, "source": self.source,
                "model": self.model, "generated_at": self.generated_at}


class AIProvider:
    """Base interface every provider implements."""
    name = "base"

    def available(self):
        raise NotImplementedError

    def generate(self, system_prompt, user_prompt):
        raise NotImplementedError


class NotConfiguredProvider(AIProvider):
    """Default provider until something real is wired in. The [regen] button
    can exist in the UI and fail gracefully against this rather than the
    button needing to not exist until a model is chosen."""
    name = "none"

    def available(self):
        return False

    def generate(self, system_prompt, user_prompt):
        raise RuntimeError("No AI provider is configured yet.")


class OllamaProvider(AIProvider):
    """Talks to a local Ollama server (default port 11434). Not active until
    explicitly selected as PROVIDER below. Importing this module does not
    start trying to reach anything on the network."""
    name = "ollama"

    def __init__(self, model=None, host=None, timeout=None):
        # Environment first, so the model can be changed without editing code.
        self.model = model or os.environ.get("DWARFWIKI_MODEL") or "llama3.1:8b"
        self.host = (host or os.environ.get("DWARFWIKI_OLLAMA")
                     or "http://localhost:11434").rstrip("/")
        self.timeout = timeout or int(os.environ.get("DWARFWIKI_AI_TIMEOUT", "60"))

    # ---- introspection -------------------------------------------------
    def installed_models(self):
        """What this Ollama actually has pulled. Used to give a real error
        instead of a KeyError when the configured model isn't present."""
        import urllib.request, json as _json
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=3) as r:
                data = _json.loads(r.read())
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def available(self):
        try:
            import urllib.request
            urllib.request.urlopen(f"{self.host}/api/tags", timeout=1.5)
            return True
        except Exception:
            return False

    def diagnose(self):
        """Everything needed to explain a failure, in one call."""
        up = self.available()
        models = self.installed_models() if up else []
        # a tag may be stored as "llama3.1:8b" and asked for as "llama3.1".
        # Treat a bare-name match as present.
        base = self.model.split(":")[0]
        have = any(m == self.model or m.split(":")[0] == base for m in models)
        return {"host": self.host, "model": self.model, "reachable": up,
                "model_installed": have, "installed_models": models,
                "timeout": self.timeout}

    # ---- generation ----------------------------------------------------
    def generate(self, system_prompt, user_prompt):
        import urllib.request
        import urllib.error
        import json as _json

        body = _json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            # Bounds matter more than they look. Without num_predict the model
            # can generate until it decides to stop, which on a slow setup
            # means it runs until the socket times out and you get nothing
            # after a minute of full-tilt inference. Without an explicit
            # num_ctx, some Ollama builds default to 2048, so a page with
            # twenty existing sections overflows the window and forces a
            # large, slow prefill every single call. Both are now stated.
            "options": {
                "num_predict": 380,     # ~two paragraphs; the prompt asks for exactly that
                "num_ctx": 4096,        # comfortably fits our largest prompt
                "temperature": 0.85,
                "top_p": 0.92,
                "repeat_penalty": 1.08,
            },
        }).encode()

        req = urllib.request.Request(
            f"{self.host}/api/chat", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = _json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = _json.loads(e.read()).get("error", "")
            except Exception:
                pass
            if "not found" in detail.lower() or e.code == 404:
                have = self.installed_models()
                raise RuntimeError(
                    f"Ollama has no model named '{self.model}'. "
                    + (f"Installed: {', '.join(have)}. " if have else "No models are installed. ")
                    + f"Pull it with:  ollama pull {self.model}") from None
            raise RuntimeError(f"Ollama rejected the request: {detail or e}") from None
        except (TimeoutError, OSError) as e:
            if not self.available():
                raise RuntimeError(
                    f"Can't reach Ollama at {self.host}. Is it running? "
                    "(This is an HTTP connection, not a file path. Where "
                    "DwarfWiki lives on disk doesn't affect it.)") from None
            raise RuntimeError(
                f"Ollama didn't answer within {self.timeout}s. The model is "
                "probably running on CPU rather than GPU, or is too large for "
                "available memory. Try a smaller model, "
                "DWARFWIKI_MODEL=llama3.2:3b, or raise DWARFWIKI_AI_TIMEOUT."
            ) from None

        if "error" in data:
            raise RuntimeError(f"Ollama: {data['error']}")
        msg = (data.get("message") or {}).get("content")
        if not msg:
            raise RuntimeError("Ollama returned an empty response.")
        return msg.strip()


# The active provider. Swapping this one line (or its constructor args) is
# the entire "future model switching" story. Nothing else in the codebase
# needs to change. Left as NotConfiguredProvider by default in the shipped
# code would mean the [regen] button always fails gracefully. That's the
# "ships without the model" story: the CODE ships either way, running it
# for real just needs Ollama actually up on the machine using it.
PROVIDER = OllamaProvider(model="llama3.1:8b")


# ---------------------------------------------------------------------------
# System prompt. Kept separate from UI/server code on purpose. The job
# here is specifically ELABORATION, not invention: take the short wordbank
# seed (the thing that already reads as a bit "canon-flavored" and terse)
# and turn it into two paragraphs of real human-feeling prose that still
# visibly grows out of the seed's specific details, not something that
# ignores it and free-associates from the character facts instead.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a skilled biographer expanding a short draft note \
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
- Never open consecutive sentences with the subject's name. Never restate \
the name where a pronoun would be unambiguous.
- Write the way a real encyclopedia entry reads once past its opening line: \
the name appears in the title and the first sentence, then largely \
disappears into "he", "she", "they".

- Weave in the character facts naturally where relevant to this section's \
topic. Do not just list them, and do not force in facts that don't fit \
this section's focus.
- Vary sentence length and opening. Do not begin every sentence with the \
same construction; a run of identically-shaped sentences is the clearest \
tell of machine writing.
- Use the background context only lightly, as atmosphere, not as the main subject.
- Do not invent new hard facts: no new names, dates, relationships, deaths, \
or events beyond what you were given. Atmosphere, interiority, and sensory \
detail are fine to invent; biographical facts are not.
- Never write a war record, military career, or political career for a \
child or a solitary wild creature.
- Match the register of a serious biographical encyclopedia. Confident, \
evocative, no throat-clearing, no meta-commentary.
- Never include disclaimers or phrases like "this is fictional", "as an \
AI", or "note that this is generated".
- No markdown formatting, no headers, no bullet points. Plain prose only."""


def generate_category(label, seed_text, character_sheet, background):
    """
    Entry point the server calls for the [regen] action.
      label            -- the category heading, e.g. "Military Career"
      seed_text        -- the CURRENT wordbank text for this category, the
                           thing being elaborated on (highest priority)
      character_sheet  -- plain-text block: real facts about the person/
                           creature (bio facts, relationships, other
                           sections' current text). Deliberately excludes
                           raw event lists, which are high-volume and low
                           value-per-token for this purpose
      background       -- plain-text block: light real facts about their
                           linked site/civ, secondary weight
    """
    if not PROVIDER.available():
        raise RuntimeError(
            "Ollama isn't reachable at localhost:11434. Make sure it's "
            "running, or 'regen' will keep failing gracefully like this.")
    parts = [f"CATEGORY: {label}", f'SEED TEXT: "{seed_text}"']
    if character_sheet:
        parts.append(f"CHARACTER FACTS:\n{character_sheet}")
    if background:
        parts.append(f"BACKGROUND:\n{background}")
    parts.append("Write the two-paragraph expansion now.")
    user_prompt = "\n\n".join(parts)
    import prompts as _p
    system, seeds = _p.build_system("biography")
    text = PROVIDER.generate(system, user_prompt)
    return GenerationResult(text, source="llm", model=getattr(PROVIDER, "model", None))


# ---------------------------------------------------------------------------
# Commerce. A settlement's trade profile, not a person's biography, so it
# gets its own framing rather than reusing SYSTEM_PROMPT. There is no
# wordbank seed for this one. Sites never had a deterministic baseline,
# building a full curated wordbank for every site was out of scope for this
# pass, so the model is working from real structured facts only, not
# elaborating on an existing draft.
# ---------------------------------------------------------------------------
COMMERCE_SYSTEM_PROMPT = """You are a trade historian writing a short \
commercial profile of a settlement, for a private fantasy wiki generated \
from a Dwarf Fortress world.

You will be given real facts about a site: its type, activity level, any \
merchant companies based there, and any real named goods/artifacts known \
to be located there. Rules:
- Write two paragraphs describing what this place is like commercially,
  what it likely trades in, who its merchants are, how bustling or quiet \
it feels. Grounded in the real facts given.
- Name the settlement itself at most once; after that use "the town", \
"the site", "it". Repeating the place name every sentence reads as machine \
writing. Vary sentence length and opening construction too.
- If real named goods or merchant companies are given, reference them by \
name naturally. If very little real commercial data is given, it's \
honest to write a smaller, quieter trade presence. Don't invent a bustling \
market out of nothing.
- Do not invent new hard facts: no new named companies, named goods, or \
specific prices beyond what you were given. General trade character, \
atmosphere, and reputation are fine to invent; specific transactions are not.
- Match the register of a serious historical-economic account. Confident, \
grounded, no throat-clearing.
- Never include disclaimers or phrases like "this is fictional", "as an \
AI", or "note that this is generated".
- No markdown formatting, no headers, no bullet points. Plain prose only."""


def generate_commerce(site_name, site_facts):
    if not PROVIDER.available():
        raise RuntimeError(
            "Ollama isn't reachable at localhost:11434. Make sure it's "
            "running, or 'regen' will keep failing gracefully like this.")
    user_prompt = f"SITE: {site_name}\n\nFACTS:\n{site_facts}\n\nWrite the two-paragraph commercial profile now."
    import prompts as _p
    system, seeds = _p.build_system("commerce")
    text = PROVIDER.generate(system, user_prompt)
    return GenerationResult(text, source="llm", model=getattr(PROVIDER, "model", None))
