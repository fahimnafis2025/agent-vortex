"""panel.py - Lab 8 GUI for the local agent.

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
    info = {"models": [], "gpu": None}
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
<title>Mission Control</title>
<style>
:root{
 --bg:#05070a; --panel:#0a0e14; --line:#1a2433;
 --cyan:#22d3ee; --amber:#f59e0b; --red:#ef4444; --green:#22c55e; --violet:#a78bfa;
 --text:#d7dde5; --dim:#7d8ca3;
 --mono:ui-monospace,'Cascadia Code','JetBrains Mono',Consolas,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(ellipse 90% 55% at 50% -10%,rgba(34,211,238,.07),transparent),repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(255,255,255,.008) 4px);pointer-events:none;z-index:0}
header{position:relative;z-index:1;display:flex;align-items:center;gap:14px;padding:10px 18px;border-bottom:1px solid var(--line);background:rgba(10,14,20,.9)}
#orb{width:46px;height:46px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#14304a,#070d16);border:2px solid #1e3a5f;position:relative;transition:all .4s;flex-shrink:0}
#orb::after{content:'';position:absolute;inset:-7px;border-radius:50%;border:2px solid transparent;transition:all .4s}
#orb.idle{border-color:#1e3a5f;box-shadow:0 0 12px rgba(34,211,238,.15)}
#orb.thinking{border-color:var(--amber);box-shadow:0 0 20px rgba(245,158,11,.55);animation:pulse 1.2s ease-in-out infinite}
#orb.working{border-color:var(--cyan);box-shadow:0 0 20px rgba(34,211,238,.55)}
#orb.working::after{border-top-color:var(--cyan);animation:spin 1s linear infinite}
#orb.alert{border-color:var(--red);box-shadow:0 0 24px rgba(239,68,68,.65);animation:pulse .7s ease-in-out infinite}
#orb.distilling{border-color:var(--violet);box-shadow:0 0 20px rgba(167,139,250,.55);animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.09)}}
@keyframes spin{to{transform:rotate(360deg)}}
#title-block h1{font-size:15px;font-weight:700;letter-spacing:3px;color:var(--text)}
#status-line{font-family:var(--mono);font-size:11px;color:var(--cyan);letter-spacing:1px;margin-top:2px}
#hw{position:relative;z-index:1;display:flex;gap:24px;align-items:center;padding:8px 18px;background:rgba(8,11,17,.9);border-bottom:1px solid var(--line);font-size:12px;color:var(--dim);flex-wrap:wrap;font-family:var(--mono)}
.hw-item{display:flex;align-items:center;gap:8px}
.hw-label{color:#4b5a70;text-transform:uppercase;font-size:10px;letter-spacing:2px}
.hw-val{color:var(--text);min-width:80px}
.bar{width:150px;height:10px;background:#141b28;border:1px solid var(--line);border-radius:5px;overflow:hidden}
#vram-fill{height:100%;width:0%;background:var(--green);transition:width .5s,background .5s}
#model-pill{background:rgba(34,211,238,.12);border:1px solid rgba(34,211,238,.4);color:var(--cyan);border-radius:12px;padding:2px 12px;font-size:12px;font-family:var(--mono)}
#spark{background:#070b12;border:1px solid var(--line);border-radius:4px}
#chats-btn{background:transparent;color:var(--cyan);border:1px solid rgba(34,211,238,.4);border-radius:8px;padding:7px 14px;cursor:pointer;font-size:12px;letter-spacing:2px;font-family:var(--mono)}
#chats-btn:hover{background:rgba(34,211,238,.1)}
#log{position:relative;z-index:1;flex:1;overflow-y:auto;padding:18px;max-width:900px;width:100%;margin:0 auto}
.msg{margin:12px 0;padding:12px 16px;border-radius:10px;max-width:88%}
.user{background:rgba(34,211,238,.08);border:1px solid rgba(34,211,238,.25);margin-left:auto;white-space:pre-wrap}
.agent{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--cyan);white-space:pre-wrap}
.tl{margin:10px 0;border-left:2px solid var(--line);padding-left:16px;display:flex;flex-direction:column;gap:7px}
.tl-row{font-family:var(--mono);font-size:12.5px;color:var(--dim);display:flex;gap:10px;align-items:center}
.tl-row .dot{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan);flex-shrink:0;animation:pulse 1s infinite}
.tl-row.done .dot{background:var(--green);box-shadow:0 0 8px var(--green);animation:none}
.tl-row.done{color:var(--text)}
.tl-row .ts{color:#4b5a70}
details.think{margin:10px 0;font-size:13px;border:1px dashed #2a3a52;border-radius:8px;padding:8px 12px}
details.think summary{cursor:pointer;color:var(--amber);font-family:var(--mono);font-size:12px;letter-spacing:1px}
details.think summary:hover{color:#fbbf24}
details.think div{color:#9fb0c8;font-family:var(--mono);font-size:12.5px;margin-top:8px;white-space:pre-wrap}
#approval{display:none;position:fixed;bottom:96px;left:50%;transform:translateX(-50%);background:#140a0a;border:1px solid var(--red);border-radius:12px;padding:16px 20px;max-width:540px;box-shadow:0 0 40px rgba(239,68,68,.3);z-index:30;animation:alertPulse 1.6s ease-in-out infinite}
@keyframes alertPulse{0%,100%{box-shadow:0 0 24px rgba(239,68,68,.2)}50%{box-shadow:0 0 44px rgba(239,68,68,.45)}}
#approval p{font-size:13px;color:#fca5a5;margin-bottom:12px;word-break:break-word;font-family:var(--mono)}
#approval button{margin-right:8px;padding:9px 20px;border:0;border-radius:8px;font-size:14px;cursor:pointer;font-family:var(--mono);letter-spacing:1px}
#btn-yes{background:#166534;color:#fff}
#btn-no{background:#2a3342;color:var(--text)}
#drawer{position:fixed;top:0;right:-430px;width:410px;max-width:94vw;height:100vh;background:#080b11;border-left:1px solid var(--line);z-index:20;display:flex;flex-direction:column;transition:right .25s}
#drawer.open{right:0}
#drawer-head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--line);letter-spacing:2px;font-size:13px}
#drawer-close{background:none;border:0;color:var(--dim);font-size:24px;cursor:pointer}
#drawer-note{font-size:12px;color:#4b5a70;padding:10px 18px;border-bottom:1px solid var(--line);font-family:var(--mono)}
#chat-list{flex:1;overflow-y:auto;padding:8px}
.chat-item{padding:10px 12px;border:1px solid var(--line);border-radius:8px;margin:8px;background:var(--panel);cursor:pointer}
.chat-item:hover{border-color:rgba(34,211,238,.4)}
.chat-item .cp{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-item .cm{font-size:12px;color:#4b5a70;margin-top:4px;font-family:var(--mono)}
.chat-item .del{float:right;background:rgba(239,68,68,.1);color:#f87171;border:1px solid rgba(239,68,68,.4);border-radius:6px;padding:2px 8px;font-size:12px;cursor:pointer;font-family:var(--mono)}
.chat-item .del.arm{background:#7f1d1d;color:#fff}
#chat-view{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
#chat-back{align-self:flex-start;background:transparent;color:var(--cyan);border:1px solid rgba(34,211,238,.4);border-radius:6px;padding:4px 10px;cursor:pointer;margin-bottom:4px;font-family:var(--mono)}
.ct{padding:8px 12px;border-radius:8px;font-size:14px;max-width:95%}
.ct.u{background:rgba(34,211,238,.08);border:1px solid rgba(34,211,238,.25);align-self:flex-end}
.ct.a{background:var(--panel);border:1px solid var(--line);align-self:flex-start}
#drawer-foot{padding:12px 18px;border-top:1px solid var(--line)}
#distill-btn{width:100%;background:rgba(167,139,250,.12);color:var(--violet);border:1px solid rgba(167,139,250,.4);border-radius:8px;padding:10px;cursor:pointer;font-size:13px;letter-spacing:1px;font-family:var(--mono)}
#distill-btn:hover{background:rgba(167,139,250,.2)}
#bar{position:relative;z-index:1;display:flex;gap:10px;padding:14px 18px;border-top:1px solid var(--line);background:rgba(8,11,17,.95)}
#in{flex:1;background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:11px 14px;font-size:15px;font-family:var(--mono)}
#in:focus{outline:none;border-color:rgba(34,211,238,.5);box-shadow:0 0 12px rgba(34,211,238,.15)}
#send{background:rgba(34,211,238,.12);color:var(--cyan);border:1px solid rgba(34,211,238,.5);border-radius:8px;padding:10px 24px;font-size:14px;cursor:pointer;letter-spacing:2px;font-family:var(--mono)}
#send:hover{background:rgba(34,211,238,.22)}
#send:disabled{opacity:.35;cursor:default}
.typing{color:#4b5a70;font-size:13px;margin:6px 0;font-family:var(--mono)}
</style></head><body>
<header>
<div id="orb" class="idle"></div>
<div id="title-block"><h1>MISSION CONTROL</h1><div id="status-line">STATUS: IDLE</div></div>
<div style="margin-left:auto;display:flex;gap:10px;align-items:center;"><div id="dock">…</div><button id="chats-btn">CHATS</button></div>
</header>
<div id="hw">
<div class="hw-item"><span class="hw-label">VRAM</span><div class="bar"><div id="vram-fill"></div></div><span id="vram-text" class="hw-val">…</span></div>
<div class="hw-item"><span class="hw-label">GPU</span><canvas id="spark" width="140" height="30"></canvas><span id="gpu-text" class="hw-val">…</span></div>
<div class="hw-item"><span class="hw-label">TEMP</span><span id="temp-text" class="hw-val">…</span></div>
</div>
<div id="log"></div>
<div id="drawer"><div id="drawer-head"><strong>FLIGHT LOG</strong><button id="drawer-close">×</button></div><div id="drawer-note">Deleting a chat removes its transcript only — saved memories are kept.</div><div id="chat-list"></div><div id="chat-view" style="display:none;"><button id="chat-back">← back</button><div id="chat-turns"></div></div><div id="drawer-foot"><button id="distill-btn">END SESSION & DISTILL INTO MEMORY</button></div></div>
<div id="approval"><p id="ap-text"></p><button id="btn-yes">APPROVE</button><button id="btn-no">DENY</button></div>
<div id="bar"><input id="in" placeholder="> transmit command…" autocomplete="off"><button id="send">SEND</button></div>
<script>
const log=document.getElementById('log'),inp=document.getElementById('in'),send=document.getElementById('send'),orb=document.getElementById('orb'),statusLine=document.getElementById('status-line');
let curAgent=null,curTl=null;
function setOrb(cls,label){orb.className=cls;statusLine.textContent='STATUS: '+label;statusLine.style.color=cls==='alert'?'#ef4444':cls==='thinking'?'#f59e0b':cls==='working'?'#22d3ee':cls==='distilling'?'#a78bfa':'#7d8ca3';}
function add(html,cls){const d=document.createElement('div');d.className='msg '+cls;d.innerHTML=html;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function md(s){let h=esc(s);h=h.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');h=h.replace(/`([^`]+)`/g,'<code style="background:#141b28;padding:1px 5px;border-radius:4px;color:#22d3ee;">$1</code>');return h.replace(/\\n/g,'<br>');}
function ts(){return new Date().toTimeString().slice(0,8);}
const es=new EventSource('/api/events');
es.onmessage=e=>{
 const ev=JSON.parse(e.data),t=ev.type,d=ev.data||{};
 if(t==='user'){add(esc(d.text),'user');setOrb('thinking','THINKING');}
 else if(t==='thinking'){
   if(!curAgent)curAgent=add('','agent');
   const det=document.createElement('details');det.className='think';
   det.innerHTML='<summary>▸ NEURAL TRACE</summary><div>'+esc(d.text)+'</div>';
   curAgent.appendChild(det);log.scrollTop=log.scrollHeight;setOrb('thinking','THINKING');
 }
 else if(t==='tool_call'){
   if(!curAgent)curAgent=add('','agent');
   if(!curTl){curTl=document.createElement('div');curTl.className='tl';curAgent.appendChild(curTl);}
   const row=document.createElement('div');row.className='tl-row';row.dataset.tool=d.name;
   row.innerHTML='<span class="dot"></span><span class="ts">'+ts()+'</span><span>EXEC '+esc(d.name)+'</span>';
   curTl.appendChild(row);log.scrollTop=log.scrollHeight;setOrb('working','EXECUTING');
 }
 else if(t==='tool_result'){
   document.querySelectorAll('.tl-row').forEach(el=>{if(el.dataset.tool===d.name&&!el.classList.contains('done')){el.classList.add('done');el.querySelector('span:last-child').textContent='DONE '+d.name;}});
 }
 else if(t==='answer'){
   if(!curAgent)curAgent=add('','agent');
   const p=document.createElement('div');p.innerHTML=md(d.text);curAgent.appendChild(p);
   curAgent=null;curTl=null;log.scrollTop=log.scrollHeight;setOrb('idle','IDLE');
 }
 else if(t==='ticket'){
   if(!curAgent)curAgent=add('','agent');
   if(!curTl){curTl=document.createElement('div');curTl.className='tl';curAgent.appendChild(curTl);}
   const row=document.createElement('div');row.className='tl-row done';
   row.innerHTML='<span class="dot"></span><span class="ts">'+ts()+'</span><span>TICKET '+(d.job_id||'')+' '+(d.status||'')+' '+(d.specialist||'')+'</span>';
   curTl.appendChild(row);log.scrollTop=log.scrollHeight;setOrb('working','EXECUTING');
 }
 else if(t==='approval'){setOrb('alert','APPROVAL REQUIRED');
   document.getElementById('ap-text').textContent='['+d.kind+'] '+d.detail;
   document.getElementById('approval').style.display='block';
 }
 else if(t==='distill'){setOrb('distilling','DISTILLING');}
 else if(t==='distill_done'){add('✨ '+esc((d.summary||'done')),'agent');setOrb('idle','IDLE');}
 else if(t==='idle'){document.getElementById('approval').style.display='none';send.disabled=false;inp.disabled=false;if(orb.className!=='distilling')setOrb('idle','IDLE');}
};
document.getElementById('btn-yes').onclick=()=>{fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:true})});document.getElementById('approval').style.display='none';setOrb('working','EXECUTING');};
document.getElementById('btn-no').onclick=()=>{fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:false})});document.getElementById('approval').style.display='none';setOrb('idle','IDLE');};
function go(){const v=inp.value.trim();if(!v)return;inp.value='';send.disabled=true;inp.disabled=true;setOrb('thinking','THINKING');fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:v})});}
send.onclick=go;inp.onkeydown=e=>{if(e.key==='Enter')go();};
const hist=[];
async function dock(){try{const r=await fetch('/api/dock');const j=await r.json();
 document.getElementById('dock').innerHTML=j.models.length?'<span id="model-pill">'+esc(j.models[0])+'</span>':'<span style="color:#4b5a70">NO MODEL</span>';
 if(j.gpu){
  const used=parseFloat(j.gpu.used_mb),total=parseFloat(j.gpu.total_mb),util=parseFloat(j.gpu.util);
  const pct=Math.round(used/total*100),fill=document.getElementById('vram-fill');
  fill.style.width=pct+'%';
  fill.style.background=pct>85?'#ef4444':pct>60?'#f59e0b':'#22c55e';
  document.getElementById('vram-text').textContent=(Math.round(used/102.4)/10)+'/'+(Math.round(total/102.4)/10)+' GB';
  document.getElementById('gpu-text').textContent=util+'%';
  document.getElementById('temp-text').textContent=(j.gpu.temp_c||'–')+'°C';
  hist.push(util);if(hist.length>40)hist.shift();drawSpark();
 }}catch(e){}}
function drawSpark(){const c=document.getElementById('spark'),x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);
 if(hist.length<2)return;x.strokeStyle='#22d3ee';x.lineWidth=1.5;x.beginPath();
 hist.forEach((v,i)=>{const px=i/39*c.width,py=c.height-2-(v/100)*(c.height-4);i?x.lineTo(px,py):x.moveTo(px,py);});x.stroke();}
setInterval(dock,5000);dock();
const drawer=document.getElementById('drawer');
document.getElementById('chats-btn').onclick=()=>{drawer.classList.add('open');loadChats();};
document.getElementById('drawer-close').onclick=()=>drawer.classList.remove('open');
async function loadChats(){
 const r=await fetch('/api/chats');const list=await r.json();
 const el=document.getElementById('chat-list');el.style.display='block';
 document.getElementById('chat-view').style.display='none';
 el.innerHTML=list.length?'':'<div style="color:#4b5a70;padding:12px;font-family:var(--mono)">NO LOGGED FLIGHTS.</div>';
 list.forEach(c=>{
  const d=document.createElement('div');d.className='chat-item';
  d.innerHTML='<button class="del">DELETE</button><div class="cp">'+esc(c.preview||'(empty)')+'</div><div class="cm">'+c.id+' · '+c.turns+' turns</div>';
  d.querySelector('.cp').onclick=()=>viewChat(c.id);
  const del=d.querySelector('.del');
  del.onclick=(e)=>{e.stopPropagation();
   if(!del.classList.contains('arm')){del.classList.add('arm');del.textContent='CONFIRM?';setTimeout(()=>{del.classList.remove('arm');del.textContent='DELETE';},4000);}
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
document.getElementById('distill-btn').onclick=()=>{fetch('/api/distill',{method:'POST'});drawer.classList.remove('open');add('Distilling this session into memories…','agent');setOrb('distilling','DISTILLING');};
</script></body></html>
"""


@app.route("/")
def index():
    return PAGE


if __name__ == "__main__":
    print("Agent panel: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True)
