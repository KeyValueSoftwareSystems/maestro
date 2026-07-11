# Maestro workflow spec — v1

A workflow is a directed graph of **nodes** described in one YAML file. It is executed by the
**lead agent** (the user's interactive session running `/maestro <slug>`), which never interprets
the graph itself: the deterministic resolver (`engine/maestroctl.py next`) reads the workflow +
the per-feature state ledger and serves exactly one next action as JSON.

The machine-readable contract is `engine/schemas/workflow.schema.json`. The builder UI
(`ui/builder.html`) embeds the same schema and reads/writes this format losslessly.

## YAML subset

Workflow files are restricted to a strict YAML subset (parsed by `engine/wf.py`, no external
dependencies): block mappings and lists, flow lists `[a, b]` and flow maps `{a: b}` on one line,
plain / single- / double-quoted scalars, `|` and `|-` block literals, comments. Anchors, aliases,
tags, multi-document files and folded scalars (`>`) are **not** supported. The builder UI emits
only this subset.

## Minimal authoring

Only `nodes:` is required. Everything else has a sensible default:

- `version:` defaults to 1 · `name:` optional · `start:` defaults to the **first node**
- a node with no `type:` is an **agent**
- a node with no `next:`/`routes:` implicitly ends the workflow (`next: end`)
- `slug` is always available as an input; other inputs only need declaring when used

The smallest valid workflow:

```yaml
nodes:
  - id: review
    instruction: Review the changes and summarize what you find.
```

## Top level

```yaml
version: 1                  # spec version; anything else is rejected
name: design                # kebab-case identifier
description: Design phase.  # optional prose
inputs:                     # declared inputs (all optional keys except the map itself)
  slug:    {type: string, required: true, description: kebab-case feature id}
  feature: {type: string, required: false, default: "${inputs.slug}"}
defaults:                   # optional per-workflow fallbacks
  model: haiku              # model for agent nodes that don't set one
  agent: general            # subagent type fallback (agents/general.md)
  max_visits: 10            # global revisit cap fallback
start: first_node_id        # entry node
nodes: [ ... ]              # the graph (see node types)
outputs:                    # optional; values surfaced to a calling workflow / final report
  hld_path: ".maestro/${inputs.slug}/hld.md"
ui: { ... }                 # optional, free-form editor metadata — engine ignores, round-trips
```

`inputs.<name>.type` is one of `string | number | boolean | list`. Inputs with `required: true`
must be provided at `init`; others fall back to `default` (which may itself contain
placeholders over other inputs).

## Placeholders

Pure string substitution — no templating engine, no filters, no expressions. Four namespaces:

| Placeholder | Meaning |
|---|---|
| `${inputs.<name>}` | workflow input value |
| `${steps.<id>.outputs.<field>}` | recorded output of a completed step |
| `${steps.<id>.branches.<key>.outputs.<field>}` | a parallel-branch result |
| `${config.<dot.path>}` | value from an optional `maestro.config.yaml` at the repo root (advanced; nothing ships or requires one) |

An unresolvable placeholder is a hard error (validation error when statically checkable,
runtime error otherwise). Inside a parallel branch, `${steps.<id>…}` resolves branch-local step
ids first, then workflow-level ids.

## Conditions

`when:` on routes uses a tiny grammar — exactly these forms, nothing else:

```
${...} == <literal>        ${...} != <literal>
${...}                     # truthy: false for "", "false", "0", "null", missing
${...} in [a, b, c]
```

Literals: bare words, numbers, `true`/`false`, single- or double-quoted strings. Comparison is
string-wise after normalising numbers and booleans (`"3" == 3`, `"true" == true`).

## Routing

Every node routes with exactly one of:

```yaml
next: <node-id>             # unconditional
routes:                     # first matching wins
  - {when: "${steps.review.outputs.blocking} == true", to: fix}
  - {to: contract_gate}     # last entry MUST be the default (no `when`)
```

Gate nodes route through their `options` instead (below). Reserved targets:

- `end` — workflow completes successfully.
- `abort` — workflow terminates as failed.

### Back-edges (cycles)

A route may target **any** node, including earlier ones — that is how loops are expressed.
Engine semantics when a route lands on an already-`done` node:

- **Re-entry reset:** the target and every `done` node reachable from it are reset to
  `pending` (cascade, graph-aware), so the flow genuinely re-runs from that point. Gate
  decision history and visit counters are preserved.
- **Visit caps:** the engine counts how many times each node is entered. A node exceeding its
  `max_visits` (node value → `defaults.max_visits` → 10) routes to its `on_exhausted:`
  (`<node-id> | abort | ask`; default `ask` = a synthesized "loop limit reached — continue
  anyway / abort" gate).

The validator allows cycles but warns about cycles containing no gate and no script node
(pure agent↔agent cycles burn tokens with no human or deterministic brake).

### Failure

`on_fail: <node-id> | abort | ask` (default `ask`) applies when a node fails after exhausting
its `retries`. `ask` synthesizes a gate: **Retry / Skip this step / Abort**, with the failure
reason. Skipping marks the node `skipped` and takes its default route.

## Node types

### `agent`

The workhorse: the lead agent spawns a subagent for it.

```yaml
- id: author_hld
  type: agent
  instruction: |            # REQUIRED — what this step must do, in plain language.
    Write the high-level design for this feature from the requirement folder.
    Surface unresolved decisions as open questions.
  skill: plan               # optional pin: subagent must load skills/plan/SKILL.md.
                            # Omit for "auto": harness skill-discovery picks the best match.
  agent: planner            # optional subagent type (agents/planner.md); default defaults.agent
  model: sonnet             # optional; default defaults.model
  inputs:                   # optional map, passed verbatim into the subagent prompt
    feature: "${inputs.feature}"
    slug: "${inputs.slug}"
  outputs: [hld_summary]    # fields the subagent must return as last-line JSON (small scalars)
  artifact: ".maestro/${inputs.slug}/hld.md"   # string or list; engine refuses to mark the
                            # step done unless every artifact exists non-empty ("proof, not
                            # promises")
  retries: 1                # re-dispatches on failure before on_fail applies (default 1)
  next: oq_serve
```

### `gate`

A human decision. Options ARE the outgoing edges. Gates are **never** skipped on resume.

```yaml
- id: hld_approval
  type: gate
  prompt: "HLD ready: ${steps.author_hld.outputs.hld_summary}. Approve?"
  options:
    - {id: approve, label: "Approve — proceed to LLD", to: author_llds}
    - {id: revise,  label: "Request revisions", to: author_hld, input: feedback}
    - {id: reject,  label: "Reject — abort", to: abort}
```

`input: <name>` collects free text into `${steps.hld_approval.outputs.<name>}`. A revise option
is simply an option whose `to:` is a back-edge — re-entry reset cascades automatically.

### `script`

A deterministic command. Exit 0 → `next`/`routes`; non-zero → `on_fail`. If stdout is a single
JSON object, its fields become the step's outputs and are routable — the generalized
`oq_serve.py` pattern.

```yaml
- id: oq_serve
  type: script
  run: ["python3", "engine/oq_serve.py", ".maestro/${inputs.slug}/open-questions.json"]
  timeout: 60               # seconds, optional (default 300)
  routes:
    - {when: "${steps.oq_serve.outputs.state} == ask",    to: oq_ask}
    - {when: "${steps.oq_serve.outputs.state} == refine", to: refine_hld}
    - {to: hld_approval}
```

### `parallel`

Static fork with inline branch subgraphs. The node itself joins; branch results land at
`${steps.<id>.branches.<branch-id>.outputs.<field>}`.

```yaml
- id: author_llds
  type: parallel
  join: all                 # all | any (default all)
  on_branch_fail: fail_all  # fail_all | continue | ask (default fail_all)
  branches:
    - id: backend
      start: backend_design
      steps:
        - id: backend_design
          type: agent
          instruction: Write the backend low-level design from the HLD.
          skill: backend-design
          artifact: ".maestro/${inputs.slug}/lld/backend.md"
          next: end         # `end` inside a branch = branch complete
    - id: frontend
      start: frontend_design
      steps: [ ... ]
  next: contract
```

Branch bodies may contain `agent`, `gate`, `script` and `subworkflow` nodes (no nested
`parallel` in v1) — a branch wrapping a subworkflow is how sdlc-main runs one impl.yaml per
stack. In harnesses with parallel subagents, ready agent steps across branches are dispatched
as one wave; elsewhere (`next --serial`) branches run one at a time.

### `subworkflow`

Runs another workflow file inline. The child's `outputs:` map becomes the step's outputs; child
steps are namespaced in state (`design/author_hld`). Maximum nesting depth: 4.

```yaml
- id: design
  type: subworkflow
  workflow: workflows/design.yaml
  inputs: {slug: "${inputs.slug}", feature: "${inputs.feature}"}
  next: arch_review
```

## State — `.maestro/<slug>/state.yaml`

Written **only** by `engine/maestroctl.py` (fcntl-locked, atomic tmp+rename). Records workflow
file + sha256 (edits mid-run halt with instructions to `rebase`), inputs, run status + cursor
(active frontier), per-step status / attempts / visits / outputs / artifacts, append-only gate
decision history, and parallel-branch bookkeeping.

Resume: `done` steps are skipped only while their artifacts still exist non-empty on disk;
interrupted (`running`) steps are re-served; gates always re-ask.

## Lead-agent protocol (summary)

```
maestroctl validate <wf>                 # refuse to start on errors
maestroctl init --slug S --workflow <wf> [--input k=v ...]
loop:
  maestroctl next --slug S [--serial]    # → ONE action JSON
    run_agent  → spawn subagent with the pre-rendered prompt → complete --outputs '<json>'
    run_agents → spawn all listed subagents in one parallel wave → complete each
    run_script → execute argv → complete --exit-code N --stdout '...'
    ask_gate   → ask the human → gate-record --option X [--input '...']
    done | failed → report and stop
  on step failure: maestroctl fail --step P --reason '...'
```

The action payload is fully resolved — placeholders substituted, prompts pre-rendered. The lead
agent performs zero interpretation, never edits state, never reads artifacts into its own
context, and never skips a gate.
