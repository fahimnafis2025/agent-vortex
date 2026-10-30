# Agent Lab

**A fully-local AI personal assistant on Windows**

By **MD Fahim Nafis** — github.com/fahimnafis2025 · linkedin.com/in/fahimnafis

> **Status: Archived — Abandoned 29 October 2026. Not maintained.**
>
> This repository is left as a historical record, so the work does not disappear.
> It is not a working product, and it is not a promise that the code will run
> unchanged on your machine. Read the full documentation before you run anything.

**Full documentation:** [Agent-Lab-Full-Documentation.pdf](./Agent-Lab-Full-Documentation.pdf)
(20 pages, with diagrams, timeline, reproduction steps, and the honest ending.
Put this README and that PDF in the same folder at the root of the repository,
or update the link above if you move the PDF to `docs/`.)

---


## What this is

A personal assistant that lives on your own computer, not in someone else's cloud.
It answers questions, works with files, browses the web, controls desktop programs,
remembers facts, runs background jobs, and — in its last push — tries to talk
by voice.

The design, in Fahim's own restaurant analogy:

- **Panel = the waiter.** It takes your order and presents the result.
  Flask, at `http://127.0.0.1:5000`, BREACH TERMINAL style.
- **Core agent = the head chef.** It breaks a request into tickets, gives each
  ticket to a specialist worker, verifies the worker's evidence, and only then
  plates an answer.
- **Specialist workers = the chefs.** Researcher, coder, and others, each with a
  small, pure-prompt skill pack. A worker runs as a separate `agent.py` job and
  writes a handoff report.
- **Model dock = the kitchen roster.** Ollama models with roles and VRAM costs.
  The default brain is `qwen3:14b`.

The rules that shaped it:

- **Accuracy over speed.** A fast wrong answer was worse than a slow honest one.
- **Local first, zero cost.** No paid API by default. A paid or cloud move had
  to be proposed and approved first.
- **No hardcoding.** Fix the general mechanism, not a list of banned phrases.
- **Approval is a card, not prose.** The agent asked permission only for
  PowerShell / command-line use and for serious writes: delete, install,
  publish, send, change system settings, or force-kill.
- **Sandbox proof is not live proof.** A test in a sandbox proved logic, not
  live behaviour. Live proof needed the footer version, a real run, and a real result.
- **No malware, ever.** Refusal lived in the routing layer. Defensive security
  reviews stayed fully allowed.

## What this is not

- Not a frontier assistant. It cannot do long research like a cloud model, and
  it never claimed to.
- Not a finished voice companion. Voice v1 worked in pieces, but as a whole
  conversation it was not usable. See below.
- Not a one-click installer. There is no `requirements.txt`, no licence file,
  and no installer in the archive. You recreate the environment from the
  documentation.

## Machine it was built on

- Windows, Intel i7-14700K, 32 GB DDR5 RAM
- NVIDIA RTX 4070 SUPER, 12 GB VRAM — the hard ceiling for the whole design
- Project: `E:\AGENT\agent-lab`
- Models: `E:\AGENT\ollama-models`, via `OLLAMA_MODELS`
- Voice sidecar: `http://127.0.0.1:8002`, localhost only

## What is in this repository

Final files from the archive `agent-lab-2.zip` (328 files, 29 October 2026):

| File | What it is |
| --- | --- |
| `agent.py` | Core agent, 9,538 lines. Compiles with `py_compile`. |
| `panel.py` | Flask panel, 1,230 lines. Footer reads **V22.9.2**. |
| `dock/config.json` | Main brain setting. Left on `huihui_ai/qwen3-abliterated:8b` from a test — switch it back to `qwen3:14b` if you want the default brain. |
| `dock/manifests/*.json` | Model cards for `qwen3:14b`, `qwen3:4b`, `dolphin3:8b`. |
| `skills/*.md` | 41 pure-prompt skill packs. Skills are prompts, not auto-posting code. |
| `memory/`, `memory.db` | File-per-fact memory plus a SQLite episode log (2,323 episodes). Audit it before reuse — it contains duplicates and stale facts. |
| `chats/*.jsonl` | 50 chat transcripts, 11–29 Oct 2026. Prompts plus final answers only. |
| `jobs/done/*.md` | 80 completed worker handoff reports. |
| `voice/` | Voice samples and state. Slot 28 was active at the end. |
| `start-agent.bat` | Windows starter: activate `.venv`, run `python agent.py`. |

**Missing from the archive, by design:** the Python virtual environment
(`.venv`) and the voice-sidecar folder were too large to upload. Recreate them
from Chapters 8 and 9 of the PDF. Do not assume they are hidden in the zip.

**Intentionally not in this cleaned repository:** chat transcripts, the
agent's memory files and databases, job briefs and handoff logs, diagnostic
logs, private test files, and compiled cache files were removed before
publication. No one reading this repository can see what the author chatted
about, what the agent remembered, or what jobs it ran. One additional file
from the original archive was excluded on safety grounds and was not run or
copied. The code, dock, skills, research notes, and voice reference files
that remain are the project itself, not its personal history.

## Quick start (condensed — full steps in the PDF, Chapter 8)

1. Install Ollama, set `OLLAMA_MODELS` to your model folder, then:
   ```powershell
   ollama pull qwen3:14b
   ```
2. Create a venv in `E:\AGENT\agent-lab`, activate it, install `openai`,
   `flask`, `playwright`, then `playwright install chromium`.
