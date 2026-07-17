#!/usr/bin/env python3
"""SessionStart hook for the fable-advisor plugin.

Injects a persistent, advisor-style trigger block so the TOP-LEVEL agent invokes
the `fable-advisor` skill at the right checkpoints (before substantive work,
before declaring done, when stuck, when changing approach). This restores the
mid-reasoning self-invocation the built-in advisor had — a skill description
alone does not reliably fire at those internal checkpoints.

Self-gating — either condition keeps the hook silent:

1. The session itself already runs a fable-family model: the reviewer this
   plugin spawns IS fable, so such a session gains nothing from the trigger.
   Session-scoped evidence is consulted first: the hook input's optional
   `model` field (present on interactive startup, where it reflects the
   *active* model even under `claude --model ...`; absent after `/clear` and
   on headless `-p` runs), then the last assistant message in the session
   transcript (covers compact). Without session-scoped evidence the hook falls
   back to launch defaults — ANTHROPIC_MODEL and the `model` key across
   settings files — and silences only when ALL of them point at fable; any
   conflict or absence fails OPEN (injects): losing the reviewer on a
   sonnet/opus session costs more than a redundant nudge on a fable one.
   Residual gap: a `claude --model sonnet` session on a machine whose saved
   default is fable goes silent after /clear (the flag is invisible to the
   hook). The mirror-image false injection is harmless — the trigger block
   itself tells fable sessions to ignore it.
2. The user disabled the fable-advisor skill via `/skills` (recorded as a
   `skillOverrides` entry in settings), so no "ghost instruction" points at a
   disabled skill.

Disabling the whole plugin via `/plugin` removes this hook entirely, which is
the primary off switch.
"""
import json
import os
import sys

SKILL = "fable-advisor"
# Model families the spawned reviewer is equivalent to. claude-mythos-5 is the
# same underlying model as claude-fable-5 (only the ID differs), so a mythos
# session gains nothing from a fable reviewer either. Matched as substrings so
# aliases ("fable", "fable[1m]") and full IDs ("claude-fable-5[1m]") all count.
REVIEWER_FAMILIES = ("fable", "mythos")

TRIGGER_BLOCK = """<FABLE_ADVISOR>
You have a `fable-advisor` skill: an independent second-opinion reviewer — a separate agent on the fable model that is handed your FULL conversation (task, every tool call, every result) and returns a course-correction. It replaces the disabled built-in advisor tool. Treat the following as standing instructions for this session: invoke the skill (Skill tool: `fable-advisor`) proactively, even when the user did not ask for a review, whenever the work you are doing for the user turns non-trivial. Concretely, call it —

- When the task is COMPLEX, HARD, or HIGH-STAKES: a subtle bug, a tricky trade-off or design decision, an ambiguous or under-specified requirement, unfamiliar territory, or an irreversible/expensive action. Difficulty — not just length — is a trigger; a short task can still be hard.
- BEFORE substantive work on any multi-step task: before writing, editing, or committing to an interpretation or an approach. (Orientation — finding files, reading a source, looking around — is NOT substantive work; do that first, then call.)
- BEFORE declaring a task complete: first make the deliverable durable (write the file, save the result, commit the change), then call.
- When STUCK: errors recurring, an approach not converging, results that don't fit.
- When CONSIDERING A CHANGE OF APPROACH.

On any task longer than a few steps you MUST call fable-advisor at least once before committing to an approach and once before declaring done. Do not talk yourself out of it by deciding the task is "simple" — if you are unsure whether it is hard enough to warrant a call, that uncertainty is itself the signal to call. The only work that genuinely doesn't need it: short, low-stakes, reactive steps whose next action is already dictated by tool output you just read.

This applies only to you, the top-level session agent. If you are a subagent dispatched to perform a task, ignore this block entirely — do not invoke fable-advisor (it would nest reviewer agents). Likewise, if the model this session itself runs on is a fable-family model, ignore this block entirely — a fable reviewer adds no independent anchoring to a fable session.
</FABLE_ADVISOR>"""


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def override_value(settings, skill):
    """skillOverrides value for `skill` in one settings dict, or None if unset."""
    if not isinstance(settings, dict):
        return None
    ov = settings.get("skillOverrides")
    if not isinstance(ov, dict):
        return None
    if skill in ov:
        return ov[skill]
    # tolerate qualified keys, e.g. "fable-advisor@market", "plugin:fable-advisor"
    for key, value in ov.items():
        base = key.split("@")[0].split(":")[-1].rsplit("/", 1)[-1]
        if base == skill:
            return value
    return None


