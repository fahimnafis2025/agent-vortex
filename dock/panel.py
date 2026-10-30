"""
panel.py - minimal model-dock control panel (Lab 4)
Run:  python dock/panel.py   then open http://localhost:5000
One page: VRAM meter, manifest list, Pull/Load/Stop buttons,
and a dropdown to switch the main brain in config.json.
Deliberately plain: no CSS framework, no JavaScript.
"""

import json
import subprocess
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for

BASE = Path(__file__).parent              # ...\agent-lab\dock
MANIFESTS = BASE / "manifests"
CONFIG = BASE / "config.json"

app = Flask(__name__)


def load_manifests():
    out = []
    for f in sorted(MANIFESTS.glob("*.json")):
        out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def get_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def get_vram():
    """(used_mb, total_mb) from nvidia-smi, or (None, None)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        used, total = out.stdout.strip().split(",")
        return int(used), int(total)
    except Exception:
        return None, None


def get_loaded():
    """Model tags currently in VRAM, parsed from `ollama ps`."""
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True,
                             text=True, timeout=10)
        lines = [l for l in out.stdout.strip().splitlines() if l]
        return [l.split()[0] for l in lines[1:]]  # skip header row
    except Exception:
        return []


def run_bg(args):
    """Fire a command without blocking the page on it."""
    subprocess.Popen(args, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


PAGE = """
<!doctype html><title>Model Dock</title>
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:2em auto;max-width:720px;
      padding:0 1em;color:#1c1e20}
 table{border-collapse:collapse;width:100%}
 td,th{border:1px solid #ccc;padding:.5em .7em;text-align:left}
 button{padding:.35em .9em;cursor:pointer}
 .bar{background:#e5e2d8;height:14px;border-radius:7px;overflow:hidden}
 .fill{background:#0f766e;height:100%}
 .loaded{color:#0f766e;font-weight:bold}
</style>
<h1>Model Dock</h1>
<p>VRAM: {{ used }} / {{ total }} MB</p>
<div class="bar"><div class="fill" style="width:{{ pct }}%"></div></div>
<p>Loaded now: {{ loaded|join(", ") if loaded else "nothing" }}</p>

<table>
<tr><th>Model</th><th>Tag</th><th>VRAM</th><th></th></tr>
{% for m in manifests %}
<tr>
 <td>{{ m.name }}
   {% if m.ollama_tag in loaded %}<span class="loaded">● loaded</span>{% endif %}
   <br><small>{{ m.description }}</small></td>
 <td><code>{{ m.ollama_tag }}</code></td>
 <td>{{ m.vram_gb }} GB</td>
 <td>
  <form method="post" action="/act" style="display:inline">
   <input type="hidden" name="tag" value="{{ m.ollama_tag }}">
   <button name="op" value="pull">Pull</button>
   <button name="op" value="load">Load</button>
   <button name="op" value="stop">Stop</button>
  </form>
 </td>
</tr>
{% endfor %}
</table>

<h2>Main brain</h2>
<form method="post" action="/set_brain">
 <select name="brain">
  {% for m in manifests %}
  <option value="{{ m.ollama_tag }}"
    {% if m.ollama_tag == brain %}selected{% endif %}>
    {{ m.name }} ({{ m.ollama_tag }})</option>
  {% endfor %}
 </select>
 <button>Save</button>
</form>
<p><small>Changing the brain edits dock/config.json.
Restart agent.py to apply it.</small></p>
<p><small>Pull and Load run in the background - refresh the
page after a bit to see the result.</small></p>
"""


@app.route("/")
def index():
    used, total = get_vram()
    pct = round(used / total * 100) if total else 0
    return render_template_string(
        PAGE, manifests=load_manifests(), used=used, total=total,
        pct=pct, loaded=get_loaded(), brain=get_config()["main_brain"])


@app.route("/act", methods=["POST"])
def act():
    tag, op = request.form["tag"], request.form["op"]
    if op == "pull":
        run_bg(["ollama", "pull", tag])
    elif op == "load":
        # A tiny generate warms the model into VRAM.
        run_bg(["ollama", "run", tag, "hi"])
    elif op == "stop":
        run_bg(["ollama", "stop", tag])
    return redirect(url_for("index"))


@app.route("/set_brain", methods=["POST"])
def set_brain():
    cfg = get_config()
    cfg["main_brain"] = request.form["brain"]
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
