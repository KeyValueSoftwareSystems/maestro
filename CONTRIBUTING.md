# Contributing to Maestro

## Checks

These run in the **source/pack repo** (the installer strips `engine/tests` from consumer repos):

```bash
python3 engine/tests/run_all.py                    # engine: parser, validator, ledger,
                                                   # resolver sims, full-SDLC e2e (no LLM)
python3 testdata/test_ui_schema_sync.py            # UI ↔ engine anti-drift (+ cross-parser)
python3 testdata/test_workflow_skill_contracts.py  # every node output ↔ its skill contract
open ui/builder.html#selftest                      # in-browser round-trip suite
```

After editing `engine/schemas/workflow.schema.json` or any `workflows/*.yaml`, run
`python3 ui/embed.py`. After editing any `workflows/*`, also run
`python3 scripts/gen_workflow_releases.py`. See `CLAUDE.md` for the full conventions.
