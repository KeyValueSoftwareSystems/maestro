# Starting a run without a slug

Part of the `maestro` lead skill; its hard rules apply.

Ask the engine what runs exist before deciding whether this is a resume or a new feature:

```bash
python3 .maestro/engine/maestroctl.py runs        # read-only JSON: [{slug, status, workflow, active, ...}]
```

When runs exist and the user did not name one explicitly, present the choice with the host's
native selector: `AskUserQuestion` on Claude Code, or `request_user_input` on Codex when that
tool is available. Labels are yours, but the slugs come **verbatim** from the engine output —
never from memory. Label each entry `resume <slug> — <status>`. Show one option per existing run plus
**"Start a new feature"**. The auto-added *Other* lets the human type a slug directly. If the
host exposes no selector (for example Codex Default mode), print the same choices as a numbered
list, explicitly ask for the number or slug, and WAIT; plain text is the required fallback,
not a failed gate.

- **Resume** → use the chosen slug and continue to Setup (init is a no-op resume).
- **`status: unreadable`** → the ledger has a git merge conflict or cannot be parsed; show
  the engine's `problem` text and stop. The human resolves or restores the file; never edit
  it yourself, and never pass `--force` unless the human explicitly asks to start over.
- **No runs exist, or Start new, description already supplied** →
  derive a concise kebab-case slug from the description: its two to five key words (drop filler
  such as "we need", "let users", articles), lowercase ASCII letters and digits joined by single
  hyphens. Tell the human
  in one friendly line that you are starting and the short name the feature is saved under
  ("Starting on phone OTP and Google sign-in — saved as `phone-otp-google-auth`."), and
  continue immediately. Do not stop merely to ask the human to reformat words they already
  supplied. Example: `we need phone OTP and Google auth` → `phone-otp-google-auth`.
- **Start new, no description supplied** → ask for the one-line feature description only,
  derive and show the slug using the same rule, then continue immediately. Do not ask a second
  question for a manually formatted slug.

In both new-feature cases, init with `--input feature="<description verbatim>"`. That
description is the seed for the workflow's bounded PRD interview when no requirement files exist.
