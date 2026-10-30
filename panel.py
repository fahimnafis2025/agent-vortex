"""panel.py - v22.7 BREACH TERMINAL (v22 + active-agent blink + telemetry activity graph).

Run:  python panel.py        (venv activated)
Then open: http://127.0.0.1:5000

Drives agent.py (must be the v8 file, named agent.py, in this folder)
through its GUI event bus: thinking / tool activity / answers stream
live, approvals become Approve/Deny cards, and the dock panel shows
live ollama + GPU state.
"""
import json
import queue
import re
import subprocess
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, request
from werkzeug.utils import secure_filename

import agent

app = Flask(__name__)

agent.GUI_MODE = True
agent.init_db()

CHAT = [{"role": "system", "content": agent.build_system_prompt()}]
BUSY = threading.Event()

PROJECT_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = PROJECT_DIR / "uploads"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def agent_worker(text):
    # v22.8: _TURN_RUNNING guards brain switches while a turn is live
    # (swapping unloads the model mid-inference).
    agent._TURN_RUNNING = True
    try:
        CHAT.append({"role": "user", "content": text})
        agent.log_episode("user", text)
        agent.log_chat("user", text)
        answer = agent.run_agent_turn(CHAT)
        agent.log_episode("assistant", answer)
        agent.log_chat("assistant", answer)
    except Exception as exc:  # never leave the UI hanging
        agent.emit("answer", {"text": "Error: " + str(exc)})
        agent.log_chat("assistant", "Error: " + str(exc))
    finally:
        agent._TURN_RUNNING = False
        BUSY.clear()
        agent.emit("idle", {})

def voice_worker(text):
    # v22.9: voice turn worker. Same logging as agent_worker, except a
    # barged turn logs NOTHING (no sentinel answer, no spoken "Stopped"):
    # the interrupting turn owns the log. Approval tiers are identical
    # because run_voice_turn IS run_agent_turn with streaming on.
    agent._TURN_RUNNING = True
    try:
        agent.voice_set_state("thinking")
        CHAT.append({"role": "user", "content": text})
        agent.log_episode("user", text)
        agent.log_chat("user", text)
        answer = agent.run_voice_turn(CHAT)
        if answer == agent._VOICE_BARGED:
            return
        agent.log_episode("assistant", answer)
        agent.log_chat("assistant", answer)
    except Exception as exc:  # never leave the UI hanging
        agent.emit("answer", {"text": "Error: " + str(exc)})
        agent.log_chat("assistant", "Error: " + str(exc))
    finally:
        agent._TURN_RUNNING = False
        BUSY.clear()
        agent.voice_set_state("listening")
        agent.emit("idle", {})


@app.route("/api/voice-health")
def voice_health():
    return jsonify(agent.voice_health_report())


@app.route("/api/voice-switch", methods=["GET"])
def voice_switch_get():
    # v22.9.1: SWITCH VOICE state for the panel button. The agent
    # owns the slot (persisted in voice/active-voice.json); the
    # panel only displays it and asks for a flip/set.
    return jsonify(agent.voice_slot_info())


@app.route("/api/voice-switch", methods=["POST"])
def voice_switch_post():
    # v22.9.1: no "slot" in the body flips to the other slot; an
    # explicit "slot" sets it; an unknown id is a 400 and
    # changes nothing. Applies from the next
    # spoken reply onward; CONVERSE on/off is unaffected.
    data = request.json or {}
    slot = data.get("slot")
    if slot is not None:
        # The agent owns the slot table: an unknown id returns
        # False and changes nothing (no slot list duplicated here).
        if not agent.voice_set_active_slot(str(slot)):
            return jsonify({"ok": False,
                            "error": "unknown voice slot"}), 400
        info = agent.voice_slot_info()
    else:
        info = agent.voice_switch()
    return jsonify(info)


@app.route("/api/voice-state", methods=["POST"])
def voice_state():
    ok = agent.voice_set_state((request.json or {}).get("state", ""))
    return jsonify({"ok": bool(ok)})


@app.route("/api/voice-barge", methods=["POST"])
def voice_barge():
    # Barge-in reuses the panel STOP path: STOP_EVENT aborts the turn
    # and the voice flag converts it to the barge sentinel.
    agent.VOICE_BARGE_EVENT.set()
    agent.stop_run()
    return jsonify({"ok": True})


