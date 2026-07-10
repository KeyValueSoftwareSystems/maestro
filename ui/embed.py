#!/usr/bin/env python3
"""Refresh ui/builder.html's embedded data blocks from their sources of truth.

Run after editing engine/schemas/workflow.schema.json or any workflows/*.yaml:

    python3 ui/embed.py

Replaces the contents of:
  <script type="application/json" id="workflow-schema">  <- engine/schemas/workflow.schema.json (verbatim)
  <script type="application/json" id="lint-rules">       <- engine/validate.py RULE_IDS
  <script type="application/json" id="wf-templates">     <- workflows/*.yaml (gallery templates)

testdata/test_ui_schema_sync.py fails if these are stale.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "ui", "builder.html")

TEMPLATE_META = {
    "sdlc-main": {"label": "Full SDLC pipeline", "desc": "Requirement to release: design, review gates, parallel per-stack implementation, QA, release pack.", "tags": ["design", "implement", "qa", "release"]},
    "design": {"label": "Design only", "desc": "HLD with an open-questions loop, approval gate, parallel LLDs, API contract, test cases.", "tags": ["hld", "lld", "contract"]},
    "impl": {"label": "Implement + review", "desc": "One stack: task DAG, sliced implementation, code review with a bounded fix loop.", "tags": ["tasks", "code", "fix-loop"]},
    "qa": {"label": "QA", "desc": "Automate and run the functional suite with a fix loop and escalation gate.", "tags": ["e2e", "fix-loop"]},
}


def replace_block(html, block_id, payload):
    pattern = re.compile(
        rf'(<script type="application/json" id="{block_id}">).*?(</script>)', re.S
    )
    if not pattern.search(html):
        sys.exit(f"embed.py: block #{block_id} not found in builder.html")
    # </ inside JSON strings would close the script tag early — escape defensively
    safe = payload.replace("</", "<\\/")
    return pattern.sub(lambda m: m.group(1) + safe + m.group(2), html, count=1)


def main():
    with open(HTML, encoding="utf-8") as fh:
        html = fh.read()

    with open(os.path.join(ROOT, "engine", "schemas", "workflow.schema.json"), encoding="utf-8") as fh:
        schema = fh.read().strip()
    html = replace_block(html, "workflow-schema", schema)

    sys.path.insert(0, os.path.join(ROOT, "engine"))
    import validate  # noqa: E402

    html = replace_block(html, "lint-rules", json.dumps(validate.RULE_IDS))

    templates = {}
    for key, meta in TEMPLATE_META.items():
        path = os.path.join(ROOT, "workflows", f"{key}.yaml")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            templates[key] = dict(meta, yaml=fh.read())
    html = replace_block(html, "wf-templates", json.dumps(templates))

    with open(HTML, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"embedded: schema ({len(schema)}B), {len(validate.RULE_IDS)} lint rules, "
          f"{len(templates)} templates -> {os.path.relpath(HTML, ROOT)}")


if __name__ == "__main__":
    main()