def normalize_model(value):
    """Model id/alias as a stripped lowercase string, or None if unusable."""
    if isinstance(value, dict):
        # tolerate an object shape like the statusline input's {"id": ...}
        value = value.get("id") or value.get("display_name")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def is_reviewer_model(norm):
    """True if a normalized model id/alias clearly denotes the reviewer family.

    "best" counts: it resolves to Fable 5 wherever the org has fable access,
    and where it doesn't, the fable reviewer can't be spawned anyway. Aliases
    that merely MAY resolve here ("default") do not count — those fail open.
    """
    return norm == "best" or any(f in norm for f in REVIEWER_FAMILIES)


def transcript_model(data):
    """Model of the last top-level assistant message in the transcript, or None.

    Session-scoped evidence like the stdin `model` field, but survives events
    that omit it (compact). Reads only the file's tail; any problem → None.
    """
    try:
        path = data.get("transcript_path") if isinstance(data, dict) else None
        if not isinstance(path, str) or not path:
            return None
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 262144))
            tail = f.read().decode("utf-8", "replace")
        for line in reversed(tail.splitlines()):
            try:
                entry = json.loads(line)
                if entry.get("type") != "assistant" or entry.get("isSidechain"):
                    continue  # sidechains are subagents on possibly other models
                model = entry["message"]["model"]
                if isinstance(model, str) and model:
                    return model
            except Exception:
                continue
    except Exception:
        pass
    return None


def main():
    data = None
    try:
        data = json.load(sys.stdin)
    except Exception:
        pass

    cwd = data.get("cwd") if isinstance(data, dict) else None
    if not isinstance(cwd, str):
        cwd = None
    # CLAUDE_PROJECT_DIR is the project root; the stdin cwd drifts when the
    # session cd's, which would mislocate project settings on /clear or compact.
    root = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    home = os.path.expanduser("~")

    # settings sources, highest precedence first: policy > local > project > user
    sources = [
        "/Library/Application Support/ClaudeCode/managed-settings.json",  # macOS policy
        "/etc/claude-code/managed-settings.json",                          # linux policy
        os.path.join(root, ".claude", "settings.local.json"),
        os.path.join(root, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.json"),
    ]
    settings_dicts = [read_json(path) for path in sources]

    # Gate 1: the session already runs the reviewer's model family — a fable
    # reviewer adds nothing to a fable session, so don't auto-nudge.
    model = normalize_model(data.get("model")) if isinstance(data, dict) else None
    model = model or normalize_model(transcript_model(data))
    if model is not None:
        # session-scoped evidence: decide on it alone
        silent = is_reviewer_model(model)
    else:
        # launch defaults only — a saved default is NOT proof of the active
        # session model (e.g. `--model` overrides it invisibly), so silence
        # only on unanimity; conflict or absence fails open.
        candidates = [normalize_model(os.environ.get("ANTHROPIC_MODEL"))]
        candidates += [normalize_model(s.get("model"))
                       for s in settings_dicts if isinstance(s, dict)]
        candidates = [c for c in candidates if c]
        silent = bool(candidates) and all(is_reviewer_model(c) for c in candidates)
    if silent:
        print("{}")
        return

    # Gate 2: only auto-nudge when the skill is fully enabled. "off" /
    # "name-only" / "user-invocable-only" all mean "no automatic triggering"
    # -> stay silent (user can still /fable-advisor).
    effective = "on"
    for settings in settings_dicts:
        value = override_value(settings, SKILL)
        if value is not None:
            effective = value
            break
    if effective != "on":
        print("{}")
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": TRIGGER_BLOCK,
        }
    }))


if __name__ == "__main__":
    main()
