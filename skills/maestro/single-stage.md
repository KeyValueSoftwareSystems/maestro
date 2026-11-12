# Running one stage on an existing feature

Part of the `maestro` lead skill; its hard rules apply.

**One stage on an existing feature** — `/maestro <slug> .maestro/workflows/design-hld.yaml`
(or `design-contract.yaml`, `design-lld.yaml`) runs just that stage's own workflow with the
feature's existing documents. Before `init`, check with `ls` that the stage's inputs exist and,
if one is missing, tell the user which stage produces it and stop: `design-hld` needs
`.maestro/runs/<slug>/requirement/prd.md`; `design-contract` and `design-lld` also need `hld.md`
(`design-lld` on the light path, which has no HLD, needs only the PRD: pass `light=true`); a
contract (`openapi.yaml`) is optional. `archive.yaml` (a feature whose archive was answered
"Not now") needs `implementation-manifest.json` and `release.json`, which the full pipeline
writes when the release is approved. If `init` exits 3 with "already runs <other workflow>", the slug's
ledger belongs to another run: ask the user (native selector) to confirm "run this stage here;
the previous ledger is kept beside it as `state.yaml.replaced-<time>`", and only on a yes re-run
`init` with `--force`. Never pass `--force` unprompted. The stage ends at its own `done`; its
documents stay in the feature folder for the full pipeline to pick up later.
