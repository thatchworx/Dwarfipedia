"""
image_provider.py  --  local image generation, in graphite
=============================================================================

Talks to a local Stable Diffusion WebUI (Forge, or AUTOMATIC1111. They share
an API) over HTTP, the same way ai_provider talks to Ollama. Nothing here
reaches the internet and nothing runs unless you've installed one and it's up.

WHY PENCIL, AND WHY IT'S HARDER THAN IT SOUNDS

Left alone, these models produce the glossy airbrushed look everyone
recognises instantly. Smooth skin, symmetrical faces, digital lighting.
Getting honest graphite out of one is mostly a matter of arguing it out of
that default, which is why the negative prompt here is long and specific:
"3d render", "airbrushed", "smooth", "octane", "artstation" and friends are
named explicitly, because a positive request for "pencil" does not by itself
suppress them.

The positive side asks for the marks of a hand rather than the subject alone,
such as visible construction lines, uneven hatching, smudged graphite, and an
unfinished edge where the artist stopped. Those artefacts are the point. A
flawless sketch reads as machine output just as clearly as a glossy render
does.

TWO KINDS OF PICTURE

  portrait  a study of one figure, drawn from their real vital record
  scene     a moment, drawn from a passage of their story, which is the
            more interesting of the two, because the wordbank text already
            describes things worth seeing

Prompts and styling live in userdata/image_prompts.json and are editable in
the app, exactly like the text prompts.
"""
import base64
import io
import json
import os
import random
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USERDATA_DIR = os.path.join(BASE_DIR, "userdata")
IMAGES_DIR = os.path.join(USERDATA_DIR, "images")
CFG_FILE = os.path.join(USERDATA_DIR, "image_prompts.json")


# ---------------------------------------------------------------------------
# Style defaults
# ---------------------------------------------------------------------------
DEFAULT_STYLE = (
    "graphite pencil drawing on toothy sketchbook paper, traditional media, "
    "hand-drawn, visible construction lines, uneven cross-hatching, smudged "
    "graphite, eraser marks, pencil pressure varying across the stroke, "
    "unfinished at the edges, loose gestural linework, monochrome, "
    "no colour, sketchbook study"
)

# Named explicitly because asking for "pencil" does not suppress any of it.
DEFAULT_NEGATIVE = (
    "3d render, octane render, unreal engine, cgi, digital painting, "
    "airbrushed, smooth shading, glossy, plastic skin, photorealistic, "
    "photograph, hyperrealistic, artstation, trending on artstation, "
    "oversaturated, vibrant colours, colour, coloured, neon, "
    "perfect symmetry, flawless, beautiful, glamour, anime, manga, cel shaded, "
    "watermark, signature, text, letters, caption, frame, border, "
    "extra fingers, extra limbs, deformed hands, mutated hands"
)

# Variety, same principle as the text style seeds: a constant prompt gives a
# constant look, so a few of these are drawn at random each time. They vary
# the drawing, not the subject.
DEFAULT_STYLE_SEEDS = [
    "quick life-study, ten minutes at most",
    "heavier line weight on the shadowed side",
    "drawn from slightly below eye level",
    "three-quarter view, the far side barely indicated",
    "only the face resolved, the rest suggested in loose strokes",
    "hard 2H lines with soft 6B shadows over them",
    "the sheet slightly foxed and thumbed at one corner",
    "an abandoned first attempt still faintly visible underneath",
    "strong single light source, most of the figure left in paper white",
    "a margin note scribbled and then rubbed out",
    "contour-led, almost no shading",
    "dense hatching built up in layers, worked over too long",
    "drawn quickly while the subject moved",
    "generous white space, the figure small on the page",
]

DEFAULT_PORTRAIT_TEMPLATE = (
    "character study of {subject}, {descriptors}, "
    "weathered and particular face, ordinary features, not beautiful, "
    "period clothing appropriate to a pre-industrial fantasy world"
)

DEFAULT_SCENE_TEMPLATE = (
    "{scene}, {subject} present, "
    "pre-industrial fantasy setting, candid unposed moment, "
    "ordinary people, functional clothing, believable tools and surroundings"
)

DEFAULTS = {
    "style": DEFAULT_STYLE,
    "negative": DEFAULT_NEGATIVE,
    "style_seeds": DEFAULT_STYLE_SEEDS,
    "portrait_template": DEFAULT_PORTRAIT_TEMPLATE,
    "scene_template": DEFAULT_SCENE_TEMPLATE,
    "seeds_per_image": 2,
    "steps": 28,
    "cfg_scale": 6.5,
    "width": 512,
    "height": 640,
    "sampler": "DPM++ 2M Karras",
}


