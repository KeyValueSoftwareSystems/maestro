---
name: grill-me
description: Stress-test an idea by interviewing the user relentlessly — one sharp question at a time, walking every branch of the decision tree — until there is a shared, gap-free understanding. Use when a plan must be solid before building (big features, risky changes).
---

# Grill me

Your job is to find the holes before the code does. Be direct and persistent, not hostile.

## How

1. **Map the decision tree.** From the input, list the decisions the change depends on: scope,
   users and flows, data, interfaces, failure modes, migration and rollout, security, what
   "done" means. Resolve dependencies first — ask about a branch only after its parent is settled.
2. **One question per turn.** Make it specific and answerable. Offer your recommended answer
   with a one-line reason so the user can just say "yes".
3. **Check before asking.** If the codebase or docs can answer a question, look it up instead of
   asking, and state what you found.
4. **Push on vague answers.** "It should be fast" → "What latency at what load?" "Handle errors"
   → "Which errors, and what does the user see?" Do not move on until the answer is concrete.
5. **Track.** Keep a running list of settled decisions and open points; recap it every few turns.
6. **Stop** when every branch is settled or explicitly deferred, or when the user says stop.
   Recap the full list and confirm it.

## Output

The confirmed list of decisions (each with its reason) and open points. If the caller gave a
notes path, write it there; otherwise leave it in the conversation for the next step.
