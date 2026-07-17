# claude-advisor-plugins

A Claude Code plugin marketplace providing **independent second-opinion reviewer**
plugins that replace the built-in `advisor` tool (useful when the built-in
advisor is disabled or unavailable). Each plugin targets sessions running a
*different* model than its reviewer — a session already running the reviewer's
own model gains nothing, so the trigger turns itself off there.

Each plugin bundles two things:

1. A **skill** (`fable-advisor`) — the mechanism. When invoked it spawns a separate
   agent on a fixed reviewer model, hands it the full session transcript, and
   returns a course-correction.
2. A **SessionStart hook** — the trigger. It injects a persistent, advisor-style
   reminder so the agent invokes the skill *at the right moments on its own*
   (before substantive work, before declaring done, when stuck, when changing
   approach) — the mid-reasoning behaviour a skill description alone can't deliver.

Currently shipped: **`fable-advisor`** (reviewer runs on the `fable` model). More
per-model variants can be added to this same marketplace later.

## Install (teammates)

```bash
claude plugin marketplace add didimax1/claude-advisor-plugins
claude plugin install fable-advisor@claude-advisor-plugins
```

Then restart Claude Code (or `/clear`) so the SessionStart hook loads.

**Access:** this is a **public** repo — anyone can install it; no org membership
or GitHub authentication required.

## Enable / disable

- **Whole feature (skill + hook) —** the primary switch: `/plugin` → toggle
  `fable-advisor`, or `claude plugin disable fable-advisor@claude-advisor-plugins`.
  Disabling the plugin removes the hook entirely, so no reminder is injected.
- **Just the skill —** `/skills` → disable `fable-advisor`. The hook self-gates on
  this: when the skill is disabled (or set to name-only / user-invocable-only) the
  reminder stops injecting, so you never get a reminder pointing at a disabled
  skill. (An already-open session keeps the reminder until its next start/clear.)
- **Fable sessions (automatic) —** when the session itself already runs a fable
  model (`/model fable`, a `claude-fable-5...` model ID, `[1m]` variants — plus
  `claude-mythos-5`, the same underlying model, and the `best` alias, which
  resolves to Fable 5 wherever the fable reviewer could run at all), the hook
  stays silent on its own: a fable reviewer adds nothing on top of a fable
  session. Sessions on other models (sonnet, opus, …) keep the trigger, and
  `/fable-advisor` still works manually anywhere. Detection: the hook input's
  `model` field (present on interactive startup, where it reflects the active
  model even under `claude --model ...`) or the session transcript (covers
  compact); without those, `ANTHROPIC_MODEL` and the `model` setting must
  *unanimously* say fable — any conflict or absence triggers as usual (fail
  open). Known gap: a `claude --model sonnet` session on a machine whose saved
  default model is fable loses the trigger after `/clear` (the flag is
  invisible to the hook). The mirror-image mistake is harmless: the trigger
  block itself tells fable sessions to ignore it, so a fable session the hook
  fails to detect only pays a few context tokens.

## Updating

When a new version is published to the marketplace:

```bash
claude plugin marketplace update claude-advisor-plugins
claude plugin update fable-advisor@claude-advisor-plugins
```

Restart Claude Code to apply.

## What it costs

On sessions where the hook triggers (non-fable model, skill enabled), the
reminder adds a small, fixed number of tokens to the system context; self-gated
sessions (fable model, or skill disabled) get no reminder and pay nothing. Each
actual review is one `fable`-model agent call over your transcript, run only
when a checkpoint is hit — not on every step.

## Requirements

- `python3` on `PATH` (the SessionStart hook is a small Python script).
- The reviewer model (`fable`) available to your account.

## Layout

```
.claude-plugin/marketplace.json        # marketplace manifest
plugins/fable-advisor/
  .claude-plugin/plugin.json           # plugin manifest
  skills/fable-advisor/SKILL.md        # the reviewer mechanism
  hooks/hooks.json                     # SessionStart registration
  hooks/session-start.py               # self-gating reminder injector
```

## Notes

- If you also run the **superpowers** plugin, its `brainstorming` trigger is very
  aggressive and may take the "before substantive work" slot on build/design
  tasks before fable-advisor does. fable-advisor still fires on complex/high-stakes
  decisions, when stuck, and before declaring done.