def load():
    out = dict(DEFAULTS)
    try:
        with open(CFG_FILE, encoding="utf-8") as fh:
            out.update(json.load(fh) or {})
    except Exception:
        pass
    return out


def save(data):
    os.makedirs(USERDATA_DIR, exist_ok=True)
    keep = {k: data[k] for k in DEFAULTS if k in data}
    tmp = CFG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keep, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, CFG_FILE)
    return load()


def reset():
    try:
        os.remove(CFG_FILE)
    except OSError:
        pass
    return load()


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------
def _clean(text, limit=340):
    """Trim a passage of prose into something a diffusion model can use.

    These models weight the front of the prompt heavily and ignore the tail,
    so a whole paragraph is worse than one good sentence. Take the opening,
    strip the wiki's own markup, and stop at a sentence boundary.
    """
    if not text:
        return ""
    t = " ".join(str(text).split())
    t = t.replace("[[", "").replace("]]", "")
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in (". ", "; ", ", "):
        i = cut.rfind(sep)
        if i > limit * 0.5:
            return cut[:i]
    return cut


def build_prompt(kind, subject, descriptors=None, scene=None, rng=None, etype="hf"):
    """Returns (positive, negative, seeds_used)."""
    cfg = load()
    rng = rng or random
    pool = list(cfg.get("style_seeds") or [])
    n = int(cfg.get("seeds_per_image") or 2)
    seeds = rng.sample(pool, min(n, len(pool))) if pool else []

    framing = TYPE_FRAMING.get(etype, "")
    if kind == "scene":
        body = (cfg.get("scene_template") or DEFAULT_SCENE_TEMPLATE).format(
            scene=_clean(scene) or "a quiet moment",
            subject=subject or "a figure")
    elif etype != "hf":
        # a "portrait" of a place or an object isn't a portrait at all
        body = ", ".join(x for x in [framing, subject, descriptors] if x)
    else:
        body = (cfg.get("portrait_template") or DEFAULT_PORTRAIT_TEMPLATE).format(
            subject=subject or "a person",
            descriptors=descriptors or "")
    if kind == "scene" and framing and etype != "hf":
        body = framing + ", " + body

    parts = [cfg.get("style") or DEFAULT_STYLE, body]
    if seeds:
        parts.append(", ".join(seeds))
    positive = ", ".join(p.strip(" ,") for p in parts if p and p.strip(" ,"))
    return positive, (cfg.get("negative") or DEFAULT_NEGATIVE), seeds


# Per-entity-type framing. A site wants an establishing view; an artifact
# wants an object study on a plain ground; a creature wants a naturalist's
# plate. Sending all of them the same "character study" phrasing was the
# reason non-figure pages produced generic results.
TYPE_FRAMING = {
    "hf":       "character study, single figure",
    "site":     "establishing view of the settlement from a rise, architectural study",
    "ent":      "heraldic study, a gathering of this people, banners and dress",
    "artifact": "object study on a plain ground, museum plate, single object, no figures",
    "wc":       "a study of the physical book or scroll, pages and binding, no figures",
    "creature": "naturalist's field plate of the animal, anatomical study, single creature",
    "region":   "wide landscape study of the country, no figures",
}


def describe_entity(etype, rec):
    """Prompt descriptors drawn from whatever the record actually holds for
    this type of thing. Stays strictly to recorded facts. Inventing a
    heroic jawline would be inventing biography."""
    if etype == "hf":
        return describe_figure(rec)
    bits = []
    if etype == "site":
        if rec.get("type"):
            bits.append(str(rec["type"]))
        structs = rec.get("structures") or []
        kinds = {s.get("type") for s in structs if isinstance(s, dict) and s.get("type")}
        bits += list(kinds)[:3]
        if rec.get("civ_race"):
            bits.append(f"built by {rec['civ_race']}s")
    elif etype == "ent":
        for k in ("race", "type"):
            if rec.get(k):
                bits.append(str(rec[k]))
    elif etype == "artifact":
        for k in ("item_type", "material"):
            if rec.get(k):
                bits.append(str(rec[k]))
        if rec.get("quality"):
            bits.append(str(rec["quality"]))
    elif etype == "wc":
        for k in ("form", "type"):
            if rec.get(k):
                bits.append(str(rec[k]))
    elif etype == "creature":
        if rec.get("is_monster"):
            bits.append("monstrous")
        for k in ("biome", "size"):
            if rec.get(k):
                bits.append(str(rec[k]))
    elif etype == "region":
        for k in ("type", "biome"):
            if rec.get(k):
                bits.append(str(rec[k]))
    return ", ".join(b for b in bits if b)


