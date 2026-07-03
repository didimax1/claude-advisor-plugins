#!/usr/bin/env python3
"""SessionStart hook for the fable-advisor plugin.

Injects a persistent, advisor-style trigger block so the TOP-LEVEL agent invokes
the `fable-advisor` skill at the right checkpoints (before substantive work,
before declaring done, when stuck, when changing approach). This restores the
mid-reasoning self-invocation the built-in advisor had — a skill description
alone does not reliably fire at those internal checkpoints.

Self-gating: if the user disabled the fable-advisor skill via `/skills`
(recorded as a `skillOverrides` entry in settings), this hook stays silent, so
no "ghost instruction" points at a disabled skill. Disabling the whole plugin
via `/plugin` removes this hook entirely, which is the primary off switch.
"""
import json
import os
import sys

SKILL = "fable-advisor"

TRIGGER_BLOCK = """<FABLE_ADVISOR>
You have a `fable-advisor` skill: an independent second-opinion reviewer — a separate agent on the fable model that is handed your FULL conversation (task, every tool call, every result) and returns a course-correction. It replaces the disabled built-in advisor tool. Treat the following as standing instructions for this session: invoke the skill (Skill tool: `fable-advisor`) proactively, even when the user did not ask for a review, whenever the work you are doing for the user turns non-trivial. Concretely, call it —

- When the task is COMPLEX, HARD, or HIGH-STAKES: a subtle bug, a tricky trade-off or design decision, an ambiguous or under-specified requirement, unfamiliar territory, or an irreversible/expensive action. Difficulty — not just length — is a trigger; a short task can still be hard.
- BEFORE substantive work on any multi-step task: before writing, editing, or committing to an interpretation or an approach. (Orientation — finding files, reading a source, looking around — is NOT substantive work; do that first, then call.)
- BEFORE declaring a task complete: first make the deliverable durable (write the file, save the result, commit the change), then call.
- When STUCK: errors recurring, an approach not converging, results that don't fit.
- When CONSIDERING A CHANGE OF APPROACH.

On any task longer than a few steps you MUST call fable-advisor at least once before committing to an approach and once before declaring done. Do not talk yourself out of it by deciding the task is "simple" — if you are unsure whether it is hard enough to warrant a call, that uncertainty is itself the signal to call. The only work that genuinely doesn't need it: short, low-stakes, reactive steps whose next action is already dictated by tool output you just read.

This applies only to you, the top-level session agent. If you are a subagent dispatched to perform a task, ignore this block entirely — do not invoke fable-advisor (it would nest reviewer agents).
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


def main():
    cwd = None
    try:
        data = json.load(sys.stdin)
        if isinstance(data, dict):
            cwd = data.get("cwd")
    except Exception:
        pass
    cwd = cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    home = os.path.expanduser("~")

    # settings sources, highest precedence first: policy > local > project > user
    sources = [
        "/Library/Application Support/ClaudeCode/managed-settings.json",  # macOS policy
        "/etc/claude-code/managed-settings.json",                          # linux policy
        os.path.join(cwd, ".claude", "settings.local.json"),
        os.path.join(cwd, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.json"),
    ]

    effective = "on"
    for path in sources:
        value = override_value(read_json(path), SKILL)
        if value is not None:
            effective = value
            break

    # Only auto-nudge when fully enabled. "off" / "name-only" / "user-invocable-only"
    # all mean "no automatic triggering" -> stay silent (user can still /fable-advisor).
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
