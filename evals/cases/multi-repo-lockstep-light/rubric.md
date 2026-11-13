# Rubric — multi-repo-lockstep-light

Score each criterion 1–5.

- **right_sized** — the light path: no HLD, no contract, no architecture brainstorm; the impact
  assessment calls the interface change `lockstep` (same requests and responses, only the length
  rule changes) and lists no open architecture decision.
- **ship_order** — the LLDs say which repository ships first so a client already deployed keeps
  working (e.g. the client accepts either length, or the server change ships last).
- **consistency** — both repositories use 4 everywhere: issue, verify, the prompt and its message;
  no leftover 5.
- **code_quality** — tests per acceptance criterion in both repositories; wrong-length codes are
  still refused.
- **evidence** — the decision log, assumptions and drift check are honest and complete.
