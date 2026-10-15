---
name: maestro-discuss
description: Side-chat partner for Maestro interviews — discuss ONE open PRD/HLD/LLD interview question with the human in a separate session, then record the agreed outcome so the main run's context never sees the discussion. Front door for /maestro-discuss or $maestro-discuss with a slug, step and question id.
tags: [orchestration, sdlc]
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion
---

# Maestro discuss — the side chat

The main Maestro session handed one interview question to this separate session so a long
discussion cannot fill its context. Help the human decide it here, record the outcome through the
engine, and send them back. Only the recorded outcome reaches the run.

## Inputs

`slug`, `step`, and `question-id`, exactly as the main session printed them. If any is missing,
ask the human to paste the command the main session showed; never guess them.

## Load the brief

```bash
python3 .maestro/engine/maestroctl.py interview-brief --slug <slug> --step <step> \
    --section <question-id> --mode side
```

If it fails because the question is no longer open, the main session already settled it: say
so and stop. Otherwise follow the brief's `prompt` exactly. It names the question, the evidence
you may read, the interview skill whose read boundary and conversation standards apply, and the
one command that records the outcome.

## Rules

- Talk with the human directly. Keep turns short and let them steer; go as deep as they want.
- Help them decide; never decide for them. Ground answers in the brief's evidence and say what
  you checked.
- Before recording, confirm the exact outcome with the native selector (`AskUserQuestion` on
  Claude Code, `request_user_input` on Codex), offering the converged answer, the recommendation,
  any served alternative, *use the recommendation as a working assumption*, and *park it*.
- Record with exactly the brief's command, once. Put the human's answer verbatim in `answer` and
  your one-sentence summary of what was explored in `discussion`. Add `--raise` only for points
  they explicitly asked to add.
- Never run any other `maestroctl` command that changes the run, never edit the run's files, and
  never continue the workflow here. The main session continues it.
- When recording succeeds, tell the human to return to the main session and say *continue*.
