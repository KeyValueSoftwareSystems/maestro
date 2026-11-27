---
name: grill-the-idea
description: Brainstorming by interview. Questions the person until the goal, scope, edge cases, constraints and acceptance criteria are settled, recommending an answer each time, then summarises the decisions. Use when asked to be interviewed or grilled about an idea, or when a request's goal, scope or acceptance criteria are unclear before planning.
---

# Grill the idea

Interview the person to remove ambiguity before anything is designed.

## How
1. Read what you already have: the request, the related code and any docs. Note what the code
   already answers, so you don't ask it. Then play the request back in two or three lines, with
   what the code says about it, and invite the person to correct it, add context and raise their
   doubts. Discuss until they are done.
2. List the open points:
   - the goal, who it is for, and why now
   - scope, non-goals, and what would make it a failure even if it works
   - one real use case, walked step by step, including bad input, no permission, a dependency
     down and nothing to show. Each step whose behaviour nobody has stated is an open point.
   - what happens to existing data, users and clients when it ships
   - constraints, each with a number: load, latency, data size, supported versions, deadline
   - choices with real trade-offs
   - acceptance criteria, as examples with real values (given, when, then)
3. Ask one question at a time, most important first, and say in one line what the answer would
   change.
   - Ask about the goal and the why as open questions without options, because options steer.
   - For a choice, give 2–4 options with your recommendation first.
   - When a point is about how something looks or flows, show a short text sketch and ask the
     person to react.
4. Follow up when an answer opens a new question. Push back on vague answers ("fast", "the
   usual") until you have an example or a number. Drop points an answer has already settled.
5. Ask only when the answer would change what gets built and neither the request nor the code
   answers it. Otherwise state your call and its reason as a proposal the person can correct.
   Stop when every point has an answer or an explicit "you decide". If the points keep
   multiplying, the request is several pieces of work: propose a split and agree which comes
   first.
6. Summarise under Decisions (decision, choice, why, decided by), Assumptions, Out of scope and
   Acceptance criteria. Then confirm the summary with the person.

## Rules
- Never ask what the code or docs can answer.
- One question per message. The exception: independent points that each have an obvious answer
  may go together in one numbered list, worded so "yes" accepts your recommendation.
- Challenge the request when it looks wrong, and say plainly why.
- A point you settle yourself goes in the summary as your call, with its reason. Never present
  it as something the person agreed to.
- If you can't reach a person, answer each point yourself with the smallest safe option and list
  those answers as Assumptions.
