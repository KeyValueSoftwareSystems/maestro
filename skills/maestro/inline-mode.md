# Inline mode — a host with no subagent tool

Part of the `maestro` lead skill; its hard rules apply.

No subagent tool (Cursor, or a Codex installation with subagents disabled)? Switch to
**inline mode** and
tell the user once: *"No subagent support here — running steps inline and sequentially;
per-step models are ignored (everything runs on this session's model)."*

- Always call `next`/mutating commands with `--serial` so the engine serves parallel
  branches one step at a time (never expect `run_agents`).
- For `run_agent`: execute the served prompt YOURSELF — load the named skill and do the
  work — then call `complete` exactly as a subagent would have been completed.
- `run_lead`, `ask_interview`, and `ask_interview_batch` behave the same in every harness,
  except that interview discussions always use the side chat: with no subagent, there is no
  other way to keep them out of this context.
- Context discipline still applies: after each inline step, carry forward only the JSON
  outputs; do not keep artifact contents in mind — re-read from disk in the step that
  needs them.
