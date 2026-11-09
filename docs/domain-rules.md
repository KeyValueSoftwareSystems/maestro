# Domain rules and change scenarios

Optional. Knowledge the code cannot say on its own, written by the project's people: **what must
never break**, and **what a change quietly affects elsewhere**. Maestro runs exactly as before
without them; when they exist, it uses them.

| Who | Does what |
|-----|-----------|
| The team (developers, domain owners, the client) | Writes and owns the rules and scenarios under `docs/` |
| `/maestro-init` | Checks them when present; when absent, asks once whether to create the starter file, and carries on either way |
| `feature-impact` | Follows the scenarios a feature triggers into every repository they reach; lists their ids in `impact.json` (`scenarios`) |
| `impl` → `domain_rules` (engine) | Checks the feature's worktree still matches every name the docs rely on; never blocks, reports to the reviewer |
| `repo-review` | A mismatch the branch caused, or a broken rule, is a blocking finding |
| `build-knowledge`, `retrospect` | Keep the team's sections word for word; `retrospect` proposes new ones, never writes them |

## Where they live

One id ties four places together, so a search finds all of them.

| Place | What goes there |
|-------|-----------------|
| `docs/functional/<domain>.md` | `## Rules that must never break` and `## If you change… also check` |
| `docs/impact/side-effects.yaml` | The same change scenarios, machine-readable |
| Code and tests | `// INV-PL-01: why` at the line that enforces the rule; the id in the name of the test that proves it |
| `<repo>/<package>/CLAUDE.md` | Optional: that folder's rules, at most 30 lines, loaded only when an agent works there |

## Ids

`INV-<CODE>-<NN>` is a rule; `CS-<CODE>-<NN>` is a change scenario. `<CODE>` is 2–5 capital
letters, one per domain page (`PL` for payment links). Never reuse a retired number.
`python3 .maestro/engine/domain_rules.py next PL` prints the next free ones.

## The domain page

Add two sections to the page `build-knowledge` wrote (or to any `docs/functional/<domain>.md`):

```markdown
## Rules that must never break
- INV-PL-01 One active link per invoice, however many payers receive it.
- INV-PL-02 A payment after disabling is accepted and flagged, never lost.

## If you change… also check
| ID | Change | Also check |
|----|--------|-----------|
| CS-PL-01 | Disabling a link | Reminders, late webhooks, the app's "link expired" screen |
```

Write a rule only for something that must hold. A description of today's behaviour is not a rule.

## `docs/impact/side-effects.yaml`

`domain_rules.py scaffold` writes an empty starter. Each scenario:

```yaml
version: 1
scenarios:
  - id: CS-PL-01
    domain: payments                # the page whose table lists it
    summary: Disabling a payment link
    rules: [INV-PL-01, INV-PL-02]   # rules at risk; each must be defined in a page
    repo: backend                   # default repository for the names below
    when_changing:                  # files (a path) or symbols (Class.method, function)
      - internal/links/disable.go
      - links.Service.Disable
    also_impacts:
      domains: [reminders]          # each needs docs/functional/<domain>.md
      tables: [payment_links]
      queues: [payment.succeeded]
      endpoints: ["GET /v1/links/{id}"]
      files: ["web:src/screens/Links.tsx"]   # "repo:name" for another repository
      symbols: []
    verify: [TestWebhookAfterDisable]       # tests that prove it still holds
```

The file uses Maestro's YAML subset (`engine/wf.py`): block maps and lists, one-line flow lists,
quoted strings. No anchors or folded (`>`) text.

## The check

```bash
python3 .maestro/engine/domain_rules.py status --root .   # are there any?
python3 .maestro/engine/domain_rules.py check  --root .   # do they still match the code?
```

`check` prints one JSON line and always exits 0 (`valid` says the result; `--out` writes the full
report). No rules at all: `present: false, skipped: true`. Otherwise it reports an error when:

- a name a scenario relies on is gone: a file path, a symbol, a table, a queue, a route segment of
  an endpoint, a `verify` test;
- an `INV` rule is cited in no code or test (markdown does not count);
- code, a test or a local `CLAUDE.md` cites an id no doc defines (a stale reference);
- a scenario cites an undefined rule, or an `also_impacts.domains` page that does not exist;
- an id is malformed or duplicated, or one page mixes domain codes.

A scenario in the yaml without a row in its page's table (or the reverse), and a local
`CLAUDE.md` over 30 lines, are warnings.

A name "exists" when it appears as a whole word in the repository's source files (`docs/`,
`node_modules`, build output and vendored code are skipped). It does not parse code, so a function
that survives only in a comment still counts. In delivery the feature's repository is read from its
worktree (`--repo <name> --worktree <path>`), the others from their checkouts.