@app.route("/api/voice-turn", methods=["POST"])
def voice_turn():
    data = request.json or {}
    text = str(data.get("message", "") or "").strip()
    if not text or BUSY.is_set():
        return jsonify({"ok": False})
    h = agent.voice_health_report()
    if not h.get("ok"):
        return jsonify({"ok": False, "error": "voice sidecar down"})
    BUSY.set()
    agent.emit("user", {"text": text})
    threading.Thread(target=voice_worker, args=(text,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/voice-tts", methods=["POST"])
def voice_tts():
    data = request.json or {}
    text = str(data.get("text", "") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty"}), 400
    audio = agent.voice_tts(text)
    if not audio:
        return jsonify({"ok": False, "error": "voice sidecar down"}), 503
    return Response(audio, mimetype="audio/wav")


@app.route("/api/voice-audio", methods=["POST"])
def voice_audio():
    # Mic chunks from the page (PCM16, v22.9.2) are fed to the
    # agent voice session; the sidecar contract accepts format webm
    # or pcm16, but live panel capture is PCM16 only now.
    import base64 as _b64
    data = request.json or {}
    try:
        chunk = _b64.b64decode(data.get("audio_b64", ""))
    except Exception:
        return jsonify({"ok": False, "error": "bad audio"}), 400
    fmt = str(data.get("format", "webm") or "webm")
    status, text = agent.voice_session_feed(chunk, fmt)
    return jsonify({"ok": True, "status": status, "text": text})




@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}
    text = str(data.get("message", "") or "").strip()
    attachments = data.get("attachments", [])
    if attachments is None:
        attachments = []
    if not isinstance(attachments, list):
        return jsonify({"ok": False, "error": "attachments must be a list"}), 400
    # Validate every attachment: relative uploads/ path only, no escapes.
    for att in attachments:
        if not isinstance(att, str) or not att.startswith("uploads/"):
            return jsonify({"ok": False, "error": "bad attachment path"}), 400
        parts = Path(att).parts
        if ".." in parts or Path(att).is_absolute():
            return jsonify({"ok": False, "error": "bad attachment path"}), 400
    if (not text and not attachments) or BUSY.is_set():
        return jsonify({"ok": False})
    if attachments:
        names = [Path(a).name for a in attachments]
        display = "\U0001f4ce " + ", ".join(names) + ("\n" + text if text else "")
        header_lines = ["[Attached files]"]
        for att in attachments:
            try:
                size = (PROJECT_DIR / att).stat().st_size
            except OSError:
                size = 0
            header_lines.append(
                '- ' + att + ' (' + str(size) + ' bytes) - use read_file("' + att + '") to read it.'
            )
        effective = text if text else "Please review the attached file(s)."
        worker_text = "\n".join(header_lines) + "\n\n" + effective
    else:
        display = text
        worker_text = text
    BUSY.set()
    agent.emit("user", {"text": display})
    threading.Thread(target=agent_worker, args=(worker_text,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/upload", methods=["POST"])
def upload():
    """Save one attached file into PROJECT_DIR/uploads/ (text/code files
    can then be read by the agent via read_file("uploads/<name>").
    Binary files (images/PDF) are saved but read_file cannot decode
    them - it reads UTF-8 text only."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "no file"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "no file"}), 400
    name = secure_filename(f.filename)
    if not name:
        return jsonify({"ok": False, "error": "bad filename"}), 400
    data = f.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return jsonify({"ok": False, "error": "file too large (max 20MB)"}), 413
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS_DIR / name
    if dest.exists():
        stem = Path(name).stem
        suffix = Path(name).suffix
        i = 1
        while dest.exists():
            dest = UPLOADS_DIR / (stem + "-" + str(i) + suffix)
            i += 1
    dest.write_bytes(data)
    return jsonify({"ok": True, "name": dest.name, "path": "uploads/" + dest.name, "size": len(data)})


@app.route("/api/events")
def events():
    def gen():
        while True:
            try:
                ev = agent.EVENT_QUEUE.get(timeout=20)
                yield "data: " + json.dumps(ev) + "\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    return Response(gen(), mimetype="text/event-stream")


@app.route("/api/approve", methods=["POST"])
def approve():
    agent.gui_resolve_approval((request.json or {}).get("approved", False))
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    """STOP button: kill the current run. Sets agent STOP_EVENT (the
    turn aborts at its next check and returns 'Stopped by user.') and
    unblocks any pending approval. BUSY is deliberately NOT cleared
    here: the worker thread's finally clears it when the turn actually
    aborts, which keeps exactly one worker thread running and avoids
    a duplicate 'Stopped' answer (the worker logs the stop as its
    turn answer). The panel JS hides the approval UI immediately on
    click, so the approval-prompt loop stops at once."""
    agent.stop_run()
    return jsonify({"ok": True})


SID_RE = re.compile(r"^\d{8}-\d{6}$")


def _chat_path(sid):
    if not SID_RE.match(sid or ""):
        return None
    p = agent.CHATS_DIR / (sid + ".jsonl")
    return p if p.is_file() else None


@app.route("/api/chats")
def chats():
    """List past chat sessions (newest first)."""
    out = []
    agent.CHATS_DIR.mkdir(parents=True, exist_ok=True)
    for p in sorted(agent.CHATS_DIR.glob("*.jsonl"), reverse=True):
        try:
            first = p.read_text(encoding="utf-8").splitlines()
            turns = len(first)
            preview = ""
            for line in first:
                d = json.loads(line)
                if d.get("role") == "user":
                    preview = d.get("text", "")[:60]
                    break
        except Exception:
            turns, preview = 0, ""
        out.append({"id": p.stem, "preview": preview, "turns": turns})
    return jsonify(out)


@app.route("/api/chats/<sid>")
def chat_view(sid):
    """Read-only transcript of one session."""
    p = _chat_path(sid)
    if p is None:
        return jsonify({"error": "not found"}), 404
    try:
        turns = [json.loads(l) for l in
                 p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        turns = []
    return jsonify({"id": sid, "turns": turns})


@app.route("/api/chats/<sid>", methods=["DELETE"])
def chat_delete(sid):
    """Delete a session transcript. Memories in memory/facts/ are NOT
    touched - deleting a chat deletes the transcript only."""
    p = _chat_path(sid)
    if p is None:
        return jsonify({"error": "not found"}), 404
    p.unlink()
    return jsonify({"ok": True})


@app.route("/api/distill", methods=["POST"])
def distill():
    """End the session: distill it into facts/lessons via save_memory."""
    def run():
        try:
            summary = agent.distill_session()
        except Exception as exc:
            summary = "Distillation failed: " + str(exc)
        agent.emit("distill_done", {"summary": str(summary)})
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


# v21.1: per-model param counts from `ollama show`, cached per process
# (models do not change params; a failed lookup caches None so a slow
# / missing ollama never blocks the 5s dock poll).
_DOCK_PARAMS_CACHE = {}


def _model_params(name):
    """Param count for one model, e.g. '14.8B'. None if unavailable."""
    if name in _DOCK_PARAMS_CACHE:
        return _DOCK_PARAMS_CACHE[name]
    val = None
    try:
        # v21.3: encoding audit - decode as UTF-8, never CP1252
        # (ollama show output with non-ASCII killed the reader thread
        # on 2026-10-16: UnicodeDecodeError byte 0x81, output lost).
        out = subprocess.run(["ollama", "show", name], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=5).stdout or ""
        m = re.search(r"parameters\s+([0-9.]+[BMK]?)", out, re.I)
        if m:
            val = m.group(1)
    except Exception:
        pass
    _DOCK_PARAMS_CACHE[name] = val
    return val


# v22.8: the ACTIVE_BRAIN panel card and its /api/brain routes are
# removed (the chip's mid-turn 409 bug was never fixed). Brain
# switching stays available in chat via the agent's switch tool;
# the panel no longer calls agent.list_brains / agent.switch_brain.


@app.route("/api/dock")
def dock():
    info = {"models": [], "all_models": [], "gpu": None}
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=10).stdout
        for line in out.strip().splitlines()[1:]:
            parts = line.split()
            if parts:
                info["all_models"].append({"name": parts[0], "size": parts[2] if len(parts) > 2 else ""})
    except Exception:
        pass
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=10).stdout
        for line in out.strip().splitlines()[1:]:
            parts = line.split()
            if parts:
                info["models"].append(parts[0])
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.total,utilization.gpu,"
             "temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10).stdout.strip()
        used, total, util, temp = [x.strip() for x in out.split(",")]
        info["gpu"] = {"used_mb": used, "total_mb": total, "util": util,
                       "temp_c": temp}
    except Exception:
        pass
        # v21.1: per-model detail from REAL data - agent MODEL_REGISTRY
    # (role / ctx / caps / strengths) + `ollama list` size + cached
    # `ollama show` params. NO per-model hardcoding here: any model
    # added to the dock gets a real description from the same source.
    # Registry keys are bare names (e.g. redcell-apex-mini); ollama
    # list names carry a tag (redcell-apex-mini:latest) - match by
    # stripping the tag, case-insensitive. A model in NEITHER source
    # gets an honest "Unknown - run ollama show <name>", NEVER a dash.
    details = {}
    reg = getattr(agent, "MODEL_REGISTRY", {}) or {}
    for _m in info["all_models"]:
        _name = _m["name"]
        _r = reg.get(_name)
        if _r is None:
            _base = _name.split(":")[0].lower()
            for _k, _v in reg.items():
                if _k.split(":")[0].lower() == _base:
                    _r = _v
                    break
        _params = _model_params(_name)
        _miss = "Unknown - run ollama show " + _name
        if _r is not None:
            _caps = []
            if _r.get("tools"):
                _caps.append("tools")
            if _r.get("vision"):
                _caps.append("vision")
            if _r.get("thinking"):
                _caps.append("thinking")
            _caps.extend(_r.get("strengths") or [])
            details[_name] = {
                "params": _params or _miss,
                "size": _m.get("size") or (
                    str(_r.get("vram_gb")) + " GB" if _r.get("vram_gb")
                    else "Unknown - run ollama list"),
                "caps": ", ".join(_caps) if _caps else "completion",
                "role": _r.get("role") or _miss,
                "ctx": str(_r.get("ctx")) if _r.get("ctx") else _miss,
            }
        else:
            details[_name] = {
                "params": _params or _miss,
                "size": _m.get("size") or "Unknown - run ollama list",
                "caps": _miss,
                "role": _miss,
                "ctx": _miss,
            }
    info["details"] = details
    return jsonify(info)



def _cpu_temp_c():
    """CPU temp in C. Tries OHM -> LHM -> MSAcpi WMI. None if unavailable.
    NZXT CAM has no public API, so it cannot be read directly - run
    LibreHardwareMonitor (free) to expose temps via WMI."""
    import subprocess
    # OHM / LHM: Sensor class, Temperature type, CPU Package / CPU Core
    for ns in ("root\\OpenHardwareMonitor", "root\\LibreHardwareMonitor"):
        try:
            ps = ("Get-CimInstance -Namespace " + ns + " -ClassName Sensor "
                  "| Where-Object { $_.SensorType -eq 'Temperature' -and ($_.Name -like '*CPU Package*' -or $_.Name -like '*CPU Core*') } "
                  "| Select-Object -First 1 -ExpandProperty Value")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=10).stdout.strip()
            if out:
                v = float(out)
                if 0 < v < 130:
                    return round(v, 1)
        except Exception:
            continue
    # MSAcpi: CurrentTemperature is tenths of Kelvin
    try:
        ps = ("Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
              "| Select-Object -First 1 -ExpandProperty CurrentTemperature")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=10).stdout.strip()
        if out:
            c = float(out) / 10.0 - 273.15
            if 0 < c < 130:
                return round(c, 1)
    except Exception:
        pass
    return None


@app.route("/api/stats")
def stats():
    """Real stats for telemetry widgets - never fake data."""
    out = {"facts": 0, "chats": 0, "jobs_done": 0, "jobs_running": 0, "strands": "unknown", "cpu_percent": None, "cpu_temp_c": None}
    try:
        out["facts"] = len(list((agent.PROJECT_DIR / "memory" / "facts").glob("*.md")))
    except Exception:
        pass
    try:
        out["chats"] = len(list(agent.CHATS_DIR.glob("*.jsonl")))
    except Exception:
        pass
    try:
        agent._jobs_mkdir()
        out["jobs_done"] = len(list((agent.JOBS_DIR / "done").glob("*.md")))
        out["jobs_running"] = len(list((agent.JOBS_DIR / "running").glob("*.json")))
    except Exception:
        pass
    try:
        import psutil
        out["cpu_percent"] = round(float(psutil.cpu_percent(interval=None)), 1)
    except Exception:
        out["cpu_percent"] = None
    try:
        out["cpu_temp_c"] = _cpu_temp_c()
    except Exception:
        out["cpu_temp_c"] = None
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8000/docs", method="GET")
        with urllib.request.urlopen(req, timeout=1) as r:
            out["strands"] = "up" if r.status < 500 else "down"
    except Exception:
        out["strands"] = "down"
    return jsonify(out)


@app.route("/api/tickets")
def tickets():
    """Ticket board: queued / running / done jobs for the Core.
    v20.3: adds started_at / ended_at (epoch seconds) + specialist so
    the linear activity timeline can draw REAL segments (no fake data).
    started_at = brief file mtime; ended_at = log mtime (running jobs:
    None = still going); done jobs only have an end (completion) time."""
    out = []
    try:
        agent._jobs_mkdir()
        for state in ("queue", "running"):
            d = agent.JOBS_DIR / state
            for f in sorted(d.glob("*.json"), reverse=True)[:20]:
                try:
                    b = json.loads(f.read_text(encoding="utf-8"))
                    goal = b.get("goal", "") or ""
                    m = re.search(r"Specialist:\s*([a-z_]+)", goal, re.I)
                    started = f.stat().st_mtime
                    ended = None
                    logf = d / (f.stem + ".log")
                    if logf.is_file():
                        ended = logf.stat().st_mtime
                    out.append({"id": b.get("id", f.stem), "status": state,
                                "goal": goal[:120],
                                "specialist": (m.group(1).lower() if m else ""),
                                "started_at": started, "ended_at": ended})
                except Exception:
                    pass
        d = agent.JOBS_DIR / "done"
        for f in sorted(d.glob("*.md"), reverse=True)[:20]:
            try:
                head = f.read_text(encoding="utf-8")[:1000]
                m = re.search(r"Specialist:\s*([a-z_]+)", head, re.I)
            except Exception:
                m = None
            out.append({"id": f.stem, "status": "done", "goal": "",
                        "specialist": (m.group(1).lower() if m else ""),
                        "started_at": None,
                        "ended_at": f.stat().st_mtime})
    except Exception as exc:
        out = [{"id": "error", "status": "error", "goal": str(exc),
                "specialist": "", "started_at": None, "ended_at": None}]
    return jsonify(out)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VORTEX // NETRUNNER HUD</title>
<script>(function(){var r=document.documentElement,k='vortex-theme';try{var s=localStorage.getItem(k);if(s)r.dataset.theme=s;}catch(e){}window.toggleTheme=function(){var dark=r.dataset.theme?r.dataset.theme==='dark':true;r.dataset.theme=dark?'light':'dark';try{localStorage.setItem(k,r.dataset.theme);}catch(e){}var b=document.getElementById('theme-btn');if(b)b.textContent=dark?'DARK':'LIGHT';};})();</script>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root[data-theme="light"]{
 --bg:#dde6df; --card:rgba(255,255,255,.88); --edge:#c9d6ce;
 --text:#0e2420; --dim:#445a54;
 --gold:#8A6D1A; --gold-dim:rgba(138,109,26,.18); --gold-hair:#8A6D1A;
 --yellow:#d81b60; --yellow-dim:rgba(216,27,96,.12);
 --red:#d81b60; --red-dim:rgba(216,27,96,.12);
}
:root{
 --bg:#000000; --card:rgba(10,10,10,.97); --edge:#5A6B85;
 --gold:#D4AF37; --gold-dim:rgba(212,175,55,.22); --gold-hair:#C9A227; 
 --yellow:#fcee0a; --yellow-dim:rgba(252,238,10,.2);
 --red:#ff003c; --red-dim:rgba(255,0,60,.2);
 --text:#FFFFFF; --dim:#B0BCCF;
 --fh:'Chakra Petch',sans-serif; --fb:'Inter',sans-serif; --fm:'JetBrains Mono',monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:rgba(0,0,0,.3)}
::-webkit-scrollbar-thumb{background:var(--gold);border-radius:0}

/* CRT Scanlines Overlay */
body::after{content:"";position:fixed;inset:0;background:linear-gradient(rgba(18,16,16,0) 50%,rgba(0,0,0,.15) 50%),linear-gradient(90deg,rgba(255,0,0,.03),rgba(0,255,0,.01),rgba(0,0,255,.03));background-size:100% 4px,3px 100%;pointer-events:none;z-index:9999}
body{background:var(--bg);color:var(--text);font:16px/1.5 var(--fb);min-height:100vh;overflow-x:hidden;text-transform:uppercase}

#bg-grid{position:fixed;inset:0;background-image:radial-gradient(rgba(212,175,55,.14) 1px,transparent 1.4px);background-size:22px 22px;opacity:.5;pointer-events:none;z-index:0}
#bg-vignette{position:fixed;inset:0;background:radial-gradient(circle at center,transparent 40%,rgba(255,0,60,.06) 100%);pointer-events:none;z-index:0}
body::before{content:'';position:fixed;inset:0;box-shadow:inset 0 0 120px rgba(255,0,60,.12),inset 0 0 24px rgba(255,0,60,.08);pointer-events:none;z-index:9998}

/* Glitch Boot Sequence */
#boot{position:fixed;inset:0;background:var(--red);z-index:10000;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;cursor:pointer;transition:opacity .2s;color:#000;font-family:var(--fm);box-shadow:inset 0 0 0 3px #000,inset 0 0 0 5px var(--gold);animation:bootHide .2s ease 3s forwards}
#boot.done{opacity:0;pointer-events:none;visibility:hidden}
@keyframes bootHide{to{opacity:0;visibility:hidden;pointer-events:none}}
#boot h1{font-size:48px;font-weight:700;letter-spacing:4px;margin-bottom:0;animation:glitch 1s linear infinite}
#boot p{font-size:14px;letter-spacing:2px;text-align:center;font-weight:700}
#boot-bar{width:min(400px,80vw);height:8px;background:rgba(0,0,0,.3);overflow:hidden;border:1px solid #000;clip-path:polygon(0 0,100% 0,100% calc(100% - 4px),calc(100% - 4px) 100%,0 100%)}
#boot-fill{height:100%;width:0%;background:#000;transition:width 1s cubic-bezier(0.8,0,0.2,1)}

@keyframes glitch{2%,64%{transform:translate(2px,0) skew(0deg)}4%,60%{transform:translate(-2px,0) skew(0deg)}62%{transform:translate(0,0) skew(5deg)}}

#app{position:relative;z-index:1;display:flex;height:100dvh;overflow:hidden}

#main{flex:1;max-width:1600px;margin:0 auto;padding:24px;display:flex;flex-direction:column;gap:20px;width:100%}

header{display:flex;align-items:center;gap:20px;padding:10px 0;border-bottom:2px solid var(--gold-dim)}
#core{width:60px;height:60px;flex-shrink:0}
#core .ring{transform-origin:50% 50%}
#core .spin{animation:spin 4s linear infinite}
#core .spin2{animation:spin 8s linear infinite reverse}
#core.working .spin{animation-duration:1.5s;stroke:var(--yellow)}
#core.thinking .spin{animation-duration:2.5s;stroke:var(--gold)}
#core.alert .spin{animation-duration:0.8s;stroke:var(--red)}
@keyframes spin{to{transform:rotate(360deg)}}

#logo{font-family:var(--fh);font-size:28px;font-weight:700;letter-spacing:2px;color:#fff}
#logo span{color:var(--red)}
#sub{font-family:var(--fm);font-size:12px;color:var(--gold);letter-spacing:4px}
#status-pill{font-family:var(--fm);font-size:14px;padding:6px 16px;border:1px solid var(--gold);background:var(--gold-dim);color:var(--gold);clip-path:polygon(10px 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%,0 10px);font-weight:700}
#status-pill.live{color:var(--yellow);border-color:var(--yellow);background:var(--yellow-dim)}
#hot-pill{display:none;font-family:var(--fm);font-size:12px;padding:6px 14px;border:1px solid var(--red);background:var(--red-dim);color:#fff;font-weight:700}
#hot-pill.show{display:block}
#theme-btn{background:transparent;color:var(--gold);border:1px solid var(--gold);padding:8px 16px;cursor:pointer;font-size:13px;font-family:var(--fm);font-weight:700}
#chats-btn{margin-left:auto;background:transparent;color:var(--gold);border:1px solid var(--gold);padding:8px 20px;cursor:pointer;font-size:14px;font-family:var(--fm);font-weight:700;clip-path:polygon(0 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%);transition:all .2s}
#chats-btn:hover{background:var(--gold);color:#000}

#grid{display:grid;grid-template-columns:repeat(12,1fr);gap:20px}
.card{position:relative;background:var(--card);border:1px solid var(--gold-hair);padding:20px;clip-path:polygon(14px 0,calc(100% - 14px) 0,100% 14px,100% calc(100% - 14px),calc(100% - 14px) 100%,14px 100%,0 calc(100% - 14px),0 14px);box-shadow:0 0 20px rgba(0,0,0,.5),0 0 32px rgba(255,0,60,.12);opacity:0;transform:translateY(15px);transition:opacity .3s,transform .3s}
.card.in{opacity:1;transform:none}
/* Decorative card corners */
.card::before{content:'';position:absolute;top:0;left:0;width:30px;height:30px;border-top:2px solid var(--gold);border-left:2px solid var(--gold);pointer-events:none}
.card::after{content:'';position:absolute;bottom:0;right:0;width:30px;height:30px;border-bottom:2px solid var(--gold);border-right:2px solid var(--gold);pointer-events:none}

.card h2{font-family:var(--fm);font-size:14px;font-weight:700;letter-spacing:2px;color:var(--gold);margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--gold-dim);padding-bottom:8px}
.live-tag{font-size:10px;color:#000;background:var(--gold);padding:2px 8px;clip-path:polygon(4px 0,100% 0,100% calc(100% - 4px),calc(100% - 4px) 100%,0 100%,0 4px)}

#activity-line{display:flex;align-items:center;gap:8px;font-family:var(--fm);font-size:12px;letter-spacing:1px;color:var(--gold);padding:6px 10px;margin-bottom:10px;border:1px solid var(--gold-dim);background:rgba(0,0,0,.35)}#activity-dot{width:8px;height:8px;background:var(--edge);clip-path:polygon(50% 0%,100% 50%,50% 100%,0% 50%);flex-shrink:0}#activity-line.act-on #activity-dot{background:var(--gold);animation:tlpulse 1.2s ease-in-out infinite}#banner{display:none;font-family:var(--fm);font-size:12px;letter-spacing:2px;text-align:center;padding:10px;margin-bottom:16px;clip-path:polygon(10px 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%,0 10px)}
#banner.attn{display:block;background:var(--red);color:#000;animation:glitch .5s infinite}
#banner.work{display:block;background:repeating-linear-gradient(45deg,var(--yellow),var(--yellow) 10px,#d4c600 10px,#d4c600 20px);color:#000;font-weight:700}
#banner.done{display:block;background:var(--gold);color:#000}


/* v22.4: was v22.3 min-height:560px (forced overflow on short windows). Chat still fills available space; floor is 320px; drag the corner to resize at will. */
#chat-card{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;max-height:none;overflow:hidden}
/* v22.4: drag-resize any panel (CSS-native handles, no JS). */
#dock-card,#telemetry-card{resize:vertical;overflow:hidden}
#sys-panels .card{resize:vertical;overflow:hidden}
#log{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:12px;padding-right:8px}

.msg{padding:14px 18px;max-width:90%;font-size:15px;line-height:1.5;animation:msgin .2s ease-out;clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px));font-family:var(--fb);text-transform:none}
@keyframes msgin{from{opacity:0;transform:translateX(-10px)}to{opacity:1;transform:none}}
.user{background:var(--yellow);color:#000;margin-left:auto;border-left:4px solid #000}
.user strong{color:#ff003c}
.agent{background:rgba(212,175,55,.05);border:1px solid var(--gold-dim);color:var(--text);border-left:4px solid var(--gold)}

.tl{margin:10px 0;border-left:2px solid var(--gold);padding-left:16px;display:flex;flex-direction:column;gap:6px}
.tl-row{font-family:var(--fm);font-size:12px;color:var(--dim);display:flex;gap:10px;align-items:center}
.tl-row .dot{width:8px;height:8px;background:var(--gold);clip-path:polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)}
.tl-row.done .dot{background:var(--yellow)}
.tl-row.failed .dot{background:var(--red)}

details.think{margin:10px 0;font-size:13px;border:1px solid var(--yellow-dim);background:rgba(252,238,10,.05);padding:10px 14px;clip-path:polygon(0 0,calc(100% - 10px) 0,100% 10px,100% 100%,0 100%)}
details.think summary{cursor:pointer;color:var(--yellow);font-family:var(--fm);font-weight:700}
details.think div{color:#a0aab5;font-family:var(--fm);font-size:12px;margin-top:10px;white-space:pre-wrap;text-transform:none}

#dock-card{grid-column:span 5}
.dock-row{display:flex;justify-content:space-between;align-items:center;font-size:14px;padding:10px 12px;border:1px solid transparent;cursor:pointer;transition:all .2s;font-family:var(--fm)}
.dock-row:hover{background:var(--gold-dim);border-color:var(--gold)}
.dock-row.sel{background:var(--yellow);color:#000;border-color:var(--yellow)}
.dock-row.sel .badge{color:#000;border-color:#000}
.dock-name{display:flex;gap:10px;align-items:center;font-weight:700}
.dot-on{width:8px;height:8px;background:var(--gold);box-shadow:0 0 10px var(--gold)}
.dock-row.sel .dot-on{background:#000;box-shadow:none}
.dot-off{width:8px;height:8px;background:var(--edge)}
.badge{font-size:10px;padding:2px 8px;border:1px solid var(--dim);color:var(--dim)}

#dock-detail{margin-top:12px;padding:12px;background:rgba(0,0,0,.5);border:1px solid var(--gold-dim);font-family:var(--fm);font-size:12px;color:var(--dim);display:none;text-transform:none}
#dock-detail b{color:var(--gold);text-transform:uppercase}

#telemetry-card{grid-column:span 5}
.gauge{margin-bottom:18px}
.gauge-top{display:flex;justify-content:space-between;font-family:var(--fm);font-size:13px;color:var(--gold);margin-bottom:8px}
.gauge-top b{color:#fff;font-size:15px}
.gauge-bar{height:14px;background:rgba(0,0,0,.5);border:1px solid var(--gold-dim);padding:2px;display:flex}
.gauge-fill{height:100%;background:var(--gold);width:0%;transition:width .3s}
.gauge-fill.warn{background:var(--yellow)}
.gauge-fill.bad{background:var(--red)}

.metric-row{display:flex;gap:20px;flex-wrap:wrap}
.metric{flex:1;min-width:90px;background:rgba(212,175,55,.03);border:1px solid var(--gold-dim);padding:10px;clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px))}
.metric .v{font-family:var(--fh);font-size:26px;font-weight:700;color:#fff}
.metric .k{font-family:var(--fm);font-size:11px;color:var(--gold);letter-spacing:1px}

#radar-card{grid-column:span 5}
#radar-legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px}
.radar-key{font-family:var(--fm);font-size:11px;display:flex;gap:8px;align-items:center;color:var(--text);cursor:pointer}
.radar-key .sw{width:12px;height:12px;clip-path:polygon(0 0,100% 0,100% calc(100% - 4px),calc(100% - 4px) 100%,0 100%,0 4px)}

#pipeline-card{grid-column:span 12}
#pipeline{display:flex;gap:16px}
.pipe-col{flex:1;background:rgba(0,0,0,.3);border:1px solid var(--edge);padding:16px;min-height:100px;clip-path:polygon(0 0,calc(100% - 15px) 0,100% 15px,100% 100%,0 100%)}
.pipe-col h3{font-family:var(--fm);font-size:12px;color:var(--gold);margin-bottom:12px;letter-spacing:2px;border-bottom:1px solid var(--gold-dim);padding-bottom:4px}
.pipe-col .item{font-family:var(--fm);font-size:12px;padding:8px 12px;background:var(--card);border:1px solid var(--edge);margin-bottom:8px;word-break:break-word;text-transform:none}
.pipe-col .item.run{border-left:4px solid var(--yellow);color:var(--yellow)}
.pipe-col .item.done{border-left:4px solid var(--gold)}

#feed-card{grid-column:span 6}
#feed{font-family:var(--fm);font-size:12px;color:var(--dim);display:flex;flex-direction:column;gap:8px;max-height:180px;overflow-y:auto;text-transform:none}
#feed div{border-bottom:1px solid rgba(255,255,255,.05);padding-bottom:4px}

#stats-card{grid-column:span 6}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.stat{background:transparent;border:1px solid var(--gold-dim);padding:14px;clip-path:polygon(0 0,calc(100% - 10px) 0,100% 10px,100% 100%,10px 100%,0 calc(100% - 10px));transition:all .2s;text-align:center}
.stat:hover{background:var(--gold-dim);border-color:var(--gold)}
.stat .v{font-family:var(--fh);font-size:28px;font-weight:700;color:var(--gold)}
.stat .k{font-family:var(--fm);font-size:10px;color:var(--dim)}

#ap-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:2999}
#ap-banner{display:none;position:fixed;top:0;left:0;right:0;z-index:3001;background:var(--red);color:#000;font-family:var(--fm);font-weight:700;font-size:14px;text-align:center;padding:10px 12px}
#ap-banner button{margin-left:12px;padding:6px 18px;border:2px solid #000;background:#000;color:var(--yellow);font-family:var(--fm);font-weight:700;cursor:pointer}
#approval{display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--red);border:2px solid #000;padding:28px;max-width:600px;width:92vw;z-index:3000;box-shadow:0 0 30px rgba(255,0,60,.5);clip-path:polygon(0 0,calc(100% - 20px) 0,100% 20px,100% 100%,20px 100%,0 calc(100% - 20px))}
#approval p{font-size:15px;color:#000;margin-bottom:16px;font-family:var(--fm);font-weight:700;text-transform:none}
#approval button{margin-right:12px;padding:10px 24px;border:2px solid #000;background:transparent;color:#000;font-family:var(--fm);font-size:14px;font-weight:700;cursor:pointer;clip-path:polygon(0 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%,0 10px)}
#btn-yes{background:#000;color:var(--yellow)} #btn-no{background:rgba(0,0,0,.2)}
#btn-yes:hover{background:var(--yellow);color:#000;border-color:#000}

#drawer{position:fixed;top:0;right:-480px;width:460px;max-width:94vw;height:100vh;background:rgba(9,10,15,.95);border-left:2px solid var(--gold);z-index:4000;display:flex;flex-direction:column;transition:right .3s cubic-bezier(0.8,0,0.2,1)}
#drawer.open{right:0}
#drawer-head{display:flex;justify-content:space-between;align-items:center;padding:20px;border-bottom:1px solid var(--gold-dim);font-family:var(--fh);font-size:18px;color:var(--gold)}
#drawer-close{background:none;border:0;color:var(--gold);font-size:32px;cursor:pointer;line-height:1}

#chat-list{flex:1;overflow-y:auto;padding:12px}
.chat-item{padding:12px;border:1px solid var(--gold-dim);margin:8px;background:rgba(0,0,0,.5);cursor:pointer;clip-path:polygon(0 0,calc(100% - 10px) 0,100% 10px,100% 100%,0 100%)}
.chat-item .cp{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:var(--fm);text-transform:none}
.chat-item .cm{font-size:11px;color:var(--gold);margin-top:6px;font-family:var(--fm)}
.chat-item .del{float:right;background:var(--red);color:#000;border:0;padding:4px 10px;font-size:12px;cursor:pointer;font-family:var(--fm);font-weight:700;clip-path:polygon(0 0,100% 0,100% calc(100% - 6px),calc(100% - 6px) 100%,0 100%,0 6px)}

#chat-view{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
#chat-back{align-self:flex-start;background:transparent;color:var(--gold);border:1px solid var(--gold);padding:6px 16px;cursor:pointer;font-family:var(--fm);font-weight:700;clip-path:polygon(0 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px)}
.ct{padding:12px 16px;font-size:14px;max-width:95%;font-family:var(--fm);text-transform:none;clip-path:polygon(0 0,calc(100% - 10px) 0,100% 10px,100% 100%,10px 100%,0 calc(100% - 10px))}
.ct.u{background:var(--yellow);color:#000;align-self:flex-end}
.ct.a{background:rgba(212,175,55,.05);border:1px solid var(--gold-dim);color:var(--text);align-self:flex-start}

#drawer-foot{padding:20px;border-top:1px solid var(--gold-dim)}
#distill-btn{width:100%;background:var(--gold);color:#000;border:0;padding:14px;cursor:pointer;font-size:14px;font-family:var(--fm);font-weight:700;clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px));text-transform:uppercase}

#bar{display:flex;gap:16px;padding:16px 0 0;position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--gold-dim);margin-top:auto;align-items:flex-end}
#in{flex:1;background:rgba(0,0,0,.5);border:1px solid var(--gold);color:var(--text);padding:16px 20px;font-size:16px;font-family:var(--fm);clip-path:polygon(0 0,calc(100% - 15px) 0,100% 15px,100% 100%,0 100%);resize:none;overflow-y:auto;max-height:140px;white-space:pre-wrap;word-wrap:break-word;overflow-wrap:break-word;line-height:1.5;min-height:54px}
#in:focus{outline:none;background:rgba(212,175,55,.05)}
#attach{background:transparent;color:var(--gold);border:1px solid var(--gold);padding:0 20px;min-height:54px;font-size:14px;cursor:pointer;letter-spacing:1px;font-weight:700;font-family:var(--fm);clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,0 100%);flex-shrink:0;white-space:nowrap}
#attach:hover{background:var(--gold);color:#000}
#attach:disabled{opacity:.4;cursor:default}
#attach-bar{display:flex;flex-wrap:wrap;gap:8px;padding:10px 0 0}
.attach-chip{display:inline-flex;align-items:center;gap:8px;background:rgba(212,175,55,.1);border:1px solid var(--gold-dim);color:var(--text);font-family:var(--fm);font-size:12px;padding:6px 10px;max-width:100%;text-transform:none}
.attach-chip span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:320px}
.attach-chip button{background:transparent;border:0;color:var(--gold);cursor:pointer;font-family:var(--fm);font-weight:700;font-size:14px;line-height:1;padding:0 2px}
#send{background:var(--red);color:#000;border:0;padding:0 36px;font-size:16px;cursor:pointer;letter-spacing:2px;font-weight:700;font-family:var(--fh);clip-path:polygon(15px 0,100% 0,100% calc(100% - 15px),calc(100% - 15px) 100%,0 100%,0 15px);transition:background .2s}
#send:hover{background:var(--yellow)}
#send:disabled{opacity:.4;background:var(--edge)}
#stop{background:#000;color:var(--red);border:2px solid var(--red);padding:0 28px;font-size:16px;cursor:pointer;letter-spacing:2px;font-weight:700;font-family:var(--fh);clip-path:polygon(15px 0,100% 0,100% calc(100% - 15px),calc(100% - 15px) 100%,0 100%,0 15px);transition:all .2s}
#stop:hover{background:var(--red);color:#000}


#timeline-card{padding:16px 20px}
#tl-head{display:flex;align-items:center;gap:16px;margin-bottom:10px;flex-wrap:wrap}
#tl-vram{display:flex;align-items:center;gap:10px;font-family:var(--fm);font-size:11px;color:var(--dim)}
#tl-vram-bar{width:160px;height:10px;background:rgba(0,0,0,.5);border:1px solid var(--gold-dim)}
#tl-vram-fill{height:100%;background:var(--gold);width:0%;transition:width .3s}
#tl-vram-fill.warn{background:var(--yellow)}#tl-vram-fill.bad{background:var(--red)}
#tl-win{font-family:var(--fm);font-size:11px;color:var(--dim);margin-left:auto}
#tl-empty{font-family:var(--fm);font-size:12px;color:var(--dim);text-align:center;padding:14px 0;display:none}
.tl-row{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.tl-row-label{width:170px;flex-shrink:0;font-family:var(--fm);font-size:11px;font-weight:700;color:var(--text);display:flex;gap:8px;align-items:center;cursor:pointer;background:transparent;border:1px solid transparent;padding:2px 6px;text-align:left}
.tl-row-label:hover{border-color:var(--gold)}
.tl-row-label.sel{border-color:var(--gold);background:rgba(212,175,55,.08)}
.tl-row-label .sw{width:10px;height:10px;flex-shrink:0;display:inline-block}
.tl-track{position:relative;flex:1;height:18px;background:rgba(0,0,0,.3);border:1px solid var(--edge)}
.tl-seg{position:absolute;top:2px;height:14px;min-width:4px;cursor:pointer}
.tl-seg.run{animation:tlpulse 1.2s ease-in-out infinite}
@keyframes tlpulse{50%{opacity:.55}}
.tl-now{position:absolute;top:-2px;bottom:-2px;width:2px;right:0;background:var(--red);z-index:2}
#tl-axis{display:flex;gap:10px;margin-top:4px}
#tl-axis .spacer{width:170px;flex-shrink:0}
#tl-axis-track{position:relative;flex:1;font-family:var(--fm);font-size:10px;color:var(--dim)}
#tl-axis-track span{position:absolute;transform:translateX(-50%)}
#tl-axis-track span.now{color:var(--red);font-weight:700;transform:translateX(-100%)}
#tl-clear{display:none;font-family:var(--fm);font-size:11px;background:transparent;border:1px solid var(--gold);color:var(--gold);padding:4px 10px;cursor:pointer}
@media(max-width:900px){.tl-row-label{width:110px;font-size:10px}}

@media(max-width:900px){#dock-card,#telemetry-card,#radar-card,#feed-card,#stats-card{grid-column:span 12}.stat-grid{grid-template-columns:repeat(2,1fr)}}

/* v21 BREACH TERMINAL */
#footer-bar{display:flex;align-items:center;gap:16px;padding:12px 0;border-top:1px solid var(--gold-hair);margin-top:4px}
.barcode{flex:1;height:16px;opacity:.55;background:repeating-linear-gradient(90deg,#fff 0 2px,transparent 2px 4px,#fff 4px 5px,transparent 5px 9px,#fff 9px 12px,transparent 12px 14px,#fff 14px 15px,transparent 15px 19px,#fff 19px 21px,transparent 21px 24px)}
.foot-bin{font-family:var(--fm);font-size:10px;color:var(--dim);opacity:.5;letter-spacing:2px}
.foot-tag{font-family:var(--fm);font-size:10px;color:var(--gold);letter-spacing:3px;white-space:nowrap}
.boot-bin{opacity:.3;font-size:10px;letter-spacing:3px;word-break:break-all;max-width:420px;text-align:center}
#boot-pct{font-size:16px}
.card h2::before{content:"";width:12px;height:12px;background:var(--gold);clip-path:polygon(0 0,100% 0,0 100%);flex-shrink:0;margin-right:10px}
.card h2:hover{animation:hglitch .35s steps(2,end) 2}
@keyframes hglitch{0%{text-shadow:2px 0 var(--red),-2px 0 var(--gold)}50%{text-shadow:-2px 0 var(--red),2px 0 var(--gold)}100%{text-shadow:none}}

/* v22 CHAT-FIRST: chat is the hero. Header + top strip (dock + telemetry)
   + big chat + collapsed secondary panels. All element IDs preserved,
   so existing JS keeps working unchanged. */
/* v22.4: was height:100dvh - the column cut off its own footer on short windows. min-height grows instead. */
#main{min-height:0;overflow:hidden}
#top-strip{display:flex;flex-wrap:wrap;gap:16px;align-items:stretch}
#top-strip .card{margin:0}
#top-strip #dock-card{flex:1 1 55%;min-width:320px}
#top-strip #telemetry-card{flex:1 1 38%;min-width:300px}
#dock-list{display:flex;flex-wrap:wrap;gap:8px}
#top-strip .dock-row{flex:0 1 auto;display:inline-flex;align-items:center;gap:8px;justify-content:flex-start;padding:8px 12px;font-size:12px;white-space:nowrap}
#top-strip .dock-name{gap:8px;font-size:12px}
#top-strip .gauge{margin-bottom:8px}
#top-strip .gauge-bar{height:10px}
#top-strip .metric-row{gap:8px}
#top-strip .metric{padding:8px 10px;min-width:0;flex:1 1 0}
/* v22.8 LIVE activity strip: slim full-width bar inside the top strip */
#top-strip #activity-card{flex:1 1 100%;min-width:0}
#activity-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}#voice-state{color:var(--gold);font-size:12px;letter-spacing:1px}#mic-live{color:#ff5a3c;font-size:11px;letter-spacing:1px;animation:tlpulse 1.2s ease-in-out infinite}#converse.on{outline:2px solid var(--gold)}#voice-switch.preset{outline:2px dashed var(--gold)}
#act-dot{width:10px;height:10px;background:var(--gold);flex:none}
#act-dot.busy{background:#ff003c;animation:actblink 1s steps(2) infinite}
@keyframes actblink{50%{opacity:.25}}
#act-step{font-family:var(--fm);font-size:14px;font-weight:700;letter-spacing:1px;color:var(--yellow);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#act-time{font-family:var(--fm);font-size:12px;color:var(--dim);letter-spacing:1px;margin-left:auto;white-space:nowrap}
#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:200;background:#0a0a0a;border:1px solid var(--gold);color:var(--yellow);font-family:var(--fm);font-size:13px;font-weight:700;letter-spacing:1px;padding:12px 24px;display:none;box-shadow:0 8px 32px rgba(0,0,0,.7)}
#toast.err{border-color:#ff003c;color:#ff003c}
#top-strip .metric .v{font-size:18px}

#in{height:72px;min-height:72px;max-height:72px}
#attach{min-height:72px}
#send,#stop{min-height:72px;display:flex;align-items:center;justify-content:center}
#sys-toggle{display:block;width:100%;background:transparent;color:var(--gold);border:1px solid var(--gold);padding:10px 16px;cursor:pointer;font-size:13px;font-family:var(--fm);font-weight:700;letter-spacing:2px;text-align:center;clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,0 100%)}
#sys-toggle:hover{background:var(--gold);color:#000}
#sys-panels{display:none}
#sys-panels.open{display:grid;grid-template-columns:repeat(12,1fr);gap:20px}
#sys-panels #timeline-card{grid-column:span 12}

/* v22.1 ACTIVE: blinking dock chip for the working agent + telemetry activity graph (real data only). */
@keyframes dockBlink{0%,100%{box-shadow:0 0 0 0 rgba(212,175,55,0);border-color:transparent}50%{box-shadow:0 0 14px 3px rgba(212,175,55,.75);border-color:var(--gold)}}
.dock-row.active{animation:dockBlink 1s ease-in-out infinite;border-color:var(--gold)}
@keyframes dockBlinkDot{0%,100%{opacity:.35;transform:scale(.8)}50%{opacity:1;transform:scale(1.35)}}
.dock-row.active .dock-name span{animation:dockBlinkDot 1s ease-in-out infinite}
#telemetry-graph-wrap{margin-top:10px}
#telemetry-graph{width:100%;height:56px;display:block;background:rgba(0,0,0,.45);border:1px solid var(--gold-dim)}
#telemetry-graph-meta{display:flex;align-items:center;gap:10px;margin-top:6px;font-family:var(--fm);font-size:10px;color:var(--dim);letter-spacing:1px}
#telemetry-live-dot{width:8px;height:8px;border-radius:50%;background:var(--red);display:inline-block;animation:telePulse 1s ease-in-out infinite;flex-shrink:0}
@keyframes telePulse{0%,100%{opacity:.3;transform:scale(.8)}50%{opacity:1;transform:scale(1.3)}}
.tele-legend{display:inline-flex;gap:8px;align-items:center}
.tele-legend i{display:inline-block;width:10px;height:3px}
#telemetry-graph-empty{display:none;text-align:center;font-family:var(--fm);font-size:11px;color:var(--dim);padding:16px 0;border:1px solid var(--gold-dim);background:rgba(0,0,0,.45)}
#sys-panels #stats-card .stat{padding:8px}
</style></head><body>
<div id="bg-grid"></div><div id="bg-vignette"></div>
<div id="boot"><h1 id="boot-text">BREACH PROTOCOL</h1><p>INITIALIZING DAEMONS...<br>BYPASSING ICE...</p><div id="boot-bar"><div id="boot-fill"></div></div><p id="boot-pct">LOADING 0%</p><p class="boot-bin">01011010 01000101 01010010 01001111 01000011 01001000 01000010 01010010 01000101 01000001 01000011 01001000</p><p style="color:rgba(0,0,0,0.5);margin-top:20px">[ CLICK TO OVERRIDE ]</p></div>
<script>(function(){var b=document.getElementById('boot');if(!b)return;function hide(){b.classList.add('done');}b.addEventListener('click',hide);setTimeout(hide,2000);})();</script>
<div id="app">
<div id="main">
<header><div><div id="logo">VORTEX <span>// SYS_CMD</span></div><div id="sub">LOCAL NETRUNNER OP &middot; 12GB VRAM</div></div><div id="status-pill">STANDBY</div><div id="hot-pill">🔥 IT'S GETTING HOT IN HERE</div><button id="theme-btn" onclick="toggleTheme()">LIGHT</button><button id="chats-btn">DATA LOGS</button></header>
<div id="top-strip">
<div class="card" id="dock-card"><h2>DAEMON_DOCK <span class="live-tag">ACTIVE</span></h2><div id="dock-list"></div><div id="dock-detail"></div></div>
<div class="card" id="telemetry-card"><h2>SYS_TELEMETRY <span class="live-tag">LIVE</span></h2>
<div class="gauge"><div class="gauge-top"><span>VRAM ALLOCATION</span><b id="vram-text">…</b></div><div class="gauge-bar"><div class="gauge-fill" id="vram-fill"></div></div></div>
<div class="metric-row"><div class="metric"><div class="v" id="gpu-util">…</div><div class="k">GPU_LOAD</div></div><div class="metric"><div class="v" id="gpu-temp">…</div><div class="k">THERMALS</div></div><div class="metric"><div class="v" id="cpu-util">…</div><div class="k">CPU_LOAD</div></div><div class="metric"><div class="v" id="cpu-temp">…</div><div class="k">CPU_TEMP</div></div><div class="metric"><div class="v" id="strands-status">…</div><div class="k">NETWORK</div></div></div><div id="telemetry-graph-wrap"><canvas id="telemetry-graph" width="600" height="56"></canvas><div id="telemetry-graph-empty">NO TELEMETRY DATA</div><div id="telemetry-graph-meta"><span id="telemetry-live-dot"></span><span>LIVE</span><span class="tele-legend"><span><i style="background:#D4AF37"></i> VRAM</span><span><i style="background:#ff003c"></i> GPU</span><span><i style="background:#6cb6ff"></i> CPU</span></span><span id="telemetry-updated" style="margin-left:auto">—</span></div></div>
</div>
<div class="card" id="activity-card"><h2>LIVE_ACTIVITY <span class="live-tag">LIVE</span></h2><div id="activity-bar"><span id="act-dot"></span><span id="act-step">STANDBY</span><span id="act-time"></span><span id="voice-state"></span><span id="mic-live" style="display:none">MIC LIVE</span></div></div>
</div>
<div class="card" id="chat-card"><h2>COMMS_LINK <span class="live-tag">SECURE</span></h2><div id="activity-line"><span id="activity-dot"></span><span id="activity-text">Ready</span></div><div id="banner"></div><div id="log"></div>
<div id="attach-bar" style="display:none"></div><div id="bar"><button id="attach" title="Attach file">📎 ATTACH</button><input type="file" id="file-picker" multiple style="display:none"><textarea id="in" rows="1" placeholder="> EXECUTE COMMAND..."></textarea><button id="stop" style="display:none">STOP</button><button id="converse">CONVERSE</button><button id="voice-switch" title="Switch voice">VOICE: 22</button><button id="send">TRANSMIT</button></div></div>
<button id="sys-toggle">SYSTEM PANELS ▸ EXPAND</button>
<div id="sys-panels">
<div class="card" id="timeline-card"><h2>ACTIVITY_TIMELINE <span class="live-tag">LIVE</span></h2><div id="tl-head"><div id="tl-vram">VRAM <div id="tl-vram-bar"><div id="tl-vram-fill"></div></div><span id="tl-vram-text">&hellip;</span></div><span id="tl-win">LAST 10 MIN &middot; NOW AT RIGHT</span><button id="tl-clear">CLEAR FILTER</button></div><div id="tl-rows"></div><div id="tl-empty">NO ACTIVITY IN LAST 10 MIN</div><div id="tl-axis"><span class="spacer"></span><div id="tl-axis-track"><span style="left:0%">-10 MIN</span><span style="left:25%">-7.5</span><span style="left:50%">-5</span><span style="left:75%">-2.5</span><span class="now" style="left:100%">NOW</span></div></div></div>
<div class="card" id="radar-card"><h2>MATRIX_CAPABILITIES</h2><svg id="radar" viewBox="0 0 220 220" style="width:100%;max-width:300px;margin:0 auto;display:block;"></svg><div id="radar-legend"></div></div>
<div class="card" id="pipeline-card"><h2>TASK_PIPELINE</h2><div id="pipeline"><div class="pipe-col"><h3>[ PENDING ]</h3><div id="pipe-queue"></div></div><div class="pipe-col"><h3>[ EXECUTING ]</h3><div id="pipe-running"></div></div><div class="pipe-col"><h3>[ RESOLVED ]</h3><div id="pipe-done"></div></div></div></div>
<div class="card" id="feed-card"><h2>TRACE_LOG</h2><div id="feed"></div></div>
<div class="card" id="stats-card"><h2>SYS_STATS</h2><div class="stat-grid"><div class="stat"><div class="v" id="st-facts">…</div><div class="k">DATABANKS</div></div><div class="stat"><div class="v" id="st-chats">…</div><div class="k">SESSIONS</div></div><div class="stat"><div class="v" id="st-jobs">…</div><div class="k">TASKS_DONE</div></div><div class="stat"><div class="v" id="st-model">…</div><div class="k">ACTIVE_DAEMON</div></div></div></div>
</div>
<div id="footer-bar"><span class="barcode"></span><span class="foot-bin">01010100 01010010 01000001 01000011 01000101</span><span class="foot-tag">BREACH TERMINAL // V22.9.2</span></div>
<div id="drawer"><div id="drawer-head"><strong>DATA LOGS</strong><button id="drawer-close">×</button></div><div id="chat-list"></div><div id="chat-view" style="display:none;"><button id="chat-back">← RETURN</button><div id="chat-turns"></div></div><div id="drawer-foot"><button id="distill-btn">EXTRACT MEMORY ENGRAM</button></div></div>
<div id="ap-overlay"></div><div id="toast"></div><div id="ap-banner"><span id="ap-banner-text"></span><button id="ap-banner-yes">AUTHORIZE</button><button id="ap-banner-no">BLOCK</button></div><div id="approval"><p id="ap-text"></p><button id="btn-yes">AUTHORIZE</button><button id="btn-no">BLOCK</button></div>
</div></div>
<script>
const log=document.getElementById('log'),inp=document.getElementById('in'),send=document.getElementById('send'),stopBtn=document.getElementById('stop'),pill=document.getElementById('status-pill'),banner=document.getElementById('banner');try{const tb=document.getElementById('theme-btn');if(tb)tb.textContent=document.documentElement.dataset.theme==='light'?'DARK':'LIGHT';}catch(e){}
let curAgent=null,curTl=null,lastSent=null;
function stickLog(){try{if(log.scrollHeight-log.scrollTop-log.clientHeight<80)log.scrollTop=log.scrollHeight;}catch(e){}}
function setStatus(s,cls){pill.textContent=s;pill.className=s==='STANDBY'?'':'live';pill.id='status-pill';try{const st={thinking:'think',working:'work',alert:'alert'}[cls]||'idle';document.body.dataset.st=st;}catch(e){}banner.className='';banner.style.display='none';if(s==='AUTH REQUIRED'){banner.className='attn';banner.textContent='⚠ WARNING — OVERRIDE REQUIRED';banner.style.display='block';}else if(s==='EXECUTING'){banner.className='work';banner.textContent='▸ BREACHING ICE — IN PROGRESS';banner.style.display='block';}else if(s==='STANDBY'){banner.className='done';banner.textContent='✓ OPERATION COMPLETE';banner.style.display='block';setTimeout(()=>{banner.style.display='none';},3000);}}
function add(html,cls){const d=document.createElement('div');d.className='msg '+cls;d.innerHTML=html;log.appendChild(d);stickLog();return d;}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function md(s){let h=esc(s);h=h.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');h=h.replace(/`([^`]+)`/g,'<code style="background:rgba(212,175,55,.1);padding:2px 6px;color:var(--gold);border:1px solid var(--gold-dim);">$1</code>');return h.replace(/\\n/g,'<br>');}
function ts(){return new Date().toTimeString().slice(0,8);}
/* v21.1 live activity line (Claude-style "-ing"): ONE always-visible
line in COMMS_LINK showing the CURRENT activity in present tense.
ADDITIVE ONLY - the [DONE]/[RUN] tool rows and the status pill are
untouched. Text derives from real SSE events; never invented. */
const ACTIVITY_MAP={get_tool:'Loading tools...',plan_tickets:'Planning tickets...',delegate:'Delegating...',confirm_plan:'Waiting for your approval...',inspect_handoff:'Verifying handoff...',plate_answer:'Plating answer...',web_search:'Searching the web...',web_fetch:'Fetching page...',read_file:'Reading file...',write_file:'Writing file...',list_files:'Listing files...',run_shell:'Running shell command...',desktop_screenshot:'Taking screenshot...',launch_app:'Launching app...',move_window:'Moving window...',move_window_to_monitor:'Moving window...',delete_file:'Deleting file...',clear_pending_jobs:'Clearing pending jobs...',save_memory:'Saving memory...',recall_memory:'Recalling memory...',get_time:'Checking time...',find_app:'Finding app...',windows_update_status:'Checking Windows Update...',list_windows:'Listing windows...',focus_window:'Focusing window...',close_window:'Closing window...',open_known_folder:'Opening folder...',browser_click:'Browsing...',browser_type:'Browsing...',browser_navigate:'Browsing...',browser_snapshot:'Browsing...',browser_js:'Browsing...',browser_op:'Browsing...',browser_open:'Browsing...',create_job:'Starting worker...',launch_job:'Starting worker...',ticket_status:'Checking ticket...',advisory_lookup:'Looking up advisory...',use_skill:'Loading skill...',expedite:'Routing...',orchestrate:'Orchestrating...',distill_session:'Extracting memory...'};
let approvalPending=false,lastActivityAt=Date.now(),activityText='Ready';
function setActivity(t){const el=document.getElementById('activity-text');if(el)el.textContent=t;const line=document.getElementById('activity-line');if(line)line.classList.toggle('act-on',t!=='Ready');activityText=t;lastActivityAt=Date.now();try{refreshActiveChip();}catch(e){}}
function activityForTool(name){return ACTIVITY_MAP[name]||('Running '+name+'...');}
function activityForTicket(d){const sp=d.specialist||'worker';const st=(d.status||'').toLowerCase();if(st==='waiting')return 'Waiting for '+sp+'...';if(st==='unloading')return 'Unloading '+sp+'...';if(st==='verifying')return 'Verifying handoff...';if(st==='done')return 'Verifying handoff...';if(st==='rework')return 'Reworking ticket...';if(st==='verified')return 'Handoff verified...';if(st==='running')return 'Working on ticket...';return 'Working on ticket...';}
setInterval(()=>{if(approvalPending)return;if(send.disabled&&activityText!=='Thinking...'&&Date.now()-lastActivityAt>3000)setActivity('Thinking...');},1000);

/* v22.1 ACTIVE-AGENT BLINK + TELEMETRY GRAPH. Real data only, general:
   works for ANY model in the dock (no hardcoded model names).
   Blink: running ticket's specialist -> badge (the dock's own badge
   taxonomy) -> matching chip (loaded one preferred); fallback while
   BUSY: loaded model, else first CORE chip (head chef). Cleared when
   idle (no running ticket + no activity ~5s) or on answer/idle/stop.
   Graph: one point per refresh() poll from /api/dock + /api/stats. */
let activeDockName=null;
window._lastRun=[];window._lastLoaded=[];
function dockBadgeFor(n){return n.includes('vl')||n.includes('moondream')?'OPTICS':n.includes('redcell')?'OSINT':n.includes('MFDoom')||n.includes('deepseek')?'NEURAL':n.includes('nomic')?'VECTOR':n.includes('dolphin')?'BYPASS':'CORE';}
const SPEC_BADGE={researcher:'NEURAL',osint:'OSINT',vision:'OPTICS',coder:'CORE',browser_op:'CORE',core:'CORE'};
function applyActiveChip(){document.querySelectorAll('.dock-row').forEach(row=>{row.classList.toggle('active',!!activeDockName&&row.dataset.name===activeDockName);});}
function resolveActiveChip(){
  const running=(window._lastRun||[]).filter(t=>t.status==='running');
  const loaded=window._lastLoaded||[];
  const chips=[...document.querySelectorAll('.dock-row')];
  const busy=running.length>0||(send.disabled&&!approvalPending&&activityText!=='Ready'&&Date.now()-lastActivityAt<5000);
  if(!busy)return null;
  for(const t of running){
    const badge=SPEC_BADGE[(t.specialist||'').toLowerCase()];
    if(!badge)continue;
    const byBadge=chips.filter(c=>dockBadgeFor(c.dataset.name)===badge);
    if(!byBadge.length)continue;
    const hit=byBadge.find(c=>loaded.includes(c.dataset.name))||byBadge[0];
    return hit.dataset.name;
  }
  if(loaded.length)return loaded[0];
  const core=chips.find(c=>dockBadgeFor(c.dataset.name)==='CORE');
  return core?core.dataset.name:null;
}
function refreshActiveChip(){activeDockName=resolveActiveChip();applyActiveChip();}
setInterval(refreshActiveChip,1000);
const teleHist={vram:[],gpu:[],cpu:[]};const TELE_MAX=60;
function pushTeleGraph(vram,gpu,cpu){
  teleHist.vram.push(vram);teleHist.gpu.push(gpu);teleHist.cpu.push(cpu);
  for(const k of ['vram','gpu','cpu']){while(teleHist[k].length>TELE_MAX)teleHist[k].shift();}
  const upd=document.getElementById('telemetry-updated');if(upd)upd.textContent=ts();
  drawTeleGraph();
}
function drawTeleGraph(){
  const cv=document.getElementById('telemetry-graph');const empty=document.getElementById('telemetry-graph-empty');
  if(!cv)return;
  const has=teleHist.vram.concat(teleHist.gpu,teleHist.cpu).some(v=>v!==null&&v!==undefined&&!isNaN(v));
  if(!has){cv.style.display='none';if(empty)empty.style.display='block';return;}
  cv.style.display='block';if(empty)empty.style.display='none';
  const ctx=cv.getContext('2d');if(!ctx)return;
  const W=cv.width,H=cv.height;
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle='rgba(212,175,55,.15)';ctx.lineWidth=1;
  for(const gy of [0.25,0.5,0.75]){ctx.beginPath();ctx.moveTo(0,H*gy);ctx.lineTo(W,H*gy);ctx.stroke();}
  const series=[['vram','#D4AF37'],['gpu','#ff003c'],['cpu','#6cb6ff']];
  for(const pair of series){
    const key=pair[0],color=pair[1];const pts=teleHist[key];if(!pts.length)continue;
    ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();let started=false;
    const step=W/(TELE_MAX-1);
    for(let i=0;i<pts.length;i++){
      const v=pts[i];if(v===null||v===undefined||isNaN(v)){started=false;continue;}
      const x=W-(pts.length-1-i)*step;
      const y=H-Math.max(0,Math.min(100,v))/100*H;
      if(!started){ctx.moveTo(x,y);started=true;}else{ctx.lineTo(x,y);}
    }
    ctx.stroke();
  }
}
let feedEntries=[],feedFilter=null;function renderFeed(){const f=document.getElementById('feed');f.innerHTML='';for(const e of feedEntries){if(feedFilter!==null&&e.row!==feedFilter)continue;const d=document.createElement('div');d.textContent='['+e.ts+'] '+e.txt;f.appendChild(d);if(f.children.length>=20)break;}}function feed(txt,row){feedEntries.unshift({txt:txt,row:(row===undefined?-1:row),ts:ts()});if(feedEntries.length>60)feedEntries.pop();renderFeed();}

const boot=document.getElementById('boot');document.getElementById('boot-fill').style.width='100%';try{var bp=document.getElementById('boot-pct');if(bp)bp.textContent='LOADING 100%';}catch(e){}
let bootDone=false;function endBoot(){if(bootDone)return;bootDone=true;boot.classList.add('done');document.querySelectorAll('.card').forEach((c,i)=>{setTimeout(()=>c.classList.add('in'),i*70);});}
boot.onclick=endBoot;setTimeout(endBoot,1800);

const RADAR_AXES=['REASONING','CODE','VISION','OSINT','TOOLS'];
const RADAR_DATA={'Qwen 14B':{vals:[7,8,1,5,10],color:'#ff003c'},'MFDoom R1':{vals:[9,6,1,5,9],color:'#D4AF37'},'REDCELL':{vals:[8,5,1,10,8],color:'#FF4D00'},'Qwen-VL 8B':{vals:[6,4,10,3,8],color:'#C9A227'}};
function radarPoints(vals){const cx=110,cy=110,R=84;return vals.map((v,i)=>{const a=(-90+i*72)*Math.PI/180,r=R*v/10;return (cx+r*Math.cos(a)).toFixed(1)+','+(cy+r*Math.sin(a)).toFixed(1);}).join(' ');}
function drawRadar(){const svg=document.getElementById('radar');let h='';for(let ring=1;ring<=5;ring++){const pts=RADAR_AXES.map((_,i)=>{const a=(-90+i*72)*Math.PI/180,r=84*ring/5;return (110+r*Math.cos(a)).toFixed(1)+','+(110+r*Math.sin(a)).toFixed(1);}).join(' ');h+='<polygon points="'+pts+'" fill="none" stroke="rgba(212,175,55,.15)" stroke-width="1"/>';}
 RADAR_AXES.forEach((ax,i)=>{const a=(-90+i*72)*Math.PI/180;h+='<line x1="110" y1="110" x2="'+(110+84*Math.cos(a)).toFixed(1)+'" y2="'+(110+84*Math.sin(a)).toFixed(1)+'" stroke="rgba(212,175,55,.2)"/><text x="'+(110+96*Math.cos(a)).toFixed(1)+'" y="'+(110+96*Math.sin(a)).toFixed(1)+'" fill="#7e8b99" font-size="9" font-family="JetBrains Mono" text-anchor="middle">'+ax+'</text>';});
 Object.entries(RADAR_DATA).forEach(([name,d])=>{h+='<polygon class="radar-poly" data-name="'+name+'" points="'+radarPoints(d.vals)+'" fill="'+d.color+'" fill-opacity=".15" stroke="'+d.color+'" stroke-width="2"/>';});
 svg.innerHTML=h;document.getElementById('radar-legend').innerHTML=Object.entries(RADAR_DATA).map(([n,d])=>'<span class="radar-key"><span class="sw" style="background:'+d.color+'"></span>'+n+'</span>').join('');}
drawRadar();


function rowForTicket(d){const sp=(d.specialist||'').toLowerCase();if(sp==='researcher')return 1;if(sp==='osint')return 2;if(sp==='vision')return 3;if(sp==='coder')return 4;if(sp==='browser_op')return 5;const g=((d.goal||'')+' '+sp).toLowerCase();if(g.includes('cve')||g.includes('security')||g.includes('osint')||g.includes('vuln')||g.includes('threat')||g.includes('breach'))return 2;if(g.includes('screenshot')||g.includes('vision')||g.includes('image')||g.includes('window')||g.includes('screen')||g.includes('ocr'))return 3;return 0;}
const ROWS=[['CORE','QWEN','#ff003c'],['RESEARCHER','MFDOOM','#D4AF37'],['OSINT','REDCELL','#FF4D00'],['VISION','QWEN-VL','#C9A227'],['CODER','QWEN','#E63946'],['BROWSER_OP','QWEN','#E8C547']];
const TL=(()=>{
  const WIN=600000,g=id=>document.getElementById(id);
  const EV=[],live={};
  try{JSON.parse(localStorage.getItem('tl-ev')||'[]').forEach(e=>{if(!e.e)e.e=0;if((e.e||Date.now())>Date.now()-WIN&&e.s>Date.now()-WIN)EV.push(e);});}catch(e){}
  setInterval(()=>{try{localStorage.setItem('tl-ev',JSON.stringify(EV));}catch(e){}},5000);
  function begin(key,row,meta){if(live[key])return;const e={key:key,row:row,s:Date.now(),e:0,meta:meta||{}};EV.push(e);live[key]=e;draw();}
  function endKey(key){const e=live[key];if(e){e.e=Date.now();delete live[key];draw();}}
  function endLabel(label){const keys=Object.keys(live);for(let i=keys.length-1;i>=0;i--){const e=live[keys[i]];if(e.meta&&e.meta.label===label){e.e=Date.now();delete live[keys[i]];draw();return;}}}
  function endAll(){Object.keys(live).forEach(k=>{live[k].e=Date.now();delete live[k];});draw();}
  function mergeTickets(tk){let changed=false;for(const t of tk||[]){if(!t.started_at&&!t.ended_at)continue;const key='tk:'+(t.id||'');const row=rowForTicket(t);const s=t.started_at?t.started_at*1000:(t.ended_at?t.ended_at*1000:0);const e=t.ended_at?t.ended_at*1000:0;if(!s)continue;const ex=EV.find(x=>x.key===key);if(ex){if(ex.s!==s||ex.e!==e){ex.s=s;if(e)ex.e=e;ex.row=row;changed=true;}}else if(s>Date.now()-WIN){EV.push({key:key,row:row,s:s,e:e,meta:{job_id:t.id||'',specialist:t.specialist||'',status:t.status||''}});changed=true;}}if(changed)draw();}
  function draw(){
    const now=Date.now();
    for(let i=EV.length-1;i>=0;i--){const e=EV[i];if((e.e&&e.e<now-WIN)||e.s<now-WIN)EV.splice(i,1);}
    const rowsEl=g('tl-rows');if(!rowsEl)return;
    let h='',any=false;
    for(let r=0;r<ROWS.length;r++){
      const evs=EV.filter(e=>e.row===r);
      if(r!==0&&evs.length===0)continue;
      any=true;
      const sel=feedFilter===r?' sel':'';
      let segs='<div class="tl-now" title="NOW"></div>';
      for(const e of evs){
        const end=e.e||now;
        let left=Math.max(0,(1-(now-e.s)/WIN)*100);
        let w=Math.max(0.6,(end-e.s)/WIN*100);
        if(left+w>100)w=100-left;
        const bg=(e.meta&&e.meta.cls==='ap')?'#ff003c':ROWS[r][2];
        const tip=[e.meta&&e.meta.job_id?('JOB '+e.meta.job_id):'',e.meta&&e.meta.specialist?('SPECIALIST '+e.meta.specialist):'',e.meta&&e.meta.status?('STATUS '+e.meta.status):'',new Date(e.s).toLocaleTimeString()+' - '+(e.e?new Date(e.e).toLocaleTimeString():'RUNNING')].filter(Boolean).join(' | ');
        segs+='<div class="tl-seg'+(!e.e?' run':'')+'" style="left:'+left.toFixed(2)+'%;width:'+w.toFixed(2)+'%;background:'+bg+'" title="'+esc(tip)+'"></div>';
      }
      h+='<div class="tl-row"><button class="tl-row-label'+sel+'" data-row="'+r+'"><span class="sw" style="background:'+ROWS[r][2]+'"></span>'+ROWS[r][0]+' - '+ROWS[r][1]+'</button><div class="tl-track">'+segs+'</div></div>';
    }
    rowsEl.innerHTML=h;
    g('tl-empty').style.display=any?'none':'block';
    rowsEl.querySelectorAll('.tl-row-label').forEach(b=>{b.onclick=()=>{const r=parseInt(b.dataset.row,10);if(feedFilter===r){feedFilter=null;}else{feedFilter=r;}document.querySelectorAll('.tl-row-label').forEach(x=>x.classList.remove('sel'));if(feedFilter!==null)b.classList.add('sel');g('tl-clear').style.display=feedFilter!==null?'block':'none';renderFeed();};});
  }
  setInterval(draw,1000);draw();
  function vram(usedGB,totalGB){const f=totalGB>0?Math.max(0,Math.min(1,usedGB/totalGB)):0;const fill=g('tl-vram-fill');if(fill){fill.style.width=(f*100).toFixed(1)+'%';fill.className=f>0.85?'bad':f>0.6?'warn':'';}const tx=g('tl-vram-text');if(tx)tx.textContent=usedGB.toFixed(1)+' / '+totalGB.toFixed(1)+' GB';}
  return{begin,endKey,endLabel,endAll,mergeTickets,vram};
})();
document.getElementById('tl-clear').onclick=()=>{feedFilter=null;document.querySelectorAll('.tl-row-label').forEach(x=>x.classList.remove('sel'));document.getElementById('tl-clear').style.display='none';renderFeed();};

const es=new EventSource('/api/events');
es.onmessage=e=>{
 const ev=JSON.parse(e.data),t=ev.type,d=ev.data||{};
 // v22.8: activity-strip dispatcher (same stream, no new endpoint).
 if(t==='user')actBegin('Thinking...');
 else if(t==='thinking')actStep('Thinking...');
 else if(t==='tool_call')actStep('TOOL: '+d.name);
 else if(t==='tool_result')actStep('TOOL '+d.name+' '+String(d.status||'done').toUpperCase());
 else if(t==='ticket')actStep('TASK '+(d.job_id||'')+' '+(d.status||''));
 else if(t==='approval')actStep('Waiting for your approval...');
 else if(t==='distill')actStep('Extracting memory...');
 else if(t==='voice_state')voiceState(d.state);
else if(t==='voice_sentence')voiceSpeak(d.text);
else if(t==='voice_barge')voiceOnBarge();
else if(t==='voice_partial')voicePartial(d.text);
else if(t==='voice_tts_fallback')toast('Voice fell back to preset voice',true);
else if(t==='voice_switch')voiceSwitchLabel(d);
else if(t==='answer'||t==='idle'||t==='stopped'||t==='distill_done'){actEnd();if(converseOn)voiceState('listening');}
 if(t==='user'){if(lastSent!==null&&d.text===lastSent){lastSent=null;setStatus('UPLOADING','thinking');}else{add(esc(d.text),'user');setStatus('UPLOADING','thinking');setActivity('Thinking...');}}
 else if(t==='thinking'){
   if(!curAgent)curAgent=add('','agent');
   const det=document.createElement('details');det.className='think';
   det.innerHTML='<summary>[ NEURAL_TRACE_ACTIVE ]</summary><div>'+esc(d.text)+'</div>';
   curAgent.appendChild(det);stickLog();setActivity('Thinking...');setStatus('PROCESSING','thinking');TL.begin('main',0);feed('Analyzing data...',0);
 }
 else if(t==='tool_call'){
   if(!curAgent)curAgent=add('','agent');
   if(!curTl){curTl=document.createElement('div');curTl.className='tl';curAgent.appendChild(curTl);}
   const row=document.createElement('div');row.className='tl-row';row.dataset.tool=d.name;
   row.innerHTML='<span class="dot"></span><span>'+ts()+'</span><span>[RUN] '+esc(d.name)+'</span>';
   curTl.appendChild(row);stickLog();setActivity(activityForTool(d.name));setStatus('EXECUTING','working');TL.begin('tool:'+d.name+'@'+Date.now(),0,{label:d.name});feed('Running script: '+d.name,0);
 }
 else if(t==='tool_result'){
   // v22.8 (G8): mark ONLY the latest unmarked matching row inside the
   // CURRENT turn's container (curTl). Results with no matching row
   // here are ignored - the old document-wide scan marked rows from
   // earlier turns, producing refusal rows on turns that never
   // ordered that tool.
   let row=null;
   if(curTl){const rows=curTl.querySelectorAll('.tl-row');for(let i=rows.length-1;i>=0;i--){const el=rows[i];if(el.dataset.tool===d.name&&!el.classList.contains('done')&&!el.classList.contains('failed')){row=el;break;}}}
   if(row){if(d.status==='refused'){row.classList.add('failed');row.querySelector('span:last-child').textContent='[REFUSED] '+d.name;}else if(d.status==='error'){row.classList.add('failed');row.querySelector('span:last-child').textContent='[FAILED] '+d.name;}else{row.classList.add('done');row.querySelector('span:last-child').textContent='[DONE] '+d.name;}}
   TL.endLabel(d.name);
 }
 else if(t==='answer'){
   if(!curAgent)curAgent=add('','agent');
   const p=document.createElement('div');p.innerHTML=md(d.text);curAgent.appendChild(p);
   curAgent=null;curTl=null;stickLog();window._lastRun=[];setActivity('Ready');approvalPending=false;setStatus('STANDBY','');TL.endAll();feed('Transmission complete',-1);
 }
 else if(t==='ticket'){
   if(!curAgent)curAgent=add('','agent');
   if(!curTl){curTl=document.createElement('div');curTl.className='tl';curAgent.appendChild(curTl);}
   const row=document.createElement('div');row.className='tl-row done';
   row.innerHTML='<span class="dot"></span><span>'+ts()+'</span><span>TASK '+(d.job_id||'')+' '+(d.status||'')+' '+(d.specialist||'')+'</span>';
   curTl.appendChild(row);stickLog();setActivity(activityForTicket(d));setStatus('EXECUTING','working');TL.begin('tk:'+(d.job_id||('ticket-'+Date.now())),rowForTicket(d),{job_id:d.job_id||'',specialist:d.specialist||'',status:d.status||'',label:'ticket'});feed('Task '+(d.job_id||'')+' '+(d.status||''),rowForTicket(d));
 }
 else if(t==='approval'){setActivity('Waiting for your approval...');approvalPending=true;setStatus('AUTH REQUIRED','alert');TL.begin('ap',0,{cls:'ap',label:'approval'});
   document.getElementById('ap-text').textContent='[ REQUIRED: '+d.kind+' ] '+d.detail;
   document.getElementById('ap-banner-text').textContent='APPROVAL REQUIRED - '+d.kind+': '+d.detail;
   document.getElementById('approval').style.display='block';document.getElementById('ap-overlay').style.display='block';document.getElementById('ap-banner').style.display='block';feed('Awaiting manual override: '+d.kind,0);
 }
 else if(t==='distill'){setActivity('Extracting memory...');setStatus('EXTRACTING','working');}
 else if(t==='distill_done'){add('✦ '+esc((d.summary||'done')),'agent');setActivity('Ready');setStatus('STANDBY','');}
 else if(t==='idle'){hideApproval();send.disabled=false;inp.disabled=false;inp.focus();const ab=document.getElementById('attach');if(ab)ab.disabled=false;stopBtn.style.display='none';window._lastRun=[];setActivity('Ready');approvalPending=false;setStatus('STANDBY','');TL.endAll();}
 else if(t==='stopped'){hideApproval();window._lastRun=[];setActivity('Ready');approvalPending=false;setStatus('STOPPED','');TL.endAll();}
};
function hideApproval(){document.getElementById('approval').style.display='none';document.getElementById('ap-overlay').style.display='none';document.getElementById('ap-banner').style.display='none';TL.endKey('ap');approvalPending=false;}
function approveIt(v){fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:v})});hideApproval();setActivity(v?'Thinking...':'Ready');setStatus(v?'EXECUTING':'STANDBY',v?'working':'');}
document.getElementById('btn-yes').onclick=()=>approveIt(true);
document.getElementById('ap-banner-yes').onclick=()=>approveIt(true);
document.getElementById('btn-no').onclick=()=>approveIt(false);
document.getElementById('ap-banner-no').onclick=()=>approveIt(false);
document.getElementById('ap-overlay').onclick=()=>{};
let attachedFiles=[];
const attachBtn=document.getElementById('attach'),filePicker=document.getElementById('file-picker'),attachBar=document.getElementById('attach-bar');
function renderAttach(){attachBar.innerHTML='';if(!attachedFiles.length){attachBar.style.display='none';return;}attachBar.style.display='flex';attachedFiles.forEach((f,idx)=>{const chip=document.createElement('span');chip.className='attach-chip';const label=document.createElement('span');label.textContent='📎 '+f.name;const rm=document.createElement('button');rm.type='button';rm.textContent='\u2715';rm.title='Remove attachment';rm.onclick=()=>{attachedFiles.splice(idx,1);renderAttach();};chip.appendChild(label);chip.appendChild(rm);attachBar.appendChild(chip);});}
if(attachBtn&&filePicker){attachBtn.onclick=()=>{if(!attachBtn.disabled)filePicker.click();};filePicker.onchange=async()=>{const files=Array.from(filePicker.files||[]);filePicker.value='';for(const file of files){try{const fd=new FormData();fd.append('file',file);const r=await fetch('/api/upload',{method:'POST',body:fd});const j=await r.json();if(j.ok){attachedFiles.push({name:j.name,path:j.path,size:j.size});}else{alert('Upload failed: '+(j.error||'unknown error'));}}catch(e){alert('Upload failed: '+e);}}renderAttach();inp.focus();};}
function go(){const v=inp.value.trim();if(!v&&!attachedFiles.length)return;const display=attachedFiles.length?('📎 '+attachedFiles.map(f=>f.name).join(', ')+(v?'\\n'+v:'')):v;const paths=attachedFiles.map(f=>f.path);attachedFiles=[];renderAttach();inp.value='';send.disabled=true;inp.disabled=true;if(attachBtn)attachBtn.disabled=true;stopBtn.style.display='';lastSent=display;add(esc(display),'user');setStatus('UPLOADING','thinking');setActivity('Thinking...');fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:v,attachments:paths})});}
stopBtn.onclick=()=>{fetch('/api/stop',{method:'POST'});hideApproval();setActivity('Stopping...');setStatus('STOPPING','');};
send.onclick=go;inp.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();go();}};

const DOCK_INFO={'redcell-apex-mini':{role:'OSINT DAEMON',caps:'RECON · INFILTRATION',str:'CVE EXPLOITS'},'MFDoom/deepseek-r1-tool-calling:14b':{role:'LOGIC ENGINE',caps:'TOOLS · NEURAL',str:'HEURISTICS'},'nomic-embed-text':{role:'VECTOR CORE',caps:'EMBEDDING',str:'MEMORY ACCESS'},'qwen3-vl:8b-instruct':{role:'KIROSHI OPTICS',caps:'VISION · OCR',str:'IMAGE PARSING'},'moondream':{role:'QUICK OPTICS',caps:'VISION (FAST)',str:'SCENE ID'},'dolphin3:8b':{role:'UNCENSORED',caps:'RAW OUTPUT',str:'ICE BYPASS'},'qwen3:14b':{role:'MASTER DAEMON',caps:'ORCHESTRATION',str:'CODE EXEC'}};
function dockInfoFor(n){return DOCK_INFO[n]||DOCK_INFO[n.split(':')[0]]||(Object.entries(DOCK_INFO).find(([k])=>k.toLowerCase()===n.toLowerCase())||[])[1]||{role:'UNCLASSIFIED',caps:'AWAITING DESIGNATION',str:'UNKNOWN'};}
async function refresh(){try{
 let _tv=null,_tg=null,_tc=null;
 const r=await fetch('/api/dock');const j=await r.json();window._dockDetails=j.details||{};
 const loaded=new Set(j.models||[]);window._lastLoaded=[...(j.models||[])];
 const el=document.getElementById('dock-list');
 el.innerHTML=(j.all_models||[]).map(m=>'<div class="dock-row" data-name="'+esc(m.name)+'"><span class="dock-name"><span class="'+(loaded.has(m.name)?'dot-on':'dot-off')+'"></span>'+esc(m.name.split(':')[0].slice(0,24))+'</span><span><span class="badge">'+dockBadgeFor(m.name)+'</span> <span style="color:var(--dim);font-size:11px;">'+esc(m.size||'')+'</span></span></div>').join('')||'<div style="color:var(--dim);">NO DAEMONS FOUND</div>';
 document.querySelectorAll('.dock-row').forEach(row=>{row.onclick=()=>{document.querySelectorAll('.dock-row').forEach(x=>x.classList.remove('sel'));row.classList.add('sel');const info=dockInfoFor(row.dataset.name);const det=document.getElementById('dock-detail');det.style.display='block';det.innerHTML='<b>'+esc(row.dataset.name)+'</b><br>CLASS: '+esc(info.role)+'<br>PROTOCOLS: '+esc(info.caps)+'<br>VECTORS: '+esc(info.str);};});
 if(j.gpu){const used=parseFloat(j.gpu.used_mb),total=parseFloat(j.gpu.total_mb);const pct=Math.round(used/total*100);const fill=document.getElementById('vram-fill');fill.style.width=pct+'%';fill.className='gauge-fill'+(pct>85?' bad':pct>60?' warn':'');document.getElementById('vram-text').textContent=(Math.round(used/102.4)/10)+'/'+(Math.round(total/102.4)/10)+' GB';document.getElementById('gpu-util').textContent=j.gpu.util+'%';_tv=pct;_tg=parseFloat(j.gpu.util);if(isNaN(_tg))_tg=null;document.getElementById('gpu-temp').textContent=j.gpu.temp_c+'°C';document.getElementById('st-model').textContent=(j.models[0]||'—').split(':')[0].slice(0,12);window._gpuTemp=parseFloat(j.gpu.temp_c);TL.vram(used/1024,total/1024);}
 const tr=await fetch('/api/tickets');const tk=await tr.json();TL.mergeTickets(tk);
 const q=tk.filter(t=>t.status==='queue'),run=tk.filter(t=>t.status==='running'),done=tk.filter(t=>t.status==='done');
 document.getElementById('pipe-queue').innerHTML=q.length?q.map(t=>'<div class="item">'+esc(t.id)+'</div>').join(''):'<div style="color:var(--dim);font-size:11px;">EMPTY QUEUE</div>';
 document.getElementById('pipe-running').innerHTML=run.length?run.map(t=>'<div class="item run">'+esc(t.id)+' · '+(t.goal?esc(t.goal.slice(0,40)):'')+'</div>').join(''):'<div style="color:var(--dim);font-size:11px;">STANDBY</div>';
 document.getElementById('pipe-done').innerHTML=done.slice(0,5).map(t=>'<div class="item done">'+esc(t.id)+'</div>').join('')||'<div style="color:var(--dim);font-size:11px;">NO DATA</div>';window._lastRun=tk;refreshActiveChip();
 const sr=await fetch('/api/stats');const st=await sr.json();
 document.getElementById('st-facts').textContent=st.facts;document.getElementById('st-chats').textContent=st.chats;document.getElementById('st-jobs').textContent=st.jobs_done;document.getElementById('strands-status').textContent=st.strands==='up'?'ONLINE':'OFFLINE';document.getElementById('cpu-util').textContent=(st.cpu_percent===null||st.cpu_percent===undefined)?'N/A':st.cpu_percent+'%';_tc=(st.cpu_percent===null||st.cpu_percent===undefined)?null:st.cpu_percent;document.getElementById('cpu-temp').textContent=(st.cpu_temp_c===null||st.cpu_temp_c===undefined)?'N/A':st.cpu_temp_c+'°C';const hot=(st.cpu_temp_c!==null&&st.cpu_temp_c!==undefined&&st.cpu_temp_c>70)||(window._gpuTemp!==undefined&&window._gpuTemp>70);document.getElementById('hot-pill').classList.toggle('show',!!hot);document.body.classList.toggle('hot',!!hot);pushTeleGraph(_tv,_tg,_tc);
}catch(e){}}
setInterval(refresh,5000);refresh();

const drawer=document.getElementById('drawer');
document.getElementById('chats-btn').onclick=()=>{drawer.classList.add('open');loadChats();};
document.getElementById('drawer-close').onclick=()=>drawer.classList.remove('open');
async function loadChats(){
 const r=await fetch('/api/chats');const list=await r.json();
 const el=document.getElementById('chat-list');el.style.display='block';
 document.getElementById('chat-view').style.display='none';
 el.innerHTML=list.length?'':'<div style="color:var(--dim);padding:12px;">NO ARCHIVED LOGS.</div>';
 list.forEach(c=>{
  const d=document.createElement('div');d.className='chat-item';
  d.innerHTML='<button class="del">PURGE</button><div class="cp">'+esc(c.preview||'(BLANK_RECORD)')+'</div><div class="cm">'+c.id+' · '+c.turns+' CYCLES</div>';
  d.querySelector('.cp').onclick=()=>viewChat(c.id);
  const del=d.querySelector('.del');
  del.onclick=(e)=>{e.stopPropagation();
   if(!del.classList.contains('arm')){del.classList.add('arm');del.textContent='CONFIRM?';setTimeout(()=>{del.classList.remove('arm');del.textContent='PURGE';},4000);}
   else{fetch('/api/chats/'+c.id,{method:'DELETE'}).then(loadChats);}};
  el.appendChild(d);
 });
}
async function viewChat(id){
 const r=await fetch('/api/chats/'+id);const j=await r.json();
 document.getElementById('chat-list').style.display='none';
 const v=document.getElementById('chat-view');v.style.display='flex';
 const t=document.getElementById('chat-turns');t.innerHTML='';
 (j.turns||[]).forEach(x=>{const d=document.createElement('div');d.className='ct '+(x.role==='user'?'u':'a');d.innerHTML=md(x.text||'');t.appendChild(d);});
}
document.getElementById('chat-back').onclick=loadChats;
document.getElementById('distill-btn').onclick=()=>{fetch('/api/distill',{method:'POST'});drawer.classList.remove('open');add('Extracting memory engram from current session...','agent');setStatus('EXTRACTING','working');};
document.getElementById('sys-toggle').onclick=()=>{var p=document.getElementById('sys-panels');var o=p.classList.toggle('open');document.getElementById('sys-toggle').textContent=o?'SYSTEM PANELS ▾ COLLAPSE':'SYSTEM PANELS ▸ EXPAND';};
/* v22.8 LIVE activity strip: current step + elapsed seconds during a turn,
   standby + last-turn duration when idle. Fed by the /api/events stream
   (dispatcher at the top of es.onmessage); no new endpoint. */
let actStart=null,actTimer=null,actLast=null;
function actTick(){const t=document.getElementById('act-time');if(!t)return;if(actStart){t.textContent=Math.floor((Date.now()-actStart)/1000)+'s';}}
function actBegin(step){actStart=Date.now();const s=document.getElementById('act-step');if(s)s.textContent=step;const d=document.getElementById('act-dot');if(d)d.classList.add('busy');if(!actTimer)actTimer=setInterval(actTick,1000);actTick();}
function actStep(step){if(!actStart)actBegin(step);else{const s=document.getElementById('act-step');if(s)s.textContent=step;}}
function actEnd(){let dur=null;if(actStart){dur=Math.floor((Date.now()-actStart)/1000);actLast=dur;actStart=null;}if(actTimer){clearInterval(actTimer);actTimer=null;}const d=document.getElementById('act-dot');if(d)d.classList.remove('busy');const s=document.getElementById('act-step');if(s)s.textContent='STANDBY';const t=document.getElementById('act-time');if(t)t.textContent=actLast!==null?('LAST TURN '+actLast+'s'):'';}
function toast(msg,isErr){const t=document.getElementById('toast');t.textContent=msg;if(isErr)t.classList.add('err');else t.classList.remove('err');t.style.display='block';clearTimeout(t._h);t._h=setTimeout(()=>{t.style.display='none';},4500);}

/* v22.9.2 VOICE converse mode: PCM capture, NOT MediaRecorder webm. Webm fragments fail ffmpeg decode (Invalid data found when processing input) because later chunks carry no webm header. PCM16 chunks are independent, downsampled to 16000 in the browser, and use the sidecar pcm16 path already verified by test_vad_detail.py.
/* v22.9 VOICE converse mode: panel mic -> /api/voice-audio -> voice
   turn -> /api/voice-tts playback. Text mode is untouched when the
   toggle is off. No audio is stored: chunks live in memory only. */
let converseOn=false,micStream=null,micRec=null,micCtx=null,micProc=null,micSrc=null,pcmAcc=[],pcmTimer=null,voiceQueue=[],voicePlaying=null;
function voiceState(s){if(!converseOn&&s!=='idle')return;const el=document.getElementById('voice-state');if(el)el.textContent=s==='idle'?'':('VOICE: '+s.toUpperCase());const mic=document.getElementById('mic-live');if(mic)mic.style.display=(converseOn&&s!=='idle')?'':'none';if(s==='listening'||s==='thinking'||s==='speaking')actStep('VOICE '+s.toUpperCase());}
function voicePartial(t){const el=document.getElementById('voice-state');if(el&&converseOn)el.textContent='VOICE: HEARD '+t.slice(0,40);}
function voiceSpeak(text){voiceQueue.push(text);voicePlayNext();}
async function voicePlayNext(){if(voicePlaying||!voiceQueue.length)return;const text=voiceQueue.shift();try{const r=await fetch('/api/voice-tts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text})});if(!r.ok){toast('Voice audio unavailable - answer shown as text',true);voicePlayNext();return;}const blob=await r.blob();const url=URL.createObjectURL(blob);const au=new Audio(url);voicePlaying=au;fetch('/api/voice-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({state:'speaking'})});au.onended=function(){URL.revokeObjectURL(url);voicePlaying=null;voicePlayNext();};au.onerror=function(){voicePlaying=null;voicePlayNext();};au.play().catch(function(){voicePlaying=null;voicePlayNext();});}catch(e){voicePlaying=null;voicePlayNext();}}
function voiceStopPlayback(){voiceQueue=[];if(voicePlaying){try{voicePlaying.pause();}catch(e){}voicePlaying=null;}}
function voiceOnBarge(){voiceStopPlayback();fetch('/api/stop',{method:'POST'});if(converseOn)voiceState('listening');}
async function voiceTurn(text){try{const r=await fetch('/api/voice-turn',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});const j=await r.json();if(!j.ok&&j.error){toast('Voice sidecar down - answering as text.',true);fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,attachments:[]})});}}catch(e){toast('Voice turn failed - answering as text.',true);fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,attachments:[]})});}}
async function voiceToggle(){const btn=document.getElementById('converse');if(converseOn){converseOn=false;try{if(pcmTimer)clearInterval(pcmTimer);}catch(e){}pcmTimer=null;try{if(micProc)micProc.disconnect();}catch(e){}try{if(micSrc)micSrc.disconnect();}catch(e){}try{if(micCtx)micCtx.close();}catch(e){}micCtx=null;micProc=null;micSrc=null;pcmAcc=[];if(micStream){micStream.getTracks().forEach(function(tr){tr.stop();});}micStream=null;micRec=null;voiceStopPlayback();fetch('/api/voice-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({state:'idle'})});voiceState('idle');btn.textContent='CONVERSE';btn.classList.remove('on');return;}try{const h=await fetch('/api/voice-health');const j=await h.json();if(!j.ok){toast('Voice sidecar is down - text mode. Start the sidecar, then flip CONVERSE again.',true);return;}}catch(e){toast('Voice sidecar is down - text mode. Start the sidecar, then flip CONVERSE again.',true);return;}try{micStream=await navigator.mediaDevices.getUserMedia({audio:true});}catch(e){toast('Microphone permission denied - voice mode off, text mode still works.',true);return;}converseOn=true;btn.textContent='CONVERSE ON';btn.classList.add('on');fetch('/api/voice-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({state:'listening'})});voiceState('listening');micCtx=new (window.AudioContext||window.webkitAudioContext)();micSrc=micCtx.createMediaStreamSource(micStream);micProc=micCtx.createScriptProcessor(4096,1,1);micProc.onaudioprocess=function(e){if(!converseOn)return;var input=e.inputBuffer.getChannelData(0);var sr=micCtx.sampleRate;var ratio=sr/16000;var outLen=Math.floor(input.length/ratio);for(var i=0;i<outLen;i++){var start=Math.floor(i*ratio);var end=Math.floor((i+1)*ratio);if(end<=start)end=start+1;var sum=0;for(var k=start;k<end&&k<input.length;k++)sum+=input[k];var avg=sum/(end-start);var s=Math.max(-1,Math.min(1,avg));pcmAcc.push(Math.round(s<0?s*32768:s*32767));}};micSrc.connect(micProc);micProc.connect(micCtx.destination);pcmTimer=setInterval(function(){if(!converseOn||!pcmAcc.length)return;var buf=new Int16Array(pcmAcc);pcmAcc=[];var bytes=new Uint8Array(buf.buffer);var binary='';for(var i=0;i<bytes.length;i++)binary+=String.fromCharCode(bytes[i]);var b64=btoa(binary);fetch('/api/voice-audio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({audio_b64:b64,format:'pcm16'})}).then(function(r){return r.json();}).then(function(j){if(j.status==='final'&&j.text){voiceTurn(j.text);}else if(j.status==='partial'&&j.text){voicePartial(j.text);}else if(j.status==='barge'){voiceOnBarge();}}).catch(function(){});},500);}
document.getElementById('converse').onclick=voiceToggle;
/* v22.9.1 SWITCH VOICE: distinct from the CONVERSE toggle.
   Flips the active TTS slot (22 <-> 28) and shows the
   current voice on the button. A slot with no sample shows
   (PRESET) and a dashed outline: honest preset fallback,
   never a silent pretend-clone. Applies from the next
   spoken reply onward; CONVERSE on/off is untouched. */
function voiceSwitchLabel(j){const btn=document.getElementById('voice-switch');if(!btn||!j)return;const label=j.label||j.slot||'';btn.textContent='VOICE: '+String(label).toUpperCase()+(j.preset_fallback?' (PRESET)':'');if(j.preset_fallback)btn.classList.add('preset');else btn.classList.remove('preset');btn.title=j.preset_fallback?('Voice '+label+' - sample missing, speaking with preset voice'):('Voice '+label);}
async function voiceSwitchRefresh(){try{const r=await fetch('/api/voice-switch');const j=await r.json();voiceSwitchLabel(j);}catch(e){}}
async function voiceSwitch(){try{const r=await fetch('/api/voice-switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});const j=await r.json();voiceSwitchLabel(j);if(j.preset_fallback)toast('Voice '+j.label+' has no sample yet - speaking with preset voice',true);}catch(e){toast('Voice switch failed',true);}}
document.getElementById('voice-switch').onclick=voiceSwitch;
voiceSwitchRefresh();
</script></body></html>
"""


@app.route("/")
def index():
    return PAGE


if __name__ == "__main__":
    print("Agent panel: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True)