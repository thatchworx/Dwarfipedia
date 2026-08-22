"""
fortress.py  --  Fortress Mode dashboard API (Flask blueprint)
=========================================================================
Live, read-only fortress data pulled via a DFHack script
(dfhack_scripts/dwarfwiki_export.lua). Nothing here is generated or
inferred. It's a snapshot of the game's own state, refreshed on request.

Setup (also available via /api/fortress/settings/install_script):
  1. Point Settings at your DFHack install folder.
  2. Click "Install / update script" to copy dwarfwiki_export.lua into
     DFHack's scripts folder.
  3. With DF + DFHack running, hit Refresh on a Fortress slot.
"""
import os
import io
import json
import time
import uuid
import subprocess

from flask import Blueprint, jsonify, request, abort

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SERVER_DIR)
USERDATA_DIR = os.path.join(BASE_DIR, "userdata")
FORTRESS_DIR = os.path.join(USERDATA_DIR, "fortress")
SLOTS_FILE = os.path.join(FORTRESS_DIR, "slots.json")
SETTINGS_FILE = os.path.join(FORTRESS_DIR, "settings.json")
EXPORT_SCRIPT_SRC = os.path.join(SERVER_DIR, "dfhack_scripts", "dwarfwiki_export.lua")

os.makedirs(FORTRESS_DIR, exist_ok=True)

fortress = Blueprint("fortress", __name__)

# Rolling history keeps headline numbers only (population, item/building
# counts, timestamp), capped so it can't grow unbounded.
_HISTORY_CAP = 2000


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _slots():
    return _load_json(SLOTS_FILE, {"slots": []})


def _slot_dir(slot_id):
    d = os.path.join(FORTRESS_DIR, slot_id)
    os.makedirs(d, exist_ok=True)
    return d


def _settings():
    s = _load_json(SETTINGS_FILE, {})
    # Must be the folder that directly contains dfhack-run.exe. On a
    # normal Steam install that's DFHack's "hack" subfolder.
    s.setdefault("dfhack_dir", r"C:\Program Files (x86)\Steam\steamapps\common\DFHack\hack")
    return s


# ---------------------------------------------------------------------
# Settings. Where DFHack lives, and installing the export script there.
# ---------------------------------------------------------------------
@fortress.route("/api/fortress/settings", methods=["GET"])
def api_fortress_settings():
    return jsonify(_settings())


@fortress.route("/api/fortress/settings", methods=["POST"])
def api_fortress_settings_save():
    body = request.get_json(force=True, silent=True) or {}
    s = _settings()
    if "dfhack_dir" in body:
        s["dfhack_dir"] = body["dfhack_dir"].strip()
    _save_json(SETTINGS_FILE, s)
    return jsonify(s)


@fortress.route("/api/fortress/settings/install_script", methods=["POST"])
def api_fortress_install_script():
    """Copies the bundled dwarfwiki_export.lua into <dfhack_dir>/scripts/
    so DFHack's console/dfhack-run can find it by name."""
    s = _settings()
    dest_dir = os.path.join(s["dfhack_dir"], "scripts")
    if not os.path.isdir(dest_dir):
        return jsonify({"ok": False, "error": f"scripts folder not found: {dest_dir}. "
                         "Double-check the DFHack folder in Settings."}), 400
    dest = os.path.join(dest_dir, "dwarfwiki_export.lua")
    try:
        with io.open(EXPORT_SCRIPT_SRC, "r", encoding="utf-8") as f:
            content = f.read()
        with io.open(dest, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "installed_to": dest})


# ---------------------------------------------------------------------
# Slots. One per fort/save you want to track, mirroring the world picker.
# ---------------------------------------------------------------------
@fortress.route("/api/fortress/slots", methods=["GET"])
def api_fortress_slots():
    return jsonify(_slots())


@fortress.route("/api/fortress/slots", methods=["POST"])
def api_fortress_slots_create():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    data = _slots()
    slot_id = uuid.uuid4().hex[:10]
    data["slots"].append({"id": slot_id, "name": name, "created": time.time()})
    _save_json(SLOTS_FILE, data)
    _slot_dir(slot_id)
    return jsonify({"id": slot_id, "name": name})


@fortress.route("/api/fortress/slots/<slot_id>", methods=["DELETE"])
def api_fortress_slots_delete(slot_id):
    data = _slots()
    data["slots"] = [s for s in data["slots"] if s["id"] != slot_id]
    _save_json(SLOTS_FILE, data)
    return jsonify({"ok": True})


def _require_slot(slot_id):
    data = _slots()
    if not any(s["id"] == slot_id for s in data["slots"]):
        abort(404, f"no such fortress slot: {slot_id}")


