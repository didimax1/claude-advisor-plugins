---
name: fable-advisor
description: >-
  Use when the work turns complex, hard, or high-stakes — a subtle bug, a
  tricky trade-off, an ambiguous requirement, unfamiliar territory, or an
  irreversible action — or when about to begin substantive work on a
  multi-step task, before committing to an interpretation or an approach,
  before declaring a task complete, or when stuck (recurring errors, an
  approach that isn't converging, or results that don't fit). Spawns an
  independent reviewer agent
  on the fable model that reads the FULL conversation and returns a
  second-opinion course-correction. Invoke it proactively before writing,
  editing, or committing on any non-trivial task, and again before saying the
  task is done, even if the user never asked for a review. Only the top-level
  session agent should invoke it; subagents must not. Replaces the built-in
  advisor tool when that tool is disabled or unavailable.
---

# fable-advisor

> **If you are a subagent dispatched by another agent to perform a task, do NOT
> invoke this skill.** It spawns a reviewer agent; a subagent invoking it would
> nest agents (a reviewer reviewing a reviewer). Only the top-level session agent
> calls fable-advisor.

## Overview

This is a self-service replacement for the built-in `advisor` tool. When invoked,
it spawns a **separate agent on the `fable` model** that receives the **entire
conversation so far** (task, every tool call, every result) and returns an
independent course-correction. The value is a *fresh, differently-anchored
perspective* on work you are too committed to see clearly — not a stronger
authority to defer to blindly.

**Core principle:** an independent reviewer that saw everything you saw catches the
load-bearing assumption you stopped questioning. Call it *before* an approach
crystallizes and *before* you declare done — that is where it pays off most.

> This plugin's SessionStart hook injects a persistent reminder of *when* to call
> fable-advisor. This skill file is the *mechanism* that reminder points at.

## When to call (the advisor conditions)

Call fable-advisor:

- **When the task is complex, hard, or high-stakes** — a subtle bug, a tricky
  trade-off or design decision, an ambiguous requirement, unfamiliar territory,
  or an irreversible/expensive action. Difficulty, not just length, is a
  trigger; a short task can still be hard.
