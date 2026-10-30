r"""Bisect the v14.8 native-transport HTTP 400.

Run with the agent venv python from E:\AGENT\agent-lab :
    .venv\Scripts\python.exe native-bisect.py

It imports your installed agent.py, builds the REAL first-turn payload
(real system prompt + real tool definitions) and sends 4 variants to
your Ollama, printing 200/400 for each. Paste the 4 lines back.
"""
import json
import importlib.util
import urllib.request
import urllib.error

AGENT = "E:" + chr(92) + "AGENT" + chr(92) + "agent-lab" + chr(92) + "agent.py"
OLLAMA = "http://localhost:11434"


def post(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA + "/api/chat", data=data, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, "OK"
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:160]
    except Exception as e:
        return "ERR", str(e)[:160]


spec = importlib.util.spec_from_file_location("agent", AGENT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

sys_prompt = mod.build_system_prompt()
tools = mod.active_tools()
print("system prompt chars:", len(sys_prompt))
print("active tools:", len(tools))
print("MODEL:", mod.MODEL)

# Sanity: scan the final JSON for exotic content
probe = json.dumps({"m": [{"role": "system", "content": sys_prompt}], "t": tools})
print("payload-with-system+tools bytes:", len(probe.encode("utf-8")))
print("non-ascii escapes present:", "\\u" in probe)

base = {
    "model": mod.MODEL,
    "stream": False,
    "keep_alive": "10m",
    "options": {"num_ctx": 8192, "temperature": 0.6, "top_p": 0.95},
    "think": False,
}
cases = {
    "1_minimal(no sys,no tools)": {
        "model": mod.MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    },
    "2_sys_only": dict(
        base,
        messages=[{"role": "system", "content": sys_prompt},
                  {"role": "user", "content": "hi"}]),
    "3_tools_only": dict(
        base,
        messages=[{"role": "user", "content": "hi"}],
        tools=tools),
    "4_sys+tools(agent real 1st call)": dict(
        base,
        messages=[{"role": "system", "content": sys_prompt},
                  {"role": "user", "content": "hi"}],
        tools=tools),
}
for name, payload in cases.items():
    # also run it through the agent's own converter, like the real path does
    if name.startswith("4"):
        payload = dict(payload)
        payload["messages"] = mod._to_native_messages(payload["messages"])
    st, body = post(payload)
    print(name, "->", st, body[:100])
