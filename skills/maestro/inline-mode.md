# Inline mode — a host with no subagent tool

Part of the `maestro` lead skill; its hard rules and **Talking to the person** apply: working
inline changes nothing the person sees — still only each action's `say` line, never the served
prompt or your working.

No subagent tool (Cursor, or a Codex installation with subagents disabled)? Switch to
**inline mode** and
tell the person once: *"Running every step here in this session, one at a time."*

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
