# Interview discussions

Part of the `maestro` lead skill; its hard rules apply. Used by `ask_interview` and
`ask_interview_batch` when the human is unsure, asks something back, or wants to raise a point.

Take each item where the human chose *Not sure*, asked
something back, or left a `must_resolve` fact open, one at a time. The reading and reasoning for a
discussion must never enter your context, so you only relay. Get the engine's brief first:

```bash
python3 .maestro/engine/maestroctl.py interview-brief --slug <slug> --step <step> \
    --section <question-id>                # add --mode side for a side chat
```

*Default — isolated subagent.* Preflight the brief's `skill`, then spawn its `agent_type` with its
`model` (Claude Code `Task`; Codex native subagent). Send the brief's `prompt` VERBATIM followed by
the human's message verbatim. Show the human the subagent's reply verbatim, minus its final JSON
line. Relay each follow-up to the SAME subagent (`SendMessage` on Claude Code); where the host
cannot continue a subagent, start a fresh one with the brief, the last JSON `summary`, and the new
message. Never answer from your own reading, never read the evidence yourself, and never
paraphrase or extend a reply. Keep only each final JSON line (`status`, `candidate`, `summary`);
let the reply text go.

*Side chat — for a deep dive, or the human's choice.* Offer it whenever the human wants room to
dig ("take it to a side chat"), and use it always where there is no subagent support (inline
mode). First record every other clear answer of the round with `interview-record-batch` (a partial
batch is valid and leaves the rest pending). Then run `interview-brief --mode side` and show the
human its `side_chat` command for their harness: open a new chat, run it, come back and say
*continue*. End your turn. On *continue*, call `next`: a question settled in the side chat is gone
from the served round; one still open is served again — ask whether to discuss it again or answer.

Close each subagent discussion with a native selector: the subagent's `candidate` (when present),
the recommendation, any served alternative, *Use the recommendation as a working assumption*,
*Park it as an open item*, *Take it to a side chat*, plus the free-form option. For *I want to raise
something*, take the point in their words and confirm the exact wording to record; route any
question it prompts through the same discussion path.