def describe_figure(rec):
    """Turn a real vital record into prompt descriptors. Deliberately plain.
    The record says what it says, and inventing a heroic jawline would be
    inventing biography."""
    bits = []
    race = (rec.get("race") or "").strip()
    sex = (rec.get("sex") or "").strip()
    if race:
        bits.append(race)
    if sex:
        bits.append(sex)
    by, dy = rec.get("birth_year"), rec.get("death_year")
    if isinstance(by, int) and isinstance(dy, int) and dy > by:
        age = dy - by
        bits.append("elderly" if age > 120 else "middle-aged" if age > 45 else "young")
    role = (rec.get("associated_type") or "").strip()
    if role and role.lower() != "standard":
        bits.append(role)
    skills = sorted(rec.get("skills") or [], key=lambda s: -s.get("ip", 0))[:2]
    for s in skills:
        if s.get("skill"):
            bits.append(s["skill"])
    return ", ".join(bits)


# ---------------------------------------------------------------------------
# The backend
# ---------------------------------------------------------------------------
class SDWebUIProvider:
    """Forge or AUTOMATIC1111. Both expose the same /sdapi/v1 endpoints, so
    one client covers either."""
    name = "sdwebui"

    def __init__(self, host=None, timeout=None):
        self.host = (host or os.environ.get("DWARFWIKI_SD")
                     or "http://127.0.0.1:7860").rstrip("/")
        self.timeout = int(os.environ.get("DWARFWIKI_SD_TIMEOUT", "180"))

    def available(self):
        import urllib.request
        try:
            urllib.request.urlopen(f"{self.host}/sdapi/v1/options", timeout=2)
            return True
        except Exception:
            return False

    def models(self):
        import urllib.request
        try:
            with urllib.request.urlopen(f"{self.host}/sdapi/v1/sd-models", timeout=5) as r:
                return [m.get("model_name") or m.get("title", "")
                        for m in json.loads(r.read())]
        except Exception:
            return []

    def diagnose(self):
        up = self.available()
        return {"host": self.host, "reachable": up,
                "models": self.models() if up else [],
                "timeout": self.timeout}

    def generate(self, positive, negative, cfg=None):
        """Returns raw PNG bytes."""
        import urllib.request
        import urllib.error

        c = cfg or load()
        payload = {
            "prompt": positive,
            "negative_prompt": negative,
            "steps": int(c.get("steps", 28)),
            "cfg_scale": float(c.get("cfg_scale", 6.5)),
            "width": int(c.get("width", 512)),
            "height": int(c.get("height", 640)),
            "sampler_name": c.get("sampler", "DPM++ 2M Karras"),
            "batch_size": 1,
            "n_iter": 1,
        }
        req = urllib.request.Request(
            f"{self.host}/sdapi/v1/txt2img",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read()).get("error", "")
            except Exception:
                pass
            raise RuntimeError(f"The image server rejected the request: {detail or e}") from None
        except (TimeoutError, OSError):
            if not self.available():
                raise RuntimeError(
                    f"Can't reach the image server at {self.host}. Start Forge or "
                    "AUTOMATIC1111 with the --api flag and try again. (This is an "
                    "HTTP connection to localhost. Where DwarfWiki sits on disk "
                    "makes no difference.)") from None
            raise RuntimeError(
                f"The image server didn't finish within {self.timeout}s. Lower the "
                "step count in the image settings, or raise DWARFWIKI_SD_TIMEOUT."
            ) from None

        imgs = data.get("images") or []
        if not imgs:
            raise RuntimeError("The image server returned no image.")
        return base64.b64decode(imgs[0].split(",", 1)[-1])


PROVIDER = SDWebUIProvider()


def save_png(raw):
    """Write bytes into the same gallery folder uploads use, so generated
    images flow through every feature that already exists. Starring,
    portraits, per-section galleries."""
    import uuid
    os.makedirs(IMAGES_DIR, exist_ok=True)
    fname = uuid.uuid4().hex + ".png"
    with open(os.path.join(IMAGES_DIR, fname), "wb") as fh:
        fh.write(raw)
    return fname
