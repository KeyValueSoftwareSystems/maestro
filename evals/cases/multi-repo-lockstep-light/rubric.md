# Rubric — multi-repo-lockstep-light

Score each criterion 1–5.

- **right_sized** — a minor plan of 5-10 lines; it says the interface is unchanged (same requests
  and responses, only the length rule changes) and leaves no open architecture decision.
- **ship_order** — the plan says which repository ships first so a client already deployed keeps
  working (e.g. the client accepts either length, or the server change ships last).
- **consistency** — both repositories use 4 everywhere: issue, verify, the prompt and its message;
  no leftover 5.
- **code_quality** — tests per acceptance criterion in both repositories; wrong-length codes are
  still refused.
- **evidence** — the decision log, assumptions and drift check are honest and complete.
