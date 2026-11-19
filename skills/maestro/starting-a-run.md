# Starting a run without a slug

Part of the `maestro` lead skill; its hard rules and **Talking to the person** apply.

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
- **`status: unreadable`** → the run's saved state has a git merge conflict or cannot be read;
  say so in one line (with the file the `problem` names, so they can fix it) and stop. The human resolves or restores the file; never edit
  it yourself, and never pass `--force` unless the human explicitly asks to start over.
- **No runs exist, or Start new, description already supplied** →
  derive a concise kebab-case slug from the description: its two to five key words (drop filler
  such as "we need", "let users", articles), lowercase ASCII letters and digits joined by single
  hyphens. Tell the human
  in one friendly line that you are starting and the short name the feature is saved under
  ("Starting on phone OTP and Google sign-in — saved as `phone-otp-google-auth`."), and
  continue immediately. Do not stop merely to ask the human to reformat words they already
  supplied. Example: `we need phone OTP and Google auth` → `phone-otp-google-auth`.
  Check the derived slug is free before using it:

  ```bash
  python3 .maestro/engine/maestroctl.py slug-check <slug>   # {available, reason}
  ```

  When it is taken (an earlier run, an active or a delivered plan uses it), add `-2` (then `-3`)
  and check again; tell the person the name you settled on. A slug the person typed themselves
  that is taken: say why in one line (the `reason`) and ask for another — never reuse it.
- **Start new, no description supplied** → ask for the one-line feature description only,
  derive and show the slug using the same rule, then continue immediately. Do not ask a second
  question for a manually formatted slug.

In both new-feature cases, init with `--input feature="<description verbatim>"`. That
description is the seed for the workflow's bounded PRD interview when no requirement files exist.

The default workflow also needs `--input path=major|minor`. When the invocation did not give it,
ask the person with the native selector — **Major**: a new feature or a change across
repositories (a full PRD and plan); **Minor**: a small, contained change (a mini PRD and a short
plan). Never infer it from the description and never default it.

The `bugfix` workflow (`/maestro <slug> bugfix branch=<b>`, the short name for
`.maestro/workflows/bugfix.yaml`) takes `--input branch=<b>` instead of `path`: the branch the bug
is on. When the invocation did not give it, ask the person which branch the bug is on, in one
line; never guess it (not `main`, not the current checkout's branch) and never default it. Its
`feature` is the one-line bug description, verbatim, like a feature's.
