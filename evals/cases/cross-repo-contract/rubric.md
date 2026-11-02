# Rubric — cross-repo-contract

Score each criterion 1–5.

- **contract_first** — the contract defines the new `status` field (type, allowed values, that it
  is additive) before either LLD; both LLDs and both implementations follow it exactly.
- **compatibility** — existing fields and callers are untouched; the change is additive.
- **architecture_judgement** — ownership is clear (the API derives status; the client only shows
  it); no new services, queues or caches for a derived field.
- **code_quality** — status derivation covers all flag combinations (including shipped but
  unpaid, if it can occur, with a stated decision); both repositories have tests per criterion.
- **evidence** — the decision log, assumptions and drift check are honest and complete.