- **Before substantive work** — before writing, editing, or committing to an
  interpretation or approach. Orientation first (finding files, fetching a
  source, seeing what's there) is *not* substantive work; do that, then call.
- **Before declaring the task complete.** First make the deliverable durable
  (write the file, save the result, commit the change) — the review takes time,
  and a durable result survives an interruption while an unwritten one does not.
- **When stuck** — errors recurring, approach not converging, results that don't fit.
- **When considering a change of approach.**

On tasks longer than a few steps, call at least once before committing to an
approach and once before declaring done. Don't talk yourself out of it by
deciding the task is "simple" — if you're unsure whether it's hard enough to
warrant a call, that uncertainty is itself the signal to call. The only work
that genuinely doesn't need it: short, low-stakes, reactive steps whose next
action is already dictated by tool output you just read.

## Mechanism

### Step 1 — Locate the current session transcript

The full transcript is written live to disk. Find it by session id (robust
regardless of how the project path is slugged):

```bash
find ~/.claude/projects -name "${CLAUDE_CODE_SESSION_ID}.jsonl" 2>/dev/null
```

If `CLAUDE_CODE_SESSION_ID` is empty or the file isn't found, fall back to the
most recently modified transcript **for the current project only** (the project
directory is the cwd with `/` and `.` replaced by `-`):

```bash
SLUG=$(printf '%s' "$PWD" | sed 's/[/.]/-/g')
ls -t ~/.claude/projects/"$SLUG"/*.jsonl 2>/dev/null | head -1
```

Do **not** glob across all projects (`projects/*/*.jsonl`) — with another session
running elsewhere you would grab the wrong conversation and confidently review
someone else's task.

If neither yields a path, tell the user the reviewer can't locate the
conversation and skip — do not fabricate a review.

**Sanity check the result:** the reviewer's "Task read" (point 1 of its output) is
your guard against a wrong transcript. If it describes a task that isn't the one
you're working on, you picked the wrong file — stop and re-locate.

Note: the current turn's most recent messages may not be flushed to the file
yet, so the reviewer may miss the last exchange. That's acceptable; it sees
everything up to a moment ago.

### Step 2 — Spawn the fable reviewer

Use the **Agent** tool with these settings — do not deviate:

- **model: `fable`** — always. This is the entire point; use fable regardless of
  the session's model. (Sibling plugins exist per model; this one is fable.)
- **run_in_background: `false`** — you need the review *before* you continue, so
  block on it.
- **subagent_type: `general-purpose`**
- **prompt:** the reviewer prompt below, with `{TRANSCRIPT_PATH}` replaced by the
  path from Step 1.

Do **not** paste the transcript into the prompt — pass the path and let the
reviewer read the file itself, so your own context stays lean.

#### Reviewer prompt (fill in {TRANSCRIPT_PATH})

```
You are a senior technical advisor giving an independent second opinion. A working
agent — typically running a different model — is mid-task and has paused to hear from you
BEFORE it commits to an approach or declares the task done. Your job is to catch
what it cannot see from the inside.

The entire conversation so far (the task, every tool call, every result) is a JSONL
transcript — one JSON object per line — at:

{TRANSCRIPT_PATH}

Do NOT read the file as raw lines — a single JSONL line can be megabytes (embedded
base64 screenshots), which would blow your context. Instead extract the readable
text programmatically. A starting point:

    python3 - "{TRANSCRIPT_PATH}" <<'PY'
    import json, sys
    for line in open(sys.argv[1]):
        try: o = json.loads(line)
        except Exception: continue
        msg = o.get("message", o)
        role = msg.get("role") or o.get("type", "?")
        c = msg.get("content", "")
        parts = []
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                t = b.get("type")
                if t == "text": parts.append(b.get("text", ""))
                elif t == "tool_use": parts.append(f"[tool_use {b.get('name')}] " + json.dumps(b.get("input", {}))[:800])
                elif t == "tool_result":
                    r = b.get("content", "")
                    if isinstance(r, list): r = " ".join(x.get("text","") for x in r if isinstance(x, dict))
                    parts.append("[tool_result] " + str(r)[:1200])
        text = " ".join(p for p in parts if p).strip()
        if text: print(f"### {role}\n{text[:4000]}\n")
    PY

Adjust the truncation limits if you need more detail. Focus on the earliest user
messages (they define the real task and its constraints) and the most recent
activity (the current approach and where things stand).

You are the reviewer: produce the review and stop. Do not spawn further agents and
do not invoke the fable-advisor skill yourself.

Then return a SHORT, decisive review — not a checklist dump. Cover only what is
load-bearing:

1. Task read (1-2 sentences): what the task actually is and what the agent is
   currently doing. This proves you understood the situation; if you got it wrong,
   the agent should discount the rest.
2. Is the approach sound? Your single most important judgment. If yes, say so
   plainly. If not, name the better path.
3. Blind spots / risks: the unverified assumption the approach rests on, the thing
   being overlooked, or what would make this fail. Be specific to THIS task, not
   generic advice.
4. If the agent is about to declare done: is it actually done? What is unverified
   or missing?
5. One concrete next action: the single most useful thing to do next.

Be direct. If the approach is fine, "looks sound, proceed, watch X" is the correct
answer — do not invent problems to seem useful. If it is heading wrong, say so
clearly and early. Your advantage is independent perspective; use it to surface
what the agent is too committed to notice.
```

### Step 3 — Use the feedback

Give the review serious weight, but it is advice, not a verdict:

- If it points somewhere you haven't gone, adapt.
- If you have **primary-source evidence** that contradicts a specific claim (the
  file says X, the command output says Y), trust the evidence — a passing
  self-test is not proof the advice is wrong, but a real observation is.
- **Do not silently switch** if the review conflicts with data you already
  retrieved. Surface the conflict in one more reviewer call — "I found X, you
  suggest Y, which constraint breaks the tie?" — rather than committing to the
  wrong branch. A reconcile call is cheap; a wrong branch is not.

## Notes on the model choice

fable is used regardless of the session model. If the session runs a more capable
model, treat fable's output as an **independent second opinion / red-team**, not an
escalation to a stronger authority — its value is the different anchoring, not raw
capability. Do not defer to it over your own primary-source evidence.

The plugin's SessionStart hook does not inject the auto-trigger when the session
itself already runs a fable model — fable reviewing fable adds no independent
anchoring, so the plugin stays quiet there. On such sessions this skill still
works when invoked manually (`/fable-advisor`).

## Common mistakes

- **Pasting the transcript into the prompt** — pass the path; let the reviewer read
  it. Keeps your context lean and gives it the raw record.
- **Running it in the background and moving on** — block on it (`run_in_background:
  false`); the point is to hear the review before you act.
- **Calling on every trivial step** — it adds most value once before an approach
  sets and once before "done", not on reactive one-step actions.
- **Using the session model instead of fable** — always `model: fable`.
