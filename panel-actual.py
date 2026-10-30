"""panel.py - v17 REAL rework (Vortex layout + HUD + radar + boot).

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

from flask import Flask, Response, jsonify, request

import agent

app = Flask(__name__)

agent.GUI_MODE = True
agent.init_db()

CHAT = [{"role": "system", "content": agent.build_system_prompt()}]
BUSY = threading.Event()


def agent_worker(text):
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
        BUSY.clear()
        agent.emit("idle", {})


@app.route("/api/chat", methods=["POST"])
def chat():
    text = (request.json or {}).get("message", "").strip()
    if not text or BUSY.is_set():
        return jsonify({"ok": False})
    BUSY.set()
    agent.emit("user", {"text": text})
    threading.Thread(target=agent_worker, args=(text,), daemon=True).start()
    return jsonify({"ok": True})


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


@app.route("/api/dock")
def dock():
    info = {"models": [], "all_models": [], "gpu": None}
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True,
                             text=True, timeout=10).stdout
        for line in out.strip().splitlines()[1:]:
            parts = line.split()
            if parts:
                info["all_models"].append({"name": parts[0], "size": parts[2] if len(parts) > 2 else ""})
    except Exception:
        pass
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True,
                             text=True, timeout=10).stdout
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
            capture_output=True, text=True, timeout=10).stdout.strip()
        used, total, util, temp = [x.strip() for x in out.split(",")]
        info["gpu"] = {"used_mb": used, "total_mb": total, "util": util,
                       "temp_c": temp}
    except Exception:
        pass
    return jsonify(info)


@app.route("/api/stats")
def stats():
    """Real stats for telemetry widgets - never fake data."""
    out = {"facts": 0, "chats": 0, "jobs_done": 0, "jobs_running": 0, "strands": "unknown"}
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
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8000/docs", method="GET")
        with urllib.request.urlopen(req, timeout=1) as r:
            out["strands"] = "up" if r.status < 500 else "down"
    except Exception:
        out["strands"] = "down"
    return jsonify(out)


@app.route("/api/tickets")
def tickets():
    """Ticket board: queued / running / done jobs for the head chef."""
    out = []
    try:
        agent._jobs_mkdir()
        for state in ("queue", "running"):
            d = agent.JOBS_DIR / state
            for f in sorted(d.glob("*.json"), reverse=True)[:20]:
                try:
                    b = json.loads(f.read_text(encoding="utf-8"))
                    out.append({"id": b.get("id", f.stem), "status": state,
                                "goal": (b.get("goal", "") or "")[:120]})
                except Exception:
                    pass
        d = agent.JOBS_DIR / "done"
        for f in sorted(d.glob("*.md"), reverse=True)[:20]:
            out.append({"id": f.stem, "status": "done", "goal": ""})
    except Exception as exc:
        out = [{"id": "error", "status": "error", "goal": str(exc)}]
    return jsonify(out)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VORTEX // AGENT COMMAND</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
 --bg:#06080f; --card:rgba(255,255,255,.045); --edge:rgba(255,255,255,.09);
 --cyan:#00e5ff; --violet:#8b5cf6; --gold:#d4af37; --yellow:#fcee0a; --green:#00ffa3; --mint:#7dffc4; --amber:#ffb800; --red:#ff2244;
 --text:#eef2ff; --dim:#9aa3c7;
 --fh:'Space Grotesk',system-ui,sans-serif; --fb:'Inter',system-ui,sans-serif; --fm:'JetBrains Mono',ui-monospace,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:15px/1.6 var(--fb);min-height:100vh;overflow-x:hidden}
#bg-grid{position:fixed;inset:0;background-image:radial-gradient(rgba(0,229,255,.07) 1px,transparent 1px);background-size:26px 26px;pointer-events:none;z-index:0}
#bg-waves{position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.14}
.bg-blob{position:fixed;border-radius:50%;filter:blur(100px);opacity:.28;pointer-events:none;z-index:0}
#b1{width:520px;height:520px;background:#1e1b4b;top:-160px;right:-120px}
#b2{width:420px;height:420px;background:#083344;bottom:-140px;left:-100px}
#boot{position:fixed;inset:0;background:#030405;z-index:100;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;cursor:pointer;transition:opacity .4s}
#boot.done{opacity:0;pointer-events:none}
#boot svg{width:min(560px,90vw);height:220px}
#boot .wave{fill:none;stroke:rgba(125,255,196,.55);stroke-width:1.2;stroke-dasharray:600;stroke-dashoffset:600;animation:draw 1.2s ease forwards}
#boot .wave:nth-child(2){animation-delay:.15s;stroke:rgba(125,255,196,.35)}
#boot .wave:nth-child(3){animation-delay:.3s;stroke:rgba(125,255,196,.2)}
@keyframes draw{to{stroke-dashoffset:0}}
#boot h1{font-family:var(--fh);font-size:34px;font-weight:600;color:var(--mint);letter-spacing:1px}
#boot p{font-family:var(--fm);font-size:11px;color:#5a8a72;letter-spacing:2px;text-align:center}
#boot-bar{width:min(360px,80vw);height:3px;background:rgba(255,255,255,.1);border-radius:99px;overflow:hidden}
#boot-fill{height:100%;width:0%;background:var(--mint);transition:width 1.4s linear}
#app{position:relative;z-index:1;display:flex;min-height:100vh}
#nav{width:64px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;gap:8px;padding:16px 0;border-right:1px solid var(--edge);background:rgba(255,255,255,.02);position:sticky;top:0;height:100vh}
.nav-btn{width:44px;height:44px;border-radius:12px;border:1px solid transparent;background:transparent;color:var(--dim);cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;transition:all .15s}
.nav-btn:hover{background:rgba(255,255,255,.06);color:var(--text)}
.nav-btn.active{background:rgba(0,229,255,.12);border-color:rgba(0,229,255,.35);color:var(--cyan)}
#main{flex:1;max-width:1440px;margin:0 auto;padding:16px;display:flex;flex-direction:column;gap:16px;width:100%}
header{display:flex;align-items:center;gap:14px;padding:2px 4px}
#core{width:52px;height:52px;flex-shrink:0}
#core .ring{transform-origin:50% 50%}
#core .spin{animation:spin 8s linear infinite}
#core .spin2{animation:spin 14s linear infinite reverse}
#core .pulse{animation:pulse 2s ease-in-out infinite}
#core.working .spin{animation-duration:3s}
#core.working .pulse{animation-duration:.8s}
#core.thinking .spin{animation-duration:5s}
#core.alert .spin{animation-duration:1.2s}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
#logo{font-family:var(--fh);font-size:20px;font-weight:700;letter-spacing:-.5px}
#logo span{color:var(--cyan)}
#sub{font-family:var(--fm);font-size:10px;color:var(--dim);letter-spacing:2px}
#status-pill{font-family:var(--fm);font-size:11px;padding:5px 12px;border-radius:99px;border:1px solid var(--edge);background:var(--card);color:var(--dim)}
#status-pill.live{color:var(--green);border-color:rgba(0,255,163,.35)}
#chats-btn{margin-left:auto;background:var(--card);color:var(--text);border:1px solid var(--edge);border-radius:10px;padding:8px 14px;cursor:pointer;font-size:13px;font-weight:500}
#grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}
.card{position:relative;background:var(--card);border:1px solid var(--edge);border-radius:16px;padding:16px;backdrop-filter:blur(14px) saturate(140%);box-shadow:0 8px 32px rgba(0,0,0,.3),inset 0 1px 0 rgba(255,255,255,.08);opacity:0;transform:translateY(10px);transition:opacity .4s,transform .4s,box-shadow .15s}
.card.in{opacity:1;transform:none}
.card:hover{box-shadow:0 12px 40px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.12)}
.card::before,.card::after{content:'';position:absolute;width:14px;height:14px;border:1.5px solid var(--gold);opacity:.7;pointer-events:none}
.card::before{top:-1px;left:-1px;border-right:0;border-bottom:0;border-top-left-radius:16px}
.card::after{bottom:-1px;right:-1px;border-left:0;border-top:0;border-bottom-right-radius:16px}
.card h2{font-family:var(--fh);font-size:13px;font-weight:600;letter-spacing:.5px;color:var(--dim);margin-bottom:12px;display:flex;justify-content:space-between;align-items:center}
.live-tag{font-family:var(--fm);font-size:10px;color:var(--green);border:1px solid rgba(0,255,163,.35);padding:2px 6px;border-radius:99px}
#banner{display:none;font-family:var(--fm);font-size:12px;letter-spacing:2px;text-align:center;padding:8px;border-radius:8px;margin-bottom:12px}
#banner.attn{display:block;background:rgba(255,34,68,.15);border:1px solid var(--red);color:#ffb3c4}
#banner.work{display:block;background:rgba(252,238,10,.1);border:1px solid rgba(252,238,10,.5);color:var(--yellow)}
#banner.done{display:block;background:rgba(0,255,163,.1);border:1px solid rgba(0,255,163,.4);color:var(--mint)}
#chat-card{grid-column:span 7;grid-row:span 2;display:flex;flex-direction:column;min-height:540px}
#log{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding-right:4px}
.msg{padding:10px 14px;border-radius:12px;max-width:88%;font-size:14px;line-height:1.6;animation:msgin .3s ease}
@keyframes msgin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.user{background:rgba(0,229,255,.1);border:1px solid rgba(0,229,255,.25);margin-left:auto;white-space:pre-wrap}
.agent{background:rgba(255,255,255,.04);border:1px solid var(--edge);white-space:pre-wrap}
.tl{margin:8px 0;border-left:2px solid var(--cyan);padding-left:12px;display:flex;flex-direction:column;gap:5px}
.tl-row{font-family:var(--fm);font-size:11px;color:var(--dim);display:flex;gap:8px;align-items:center}
.tl-row .dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);flex-shrink:0}
.tl-row.done .dot{background:var(--green)}
details.think{margin:8px 0;font-size:13px;border:1px dashed rgba(255,184,0,.4);border-radius:10px;padding:8px 12px}
details.think summary{cursor:pointer;color:var(--amber);font-family:var(--fm);font-size:11px}
details.think div{color:#b8b8d0;font-family:var(--fm);font-size:12px;margin-top:8px;white-space:pre-wrap}
#dock-card{grid-column:span 5}
.dock-row{display:flex;justify-content:space-between;align-items:center;font-size:13px;padding:8px 10px;border:1px solid transparent;border-radius:10px;cursor:pointer;transition:all .15s}
.dock-row:hover{background:rgba(255,255,255,.05);border-color:var(--edge)}
.dock-row.sel{background:rgba(0,229,255,.08);border-color:rgba(0,229,255,.35)}
.dock-name{font-family:var(--fm);font-size:12px;display:flex;gap:8px;align-items:center}
.dot-on{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green)}
.dot-off{width:8px;height:8px;border-radius:50%;background:#3a3f55}
.badge{font-family:var(--fm);font-size:10px;padding:2px 6px;border-radius:99px;border:1px solid var(--edge);color:var(--dim)}
.badge.y{color:var(--yellow);border-color:rgba(252,238,10,.4)}
#dock-detail{margin-top:10px;padding:10px 12px;border:1px solid var(--edge);border-radius:10px;font-family:var(--fm);font-size:11px;color:var(--dim);display:none}
#dock-detail b{color:var(--text)}
#telemetry-card{grid-column:span 5}
.gauge{margin-bottom:14px}
.gauge-top{display:flex;justify-content:space-between;font-family:var(--fm);font-size:12px;color:var(--dim);margin-bottom:6px}
.gauge-top b{color:var(--text);font-size:14px}
.gauge-bar{height:10px;background:rgba(255,255,255,.08);border-radius:99px;overflow:hidden}
.gauge-fill{height:100%;background:linear-gradient(90deg,var(--cyan),var(--violet));border-radius:99px;transition:width .5s}
.gauge-fill.warn{background:linear-gradient(90deg,var(--amber),#ff6b00)}
.gauge-fill.bad{background:linear-gradient(90deg,var(--red),#ff6b00)}
.metric-row{display:flex;gap:16px;flex-wrap:wrap}
.metric{flex:1;min-width:90px}
.metric .v{font-family:var(--fh);font-size:22px;font-weight:700}
.metric .k{font-size:11px;color:var(--dim);letter-spacing:.5px}
#radar-card{grid-column:span 5}
#radar-legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.radar-key{font-family:var(--fm);font-size:10px;display:flex;gap:6px;align-items:center;color:var(--dim);cursor:pointer}
.radar-key .sw{width:10px;height:10px;border-radius:2px}
#pipeline-card{grid-column:span 12}
#pipeline{display:flex;gap:12px}
.pipe-col{flex:1;background:rgba(255,255,255,.03);border:1px solid var(--edge);border-radius:12px;padding:12px;min-height:90px}
.pipe-col h3{font-family:var(--fm);font-size:11px;color:var(--dim);margin-bottom:8px;letter-spacing:1px}
.pipe-col .item{font-family:var(--fm);font-size:11px;padding:6px 8px;border-radius:8px;background:rgba(255,255,255,.04);margin-bottom:6px;word-break:break-word}
.pipe-col .item.run{border-left:3px solid var(--yellow);animation:pulse 1.5s infinite}
.pipe-col .item.done{border-left:3px solid var(--green)}
#feed-card{grid-column:span 6}
#feed{font-family:var(--fm);font-size:12px;color:var(--dim);display:flex;flex-direction:column;gap:6px;max-height:180px;overflow-y:auto}
#stats-card{grid-column:span 6}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat{background:rgba(255,255,255,.03);border:1px solid var(--edge);border-radius:12px;padding:12px;transition:transform .15s}
.stat:hover{transform:translateY(-2px)}
.stat .v{font-family:var(--fh);font-size:20px;font-weight:700}
.stat .k{font-size:11px;color:var(--dim)}
#approval{display:none;position:fixed;bottom:110px;left:50%;transform:translateX(-50%);background:#1a0a0a;border:1px solid var(--red);border-radius:16px;padding:16px 20px;max-width:520px;z-index:30;box-shadow:0 16px 48px rgba(0,0,0,.5)}
#approval p{font-size:13px;color:#ffb3c4;margin-bottom:12px;font-family:var(--fm);word-break:break-word}
#approval button{margin-right:8px;padding:8px 18px;border:0;border-radius:10px;font-size:13px;cursor:pointer;font-weight:600}
#btn-yes{background:var(--yellow);color:#000} #btn-no{background:rgba(255,255,255,.1);color:var(--text)}
#drawer{position:fixed;top:0;right:-430px;width:410px;max-width:94vw;height:100vh;background:#0e1220;border-left:1px solid var(--edge);z-index:40;display:flex;flex-direction:column;transition:right .25s}
#drawer.open{right:0}
#drawer-head{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid var(--edge);font-family:var(--fh);font-size:14px}
#drawer-close{background:none;border:0;color:var(--dim);font-size:24px;cursor:pointer}
#chat-list{flex:1;overflow-y:auto;padding:8px}
.chat-item{padding:10px 12px;border:1px solid var(--edge);border-radius:10px;margin:8px;background:rgba(255,255,255,.03);cursor:pointer}
.chat-item .cp{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-item .cm{font-size:12px;color:var(--dim);margin-top:4px;font-family:var(--fm)}
.chat-item .del{float:right;background:rgba(255,34,68,.15);color:#ff8ba0;border:1px solid rgba(255,34,68,.4);border-radius:6px;padding:2px 8px;font-size:12px;cursor:pointer;font-family:var(--fm)}
.chat-item .del.arm{background:#7f1d1d;color:#fff}
#chat-view{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
#chat-back{align-self:flex-start;background:var(--cyan);color:#000;border:0;border-radius:8px;padding:4px 10px;cursor:pointer;font-family:var(--fm);font-weight:700}
.ct{padding:8px 12px;border-radius:10px;font-size:14px;max-width:95%}
.ct.u{background:rgba(0,229,255,.1);border:1px solid rgba(0,229,255,.25);align-self:flex-end}
.ct.a{background:rgba(255,255,255,.04);border:1px solid var(--edge);align-self:flex-start}
#drawer-foot{padding:12px 18px;border-top:1px solid var(--edge)}
#distill-btn{width:100%;background:var(--cyan);color:#000;border:0;border-radius:10px;padding:10px;cursor:pointer;font-size:13px;font-weight:700}
#bar{display:flex;gap:10px;padding:12px 0 8px;position:sticky;bottom:0;background:linear-gradient(180deg,transparent,var(--bg) 30%)}
#in{flex:1;background:rgba(255,255,255,.06);border:1px solid var(--edge);color:var(--text);border-radius:12px;padding:12px 16px;font-size:15px;font-family:var(--fm)}
#in:focus{outline:none;border-color:var(--cyan)}
#send{background:var(--yellow);color:#000;border:0;border-radius:12px;padding:12px 24px;font-size:13px;cursor:pointer;letter-spacing:1px;font-weight:700;clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px)}
#send:disabled{opacity:.35}
@media(max-width:900px){#nav{display:none}#chat-card{grid-column:span 12}#dock-card,#telemetry-card,#radar-card,#feed-card,#stats-card{grid-column:span 12}.stat-grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<div id="bg-grid"></div><svg id="bg-waves" viewBox="0 0 1440 900" preserveAspectRatio="none"><path d="M0,200 C240,120 480,280 720,200 S1200,120 1440,220" fill="none" stroke="rgba(125,255,196,.18)" stroke-width="1"/><path d="M0,420 C240,340 480,500 720,420 S1200,340 1440,440" fill="none" stroke="rgba(0,229,255,.12)" stroke-width="1"/><path d="M0,640 C240,560 480,720 720,640 S1200,560 1440,660" fill="none" stroke="rgba(125,255,196,.12)" stroke-width="1"/></svg><div class="bg-blob" id="b1"></div><div class="bg-blob" id="b2"></div>
<div id="boot"><svg viewBox="0 0 560 220"><path class="wave" d="M0,60 C70,20 140,100 210,60 S350,20 420,60 S500,100 560,60"/><path class="wave" d="M0,110 C70,70 140,150 210,110 S350,70 420,110 S500,150 560,110"/><path class="wave" d="M0,160 C70,120 140,200 210,160 S350,120 420,160 S500,200 560,160"/></svg><h1>Initializing</h1><p>ALIGNING INTERNAL DATA STREAMS.<br>SYNC WILL COMPLETE AUTOMATICALLY.</p><div id="boot-bar"><div id="boot-fill"></div></div><p style="color:#3a5a48;">CLICK ANYWHERE TO SKIP</p></div>
<div id="app">
<nav id="nav"><button class="nav-btn active" data-go="chat-card" title="Chat">💬</button><button class="nav-btn" data-go="dock-card" title="Dock">🧊</button><button class="nav-btn" data-go="telemetry-card" title="Telemetry">📊</button><button class="nav-btn" data-go="radar-card" title="Capabilities">🕸️</button><button class="nav-btn" data-go="pipeline-card" title="Tickets">🎫</button><button class="nav-btn" data-go="stats-card" title="System">⚙️</button></nav>
<div id="main">
<header><svg id="core" viewBox="0 0 52 52"><circle cx="26" cy="26" r="24" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="1"/><circle class="ring spin" cx="26" cy="26" r="20" fill="none" stroke="#00e5ff" stroke-width="1" stroke-dasharray="8 6" opacity=".8"/><circle class="ring spin2" cx="26" cy="26" r="14" fill="none" stroke="#8b5cf6" stroke-width="1" stroke-dasharray="4 5" opacity=".6"/><circle class="pulse" cx="26" cy="26" r="6" fill="#00e5ff"/></svg><div><div id="logo">VORTEX <span>// AGENT</span></div><div id="sub">HEAD CHEF &middot; LOCAL &middot; 12GB</div></div><div id="status-pill">IDLE</div><button id="chats-btn">Flight Log</button></header>
<div id="grid">
<div class="card" id="chat-card"><h2>Chat <span class="live-tag">LIVE</span></h2><div id="banner"></div><div id="log"></div></div>
<div class="card" id="dock-card"><h2>Model Dock <span class="live-tag">LIVE</span></h2><div id="dock-list"></div><div id="dock-detail"></div></div>
<div class="card" id="telemetry-card"><h2>Telemetry <span class="live-tag">LIVE</span></h2>
<div class="gauge"><div class="gauge-top"><span>VRAM</span><b id="vram-text">…</b></div><div class="gauge-bar"><div class="gauge-fill" id="vram-fill"></div></div></div>
<div class="metric-row"><div class="metric"><div class="v" id="gpu-util">…</div><div class="k">GPU UTIL</div></div><div class="metric"><div class="v" id="gpu-temp">…</div><div class="k">TEMP</div></div><div class="metric"><div class="v" id="strands-status">…</div><div class="k">STRANDS</div></div></div>
</div>
<div class="card" id="radar-card"><h2>Capability Radar</h2><svg id="radar" viewBox="0 0 220 220" style="width:100%;max-width:300px;margin:0 auto;display:block;"></svg><div id="radar-legend"></div></div>
<div class="card" id="pipeline-card"><h2>Ticket Pipeline</h2><div id="pipeline"><div class="pipe-col"><h3>QUEUED</h3><div id="pipe-queue"></div></div><div class="pipe-col"><h3>RUNNING</h3><div id="pipe-running"></div></div><div class="pipe-col"><h3>DONE</h3><div id="pipe-done"></div></div></div></div>
<div class="card" id="feed-card"><h2>Activity</h2><div id="feed"></div></div>
<div class="card" id="stats-card"><h2>System</h2><div class="stat-grid"><div class="stat"><div class="v" id="st-facts">…</div><div class="k">MEMORY FACTS</div></div><div class="stat"><div class="v" id="st-chats">…</div><div class="k">CHAT SESSIONS</div></div><div class="stat"><div class="v" id="st-jobs">…</div><div class="k">JOBS DONE</div></div><div class="stat"><div class="v" id="st-model">…</div><div class="k">LOADED MODEL</div></div></div></div>
</div>
<div id="drawer"><div id="drawer-head"><strong>Flight Log</strong><button id="drawer-close">×</button></div><div id="chat-list"></div><div id="chat-view" style="display:none;"><button id="chat-back">← back</button><div id="chat-turns"></div></div><div id="drawer-foot"><button id="distill-btn">End session & distill into memory</button></div></div>
<div id="approval"><p id="ap-text"></p><button id="btn-yes">Approve</button><button id="btn-no">Deny</button></div>
<div id="bar"><input id="in" placeholder="> transmit…" autocomplete="off"><button id="send">SEND</button></div>
</div></div>
<script>
const log=document.getElementById('log'),inp=document.getElementById('in'),send=document.getElementById('send'),pill=document.getElementById('status-pill'),core=document.getElementById('core'),banner=document.getElementById('banner');
let curAgent=null,curTl=null,lastSent=null;
function setStatus(s,cls){pill.textContent=s;pill.className=s==='IDLE'?'':'live';pill.id='status-pill';core.className='';core.setAttribute('class',cls||'');banner.className='';banner.style.display='none';if(s==='APPROVAL REQUIRED'){banner.className='attn';banner.textContent='⚠ ATTENTION — APPROVAL REQUIRED';banner.style.display='block';}else if(s==='EXECUTING'){banner.className='work';banner.textContent='▸ BREACHING — WORKING';banner.style.display='block';}else if(s==='IDLE'){banner.className='done';banner.textContent='✓ COMPLETE — IDLE';banner.style.display='block';setTimeout(()=>{banner.style.display='none';},3000);}}
function add(html,cls){const d=document.createElement('div');d.className='msg '+cls;d.innerHTML=html;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function md(s){let h=esc(s);h=h.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');h=h.replace(/`([^`]+)`/g,'<code style="background:rgba(255,255,255,.08);padding:1px 5px;border-radius:4px;color:#00e5ff;">$1</code>');return h.replace(/\\n/g,'<br>');}
function ts(){return new Date().toTimeString().slice(0,8);}
function feed(txt){const f=document.getElementById('feed');const d=document.createElement('div');d.textContent=ts()+'  '+txt;f.prepend(d);while(f.children.length>20)f.removeChild(f.lastChild);}
// Boot: 1.5s max, click to skip
const boot=document.getElementById('boot');document.getElementById('boot-fill').style.width='100%';
let bootDone=false;function endBoot(){if(bootDone)return;bootDone=true;boot.classList.add('done');document.querySelectorAll('.card').forEach((c,i)=>{setTimeout(()=>c.classList.add('in'),i*90);});}
boot.onclick=endBoot;setTimeout(endBoot,1500);
// Radar: 5 axes - reasoning / code / vision / osint / tools (0-10, from registry)
const RADAR_AXES=['REASONING','CODE','VISION','OSINT','TOOLS'];
const RADAR_DATA={'Qwen 14B':{vals:[7,8,1,5,10],color:'#00e5ff'},'MFDoom R1':{vals:[9,6,1,5,9],color:'#8b5cf6'},'REDCELL':{vals:[8,5,1,10,8],color:'#ff2244'},'Qwen-VL 8B':{vals:[6,4,10,3,8],color:'#ffb800'}};
function radarPoints(vals){const cx=110,cy=110,R=84;return vals.map((v,i)=>{const a=(-90+i*72)*Math.PI/180,r=R*v/10;return (cx+r*Math.cos(a)).toFixed(1)+','+(cy+r*Math.sin(a)).toFixed(1);}).join(' ');}
function drawRadar(){const svg=document.getElementById('radar');let h='';for(let ring=1;ring<=5;ring++){const pts=RADAR_AXES.map((_,i)=>{const a=(-90+i*72)*Math.PI/180,r=84*ring/5;return (110+r*Math.cos(a)).toFixed(1)+','+(110+r*Math.sin(a)).toFixed(1);}).join(' ');h+='<polygon points="'+pts+'" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="1"/>';}
 RADAR_AXES.forEach((ax,i)=>{const a=(-90+i*72)*Math.PI/180;h+='<line x1="110" y1="110" x2="'+(110+84*Math.cos(a)).toFixed(1)+'" y2="'+(110+84*Math.sin(a)).toFixed(1)+'" stroke="rgba(255,255,255,.12)"/><text x="'+(110+96*Math.cos(a)).toFixed(1)+'" y="'+(110+96*Math.sin(a)).toFixed(1)+'" fill="#9aa3c7" font-size="8" font-family="JetBrains Mono" text-anchor="middle">'+ax+'</text>';});
 Object.entries(RADAR_DATA).forEach(([name,d])=>{h+='<polygon class="radar-poly" data-name="'+name+'" points="'+radarPoints(d.vals)+'" fill="'+d.color+'" fill-opacity=".18" stroke="'+d.color+'" stroke-width="1.5"/>';});
 svg.innerHTML=h;document.getElementById('radar-legend').innerHTML=Object.entries(RADAR_DATA).map(([n,d])=>'<span class="radar-key"><span class="sw" style="background:'+d.color+'"></span>'+n+'</span>').join('');}
drawRadar();
const es=new EventSource('/api/events');
es.onmessage=e=>{
 const ev=JSON.parse(e.data),t=ev.type,d=ev.data||{};
 if(t==='user'){if(lastSent!==null&&d.text===lastSent){lastSent=null;setStatus('THINKING','thinking');}else{add(esc(d.text),'user');setStatus('THINKING','thinking');}}
 else if(t==='thinking'){
   if(!curAgent)curAgent=add('','agent');
   const det=document.createElement('details');det.className='think';
   det.innerHTML='<summary>▸ Neural Trace</summary><div>'+esc(d.text)+'</div>';
   curAgent.appendChild(det);log.scrollTop=log.scrollHeight;setStatus('THINKING','thinking');feed('Thinking…');
 }
 else if(t==='tool_call'){
   if(!curAgent)curAgent=add('','agent');
   if(!curTl){curTl=document.createElement('div');curTl.className='tl';curAgent.appendChild(curTl);}
   const row=document.createElement('div');row.className='tl-row';row.dataset.tool=d.name;
   row.innerHTML='<span class="dot"></span><span>'+ts()+'</span><span>EXEC '+esc(d.name)+'</span>';
   curTl.appendChild(row);log.scrollTop=log.scrollHeight;setStatus('EXECUTING','working');feed('EXEC '+d.name);
 }
 else if(t==='tool_result'){
   document.querySelectorAll('.tl-row').forEach(el=>{if(el.dataset.tool===d.name&&!el.classList.contains('done')){el.classList.add('done');el.querySelector('span:last-child').textContent='DONE '+d.name;}});
 }
 else if(t==='answer'){
   if(!curAgent)curAgent=add('','agent');
   const p=document.createElement('div');p.innerHTML=md(d.text);curAgent.appendChild(p);
   curAgent=null;curTl=null;log.scrollTop=log.scrollHeight;setStatus('IDLE','');feed('Answer delivered');
 }
 else if(t==='ticket'){
   if(!curAgent)curAgent=add('','agent');
   if(!curTl){curTl=document.createElement('div');curTl.className='tl';curAgent.appendChild(curTl);}
   const row=document.createElement('div');row.className='tl-row done';
   row.innerHTML='<span class="dot"></span><span>'+ts()+'</span><span>TICKET '+(d.job_id||'')+' '+(d.status||'')+' '+(d.specialist||'')+'</span>';
   curTl.appendChild(row);log.scrollTop=log.scrollHeight;setStatus('EXECUTING','working');feed('Ticket '+(d.job_id||'')+' '+(d.status||''));
 }
 else if(t==='approval'){setStatus('APPROVAL REQUIRED','alert');
   document.getElementById('ap-text').textContent='['+d.kind+'] '+d.detail;
   document.getElementById('approval').style.display='block';feed('Approval required: '+d.kind);
 }
 else if(t==='distill'){setStatus('DISTILLING','working');}
 else if(t==='distill_done'){add('✨ '+esc((d.summary||'done')),'agent');setStatus('IDLE','');}
 else if(t==='idle'){document.getElementById('approval').style.display='none';send.disabled=false;inp.disabled=false;setStatus('IDLE','');}
};
document.getElementById('btn-yes').onclick=()=>{fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:true})});document.getElementById('approval').style.display='none';setStatus('EXECUTING','working');};
document.getElementById('btn-no').onclick=()=>{fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:false})});document.getElementById('approval').style.display='none';setStatus('IDLE','');};
function go(){const v=inp.value.trim();if(!v)return;inp.value='';send.disabled=true;inp.disabled=true;lastSent=v;add(esc(v),'user');setStatus('THINKING','thinking');fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:v})});}
send.onclick=go;inp.onkeydown=e=>{if(e.key==='Enter')go();};
document.querySelectorAll('.nav-btn').forEach(b=>{b.onclick=()=>{document.querySelectorAll('.nav-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.go).scrollIntoView({behavior:'smooth',block:'center'});};});
const DOCK_INFO={'redcell-apex-mini':{role:'OSINT researcher',caps:'tools · thinking',str:'OSINT, security, CVE'},'MFDoom/deepseek-r1-tool-calling:14b':{role:'Researcher',caps:'tools · thinking',str:'Reasoning, research'},'nomic-embed-text':{role:'Embeddings',caps:'embedding',str:'Vector memory'},'qwen3-vl:8b-instruct':{role:'Vision worker',caps:'tools · vision',str:'Screenshot, OCR, grounding'},'moondream':{role:'Captioning consultant',caps:'vision (no tools)',str:'Fast captioning'},'dolphin3:8b':{role:'Uncensored consultant',caps:'completion only',str:'Refusal-free'},'qwen3:14b':{role:'Head chef + coder',caps:'tools · thinking',str:'Orchestration, code'}};
async function refresh(){try{
 const r=await fetch('/api/dock');const j=await r.json();
 const loaded=new Set(j.models||[]);
 const el=document.getElementById('dock-list');
 const badgeFor=n=>n.includes('vl')||n.includes('moondream')?'vision':n.includes('redcell')?'osint':n.includes('MFDoom')||n.includes('deepseek')?'reasoning':n.includes('nomic')?'embed':n.includes('dolphin')?'uncensored':'general';
 el.innerHTML=(j.all_models||[]).map(m=>'<div class="dock-row" data-name="'+esc(m.name)+'"><span class="dock-name"><span class="'+(loaded.has(m.name)?'dot-on':'dot-off')+'"></span>'+esc(m.name.split(':')[0].slice(0,24))+'</span><span><span class="badge">'+badgeFor(m.name)+'</span> <span style="color:#9aa3c7;font-family:var(--fm);font-size:11px;">'+esc(m.size||'')+'</span></span></div>').join('')||'<div style="color:#9aa3c7;">No models</div>';
 document.querySelectorAll('.dock-row').forEach(row=>{row.onclick=()=>{document.querySelectorAll('.dock-row').forEach(x=>x.classList.remove('sel'));row.classList.add('sel');const info=DOCK_INFO[row.dataset.name]||{role:'—',caps:'—',str:'—'};const det=document.getElementById('dock-detail');det.style.display='block';det.innerHTML='<b>'+esc(row.dataset.name)+'</b><br>Role: '+esc(info.role)+'<br>Caps: '+esc(info.caps)+'<br>Strengths: '+esc(info.str);};});
 if(j.gpu){const used=parseFloat(j.gpu.used_mb),total=parseFloat(j.gpu.total_mb);const pct=Math.round(used/total*100);const fill=document.getElementById('vram-fill');fill.style.width=pct+'%';fill.className='gauge-fill'+(pct>85?' bad':pct>60?' warn':'');document.getElementById('vram-text').textContent=(Math.round(used/102.4)/10)+'/'+(Math.round(total/102.4)/10)+' GB';document.getElementById('gpu-util').textContent=j.gpu.util+'%';document.getElementById('gpu-temp').textContent=j.gpu.temp_c+'°C';document.getElementById('st-model').textContent=(j.models[0]||'—').split(':')[0].slice(0,12);}
 const tr=await fetch('/api/tickets');const tk=await tr.json();
 const q=tk.filter(t=>t.status==='queue'),run=tk.filter(t=>t.status==='running'),done=tk.filter(t=>t.status==='done');
 document.getElementById('pipe-queue').innerHTML=q.length?q.map(t=>'<div class="item">'+esc(t.id)+'</div>').join(''):'<div style="color:#9aa3c7;font-size:11px;">Empty</div>';
 document.getElementById('pipe-running').innerHTML=run.length?run.map(t=>'<div class="item run">'+esc(t.id)+' · '+(t.goal?esc(t.goal.slice(0,40)):'')+'</div>').join(''):'<div style="color:#9aa3c7;font-size:11px;">Idle</div>';
 document.getElementById('pipe-done').innerHTML=done.slice(0,5).map(t=>'<div class="item done">'+esc(t.id)+'</div>').join('')||'<div style="color:#9aa3c7;font-size:11px;">None yet</div>';
 const sr=await fetch('/api/stats');const st=await sr.json();
 document.getElementById('st-facts').textContent=st.facts;document.getElementById('st-chats').textContent=st.chats;document.getElementById('st-jobs').textContent=st.jobs_done;document.getElementById('strands-status').textContent=st.strands==='up'?'UP':'DOWN';
}catch(e){}}
setInterval(refresh,5000);refresh();
const drawer=document.getElementById('drawer');
document.getElementById('chats-btn').onclick=()=>{drawer.classList.add('open');loadChats();};
document.getElementById('drawer-close').onclick=()=>drawer.classList.remove('open');
async function loadChats(){
 const r=await fetch('/api/chats');const list=await r.json();
 const el=document.getElementById('chat-list');el.style.display='block';
 document.getElementById('chat-view').style.display='none';
 el.innerHTML=list.length?'':'<div style="color:#9aa3c7;padding:12px;">No logged flights.</div>';
 list.forEach(c=>{
  const d=document.createElement('div');d.className='chat-item';
  d.innerHTML='<button class="del">Delete</button><div class="cp">'+esc(c.preview||'(empty)')+'</div><div class="cm">'+c.id+' · '+c.turns+' turns</div>';
  d.querySelector('.cp').onclick=()=>viewChat(c.id);
  const del=d.querySelector('.del');
  del.onclick=(e)=>{e.stopPropagation();
   if(!del.classList.contains('arm')){del.classList.add('arm');del.textContent='Confirm?';setTimeout(()=>{del.classList.remove('arm');del.textContent='Delete';},4000);}
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
document.getElementById('distill-btn').onclick=()=>{fetch('/api/distill',{method:'POST'});drawer.classList.remove('open');add('Distilling this session into memories…','agent');setStatus('DISTILLING','working');};
</script></body></html>
"""


@app.route("/")
def index():
    return PAGE


if __name__ == "__main__":
    print("Agent panel: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True)