# ---------------------------------------------------------------------
# Refresh. Shell out to dfhack-run, read the JSON it produces, store
# "current", append a headline entry to history.
# ---------------------------------------------------------------------
@fortress.route("/api/fortress/<slot_id>/refresh", methods=["POST"])
def api_fortress_refresh(slot_id):
    _require_slot(slot_id)
    s = _settings()
    dfhack_dir = s.get("dfhack_dir", "")
    dfhack_run = os.path.join(dfhack_dir, "dfhack-run.exe")

    if not os.path.isdir(dfhack_dir):
        return jsonify({"ok": False, "error": "Failed to get data",
                         "detail": f"DFHack folder not found: {dfhack_dir!r}. "
                                    "Check the path in Fortress → Settings."}), 502
    if not os.path.exists(dfhack_run):
        return jsonify({"ok": False, "error": "Failed to get data",
                         "detail": f"dfhack-run.exe not found at {dfhack_run!r}. "
                                    "If your DFHack build keeps it somewhere else "
                                    "(e.g. inside a 'hack' subfolder), point Settings "
                                    "at whichever folder directly contains dfhack-run.exe."}), 502

    out_path = os.path.join(_slot_dir(slot_id), "current.json")
    # Clear any stale file first, so a silent failure can't look like
    # success by leaving old data in place.
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass

    # stdout/stderr go to real temp files rather than subprocess pipes.
    # Some minimal Windows console tools crash when given a pipe instead
    # of a real console/file handle.
    stdout_path = os.path.join(_slot_dir(slot_id), "_dfhack_stdout.tmp")
    stderr_path = os.path.join(_slot_dir(slot_id), "_dfhack_stderr.tmp")
    try:
        with open(stdout_path, "wb") as out_f, open(stderr_path, "wb") as err_f:
            proc = subprocess.run(
                [dfhack_run, "dwarfwiki_export", out_path],
                stdout=out_f, stderr=err_f, timeout=30,
            )
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Failed to get data",
                         "detail": "dfhack-run didn't respond within 30s. Is Dwarf "
                                    "Fortress + DFHack actually running right now?"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": "Failed to get data",
                         "detail": f"Couldn't launch dfhack-run: {e}"}), 502

    def _read_tmp(p):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except OSError:
            return ""
    stdout = _read_tmp(stdout_path)
    stderr = _read_tmp(stderr_path)
    for p in (stdout_path, stderr_path):
        try:
            os.remove(p)
        except OSError:
            pass
    combined = "\n".join(x for x in (stdout, stderr) if x)

    if proc.returncode != 0:
        hint = ""
        # 3221225477 == 0xC0000005 (Windows access violation). Dfhack-run
        # crashed outright rather than reporting a normal error, which
        # (with no output at all) usually means it couldn't reach a
        # running game.
        if proc.returncode == 3221225477:
            hint = ("\n\ndfhack-run.exe crashed (Windows access violation) "
                     "instead of reporting a normal error. This usually means "
                     "it couldn't find a running DF + DFHack to talk to, "
                     "double-check the game is loaded into a fortress (not on "
                     "a menu) and try again. If it keeps happening with the "
                     "game definitely running, dfhack-run.exe and dfhack.dll "
                     "in that folder may be from mismatched versions.")
        return jsonify({"ok": False, "error": "Failed to get data",
                         "detail": f"dfhack-run exited with code {proc.returncode}.\n"
                                    f"{combined or '(no output)'}{hint}"}), 502

    if not os.path.exists(out_path):
        return jsonify({"ok": False, "error": "Failed to get data",
                         "detail": "dfhack-run reported success but no output file "
                                    "appeared, and produced no console output at all, "
                                    "including for built-in commands like \"help\" "
                                    "if you have tested that manually. That points at "
                                    "dfhack-run not reaching a running DFHack instance. "
                                    "Try DFHack's own in-game console (its hotkey inside "
                                    "the running game), if that responds normally but "
                                    "dfhack-run still doesn't, the issue is specifically "
                                    "in dfhack-run's connection, not DFHack itself.\n"
                                    f"dfhack-run said:\n{combined or '(nothing)'}"}), 502

    current = _load_json(out_path, None)
    if current is None:
        return jsonify({"ok": False, "error": "Failed to get data",
                         "detail": "The output file exists but isn't valid JSON, "
                                    "the export script may have crashed partway "
                                    "through. dfhack-run said:\n"
                                    f"{combined or '(nothing)'}"}), 502

    hist_path = os.path.join(_slot_dir(slot_id), "history.json")
    hist = _load_json(hist_path, [])
    hl = current.get("headline", {})
    hist.append({
        "ts": time.time(),
        "cur_year": current.get("meta", {}).get("cur_year"),
        "population": hl.get("population"),
        "item_count": hl.get("item_count"),
        "building_count": hl.get("building_count"),
    })
    if len(hist) > _HISTORY_CAP:
        hist = hist[-_HISTORY_CAP:]
    _save_json(hist_path, hist)

    return jsonify({"ok": True, "meta": current.get("meta", {}),
                     "warnings": current.get("_warnings", []),
                     "dfhack_output": combined})


@fortress.route("/api/fortress/<slot_id>/current", methods=["GET"])
def api_fortress_current(slot_id):
    _require_slot(slot_id)
    out_path = os.path.join(_slot_dir(slot_id), "current.json")
    current = _load_json(out_path, None)
    if current is None:
        return jsonify({"error": "Failed to get data"}), 404
    return jsonify(current)


@fortress.route("/api/fortress/<slot_id>/history", methods=["GET"])
def api_fortress_history(slot_id):
    _require_slot(slot_id)
    hist_path = os.path.join(_slot_dir(slot_id), "history.json")
    return jsonify(_load_json(hist_path, []))