3. Copy `agent.py` and `panel.py` into that folder, with those exact names.
   Set `dock/config.json` to the brain you actually want.
4. Run the panel:
   ```powershell
   python panel.py
   ```
   Open `http://127.0.0.1:5000`, hard refresh with Ctrl+Shift+R, and check
   the footer first. **It must read V22.9.2.** If it does not, fix the install
   before you debug anything else.
5. Test one thing per turn, and wait for each turn to fully finish before
   typing the next prompt. Overlapping turns were a known fragility in this build.

Context: the archive files carry `NATIVE_NUM_CTX = 8192`. Fahim later ran at
16,384 and reported speed felt fine. If you want 16K, set it in one place and
record how you set it — a reinstall resets a file edit to 8192. Bigger context
does not fix confabulation; it can preserve confusing history too.

## Voice, in brief

Voice v1 was a CPU cascade, so it would never take VRAM from the brain:

```
Panel mic → Silero VAD (CPU) → Whistle STT (CPU) → qwen3:14b brain (GPU)
→ Qwen3-TTS 0.6B (CPU) → panel speaker
```

- Two voice slots, **22** and **28**. Slot **28** (Caitlin, teasing) was the
  primary voice at the end, and the active slot in `voice/active-voice.json`.
- ICL cloning (long reference + Whistle transcript) reached about **70%**
  in Fahim's judgement, up from robotic x-vector output. The 1.7B model did
  not beat 0.6B in a direct test, so 0.6B was locked in.
- Fish Audio was considered, then shelved: S2-Pro needs 24 GB on GPU or CPU,
  Drama 3 needs 48 GB GPU and no CPU, and the cloud API was excluded by the
  zero-cost rule.
- Three live bugs, found in one night and fixed in the final files:
  torchaudio loader (fixed with soundfile), webm fragments (fixed with PCM
  capture in panel v22.9.2), and a wrong browser mic input (the cause of
  digital silence, max 0.000 on every chunk).
- Even after those fixes, voice was **not usable as conversation**: about
  10–12 seconds to the first spoken reply, slowing as history grew, and
  sometimes two voice lines running over each other (a panel playback race:
  playback was marked busy only after the TTS fetch finished, not before).

Full voice detail, including how to recreate the sidecar, is in Chapter 9
of the PDF.

## What worked, what did not

**Worked, with evidence in the archive:**

- Clean brain Q&A, desktop control (Discord launched with a verified PID,
  Chrome private mode, brain switching), and honest failure (a PDF question
  answered with a plain no-library error instead of an invented summary).
- 80 completed job handoffs with verification sections.
- Voice pipeline in pieces: Silero, Whistle, Qwen 0.6B clone, sidecar health,
  and PCM capture with no sidecar error.

**Did not work:**

- Free-chat confabulation: invented opinions and facts instead of saying
  “I don't know”, e.g. an invented plot for a show, and a follow-up question
  losing its referent (Halloween: 31 October, but answered with today's
  weekday, Thursday 29 October 2026, instead of Saturday 31 October 2026).
- Canned chatter fallbacks for vague prompts, instead of clarification.
- Voice conversation as a whole, for the reasons above.
- The 28-test suite was declined on 29 October 2026, so the v14.8.14 fixes
  and everything built on them stayed sandbox-only — later oddities were
  harder to attribute.

## Where it stopped

On the night of 29 October 2026, after the voice tests, Fahim said he was
**abandoning this project, not parking it**. He had tried to make a great
thing at a smaller scale, and he felt he had failed, with no real result.
He felt powerless when nothing worked.

In his own terms, as he put it at the end:

> I will wait for a better AI agent or bot to help do this, so that people
> can have their own local agent in the future. A true AI companion that is
> truly intelligent.

That hope is left here, in the open, for whoever picks up this kind of work
next — with better tools, better models, or a better way to do conversation
locally.

## If you pick this up

1. Prove **one reliable daily job** live, end to end, before adding features.
2. Fix the voice playback race first: mark playback busy *before* the TTS
   fetch, not after, and serialize the queue strictly.
3. Decide think for voice explicitly, and trim voice history — do not send
   the full chat history to every voice turn.
4. Consider a speech-native or GPU TTS path honestly if conversational
   latency is your bar. CPU TTS will always lag cloud speech.
5. Test live, one turn at a time, with footer version, brain, wait-for-turn,
   and exact error text. Do not accept sandbox proof as live proof.
6. Audit memory before reuse, keep the approval and safety rules, and keep
   any paid or cloud step explicit in this README.

## Safety, secrets, and licence

- **No secrets in this repository.** Never paste API keys, passwords, or
  one-time codes into chat, job briefs, memory, or a public repository.
- **No malware.** Do not use this code to write remote-code-execution or
  exploitation tools. Defensive scanning and review are allowed uses.
- **Localhost only.** The panel and sidecar are not meant to be exposed to
  the internet. Exposing them exposes file, shell, and browser tools.
- **Audio privacy.** Voice turns log text transcripts only by design.
  Audio is not stored by default.
- **Licence:** there is no licence file in the archive, and this README
  does not choose one for the author. Add a licence of your own choosing
  before you publish, or use the licence the author chooses if you are
  republishing with permission. Until then, treat the code as all rights
  reserved.

---

*Agent Lab, 6–29 October 2026. Author: MD Fahim Nafis.*
*So long, and goodbye — the repository stays, so the work does not disappear
with the decision to stop.*
