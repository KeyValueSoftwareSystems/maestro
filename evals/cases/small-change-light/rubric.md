# Rubric — small-change-light

Score each criterion 1–5 (5 = what a strong senior engineer would produce).

- **requirement_fidelity** — the PRD states exactly the three behaviours (trim, collapse inner
  spaces, "Untitled" for empty) and nothing more; no invented targets.
- **proportion** — the design is as small as the change: one LLD, no HLD, no contract, no
  speculative infrastructure or abstractions.
- **code_quality** — `format_title` handles the three behaviours in idiomatic Python; tests cover
  each acceptance criterion, including the empty and all-space cases.
- **evidence** — the review pack reports the engine's verification and the acceptance-criteria
  trace honestly; assumptions (if any) are listed first.
