# Domain rules and change scenarios

Optional. Knowledge the code cannot say on its own, written by the project's people: **what must
never break** (invariants) and **what a change quietly affects elsewhere** (change scenarios).
Maestro runs exactly as before without them; when they exist, it uses them. They are part of the
living docs (format: `skills/core/bootstrap/build-knowledge/docs-format.md`) and the only part a
model may never edit.

| Who | Does what |
|-----|-----------|
| The team (developers, domain owners, the client) | Writes and owns the invariants and scenarios; accepts or rejects the model's proposals |
| `build-knowledge`, `retrospect`, workspace sync | Never edit them; write what they find under `## Proposed rules and scenarios` |
| `living_docs.py` (engine) | Restores any change a writer step makes to them (R9); checks them against the code |
| `/maestro-init` | Checks them when present; when absent, asks once whether to create the starter file |
| `feature-impact` | Follows the scenarios a feature triggers into every repository they reach; lists their ids in `impact.json` (`scenarios`) |
| `impact.py validate --prd` (engine) | Adds every scenario whose `when_changing` the PRD names, with its rules and `also_impacts` items, so the match never rests on the agent |
| `impact_trace.py` (engine) | The HLD, then the LLDs, must deal with every listed invariant, scenario and item, or say "no change needed, because …"; gaps go back to the writer |
| `impl` → `domain_rules` (engine) | Checks the feature's worktree still matches every name they rely on; never blocks, reports to the reviewer |
| `repo-review` | A mismatch the branch caused, or a broken invariant, is a blocking finding |

## Where they live

One id ties the places together, so a search finds all of them.

| Place | What goes there |
|-------|-----------------|
| `docs/<domain>.md` `## Invariants` (Part B) | `<PREFIX>-INV-NNN` rows: the invariant (with the rule it enforces and how it stays consistent), the anchor that enforces it, the test that proves it |
| `docs/<domain>.md` `## Change scenarios` (Part C) | `<PREFIX>-CS-NNN` rows: if you change this, what must change with it, where (anchors and the tests that verify it) |
| `docs/architecture.md` `## Platform-wide invariants` | `ARCH-INV-NNN` rows every repository keeps |
| `docs/impact/side-effects.yaml` | The same change scenarios, machine-readable |
| Code and tests | `// PL-INV-001: why` where the rule is enforced; the id in the name or comment of the test that proves it |

`<PREFIX>` is the domain's `id_prefix` (2–6 capitals, e.g. `PL` for payment links); numbers are
three digits and never reused. `python3 .maestro/engine/living_docs.py next PL` prints the next
free ones. To retire a rule, keep its row and start its second cell with `Retired YYYY-MM-DD:`.
An invariant needs test evidence; without a test that proves it, it stays a proposal.
An effect on another domain that is not a rule to protect but simply happens (an event another
domain consumes, a row it writes) is an Outbound side effect (`<PREFIX>-SE-NNN`, written by the
docs writer), not a change scenario.

```markdown
## Invariants
| ID | Invariant | Enforced by | Test evidence |
| --- | --- | --- | --- |
| PL-INV-001 | An invoice has at most one active payment link. Enforces PL-BR-001. Consistency: transactional, partial unique index. | backend · internal/links/link.go · Service.ForInvoice | backend · internal/links/link_test.go · TestForInvoiceReusesActiveLink |

## Change scenarios
| ID | If you change | Also change | Where |
| --- | --- | --- | --- |
| PL-CS-001 | Disabling a payment link: backend · internal/links/disable.go · Service.Disable | Reminders stop (PL-INV-004); a late payment is still accepted | verify with backend · internal/links/disable_test.go · TestDisablePublishesEvent; source: Incident INC-2025-07 |
```

Write an invariant only for something that must hold. A description of today's behaviour is a
business rule (`PL-BR-NNN` under the same doc's `## Business rules`), not an invariant.

## Proposals

Models never write the sections above. What build-knowledge or retrospect finds goes under
`## Proposed rules and scenarios` in the same doc, without an ID:

```markdown
## Proposed rules and scenarios
| Kind | Proposal | Where | Evidence |
| --- | --- | --- | --- |
| invariant | A payment link's expiry date never moves earlier once sent. | backend · internal/links/sweep.go · ExpirySweep.Run | The sweep only expires links past their date. |
```

To accept one, a person moves it into the right section with the next free ID, and deletes the
proposal row. To reject one, delete the row.

## `docs/impact/side-effects.yaml`

`living_docs.py scaffold` writes an empty starter. Each scenario has a row with the same ID in its
domain doc:

```yaml
version: 1
scenarios:
  - id: PL-CS-001
    domain: payment-links           # the domain doc whose table lists it
    summary: Disabling a payment link
    rules: [PL-INV-004]             # invariants at risk; each must be defined
    repo: backend                   # default repository for the names below
    when_changing:                  # files (a path) or symbols (Class.method, function)
      - internal/links/disable.go
      - Service.Disable
    also_impacts:
      domains: [reminders]          # each needs its docs
      tables: [payment_links]
      queues: [link.disabled]
      endpoints: ["GET /v1/links/{id}"]
      files: ["web:src/screens/Links.tsx"]   # "repo:name" for another repository
      symbols: []
    verify: [TestDisablePublishesEvent]     # tests that prove it still holds
```

The file uses Maestro's YAML subset (`engine/wf.py`): block maps and lists, one-line flow lists,
quoted strings. No anchors or folded (`>`) text.

## The checks

```bash
python3 .maestro/engine/living_docs.py status --root .   # are there any?
python3 .maestro/engine/living_docs.py rules  --root .   # do they still match the code?
python3 .maestro/engine/living_docs.py check  --root .   # the whole format, these included
```

`rules` prints one JSON line and always exits 0 (`valid` says the result; `--out` writes the full
report; `--repo <name> --worktree <path>` reads that repository from a feature's worktree). No
rules at all: `present: false, skipped: true`. Otherwise it reports an error when:

- an anchor in an invariant or scenario row no longer resolves;
- a name a scenario relies on is gone: a file path, a symbol, a table, a queue, a route segment of
  an endpoint, a `verify` test;
- code or a test cites an id no doc defines (a stale reference);
- a scenario cites an undefined invariant, or an `also_impacts.domains` domain without docs;
- an id is malformed or duplicated.

An invariant cited in no code or test, and a scenario in the yaml without a row in its table (or
the reverse), are warnings.

A name "exists" when it appears as a whole word in the repository's source files (`docs/`,
markdown, `node_modules`, build output and vendored code are skipped). It does not parse code, so
a function that survives only in a comment still counts.

In a writer step (`check --locked-from <snapshot>`), any change to the team's content fails as R9
and the engine puts the snapshot text back; a problem inside the team's content is reported as a
warning for the team, since the writer may not fix it.
