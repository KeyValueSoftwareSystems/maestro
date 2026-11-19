# Evaluating Maestro

The engine suite proves the flow runs. These two layers measure whether the output is good.

## Skill behaviour tests — after every skill edit

`evals/skills/<skill>/*.yaml` holds scripted cases: a self-contained prompt, the patterns the
reply must contain and the ones it must never contain (for example, no infrastructure questions
in a workspace without infrastructure, no invented response-time targets, a weakened test
assertion always blocks review).

```bash
python3 engine/skill_tests.py list                 # the cases and their prompts
# run each in a fresh subagent told to load and follow its skill; save the reply as out/<id>.txt
python3 engine/skill_tests.py check --outputs out  # exit 0 only when every case passes
```

Checking needs no model, so it is cheap to run on every change.

## Evaluation set — before every release

`evals/cases/<case>/` is one end-to-end feature: `case.yaml` (the requirement, the repositories
and their commands, the run mode, and what a good run achieves), `workspace/` (fixture
repositories) and `rubric.md` (what a judge grades). The set covers a small single-repository
change (a minor plan), two repositories changing in step under an unchanged interface (a minor
plan with a ship order), a cross-repository field (a major plan whose Interfaces section
both repositories follow) and a background job with Terraform (a major plan with an
Infrastructure section).

```bash
python3 engine/eval_setup.py --case evals/cases/infra-queue --dest /tmp/eval-infra
# install Maestro into /tmp/eval-infra and run the printed /maestro command (auto mode); auto
# mode still leaves the brainstorm, the plan approval and the archive confirmation to you
python3 engine/eval_score.py score --root /tmp/eval-infra --case evals/cases/infra-queue \
    --judge judge.json --out reports/infra-queue.json
python3 engine/eval_score.py summary --reports reports/*.json --baseline evals/baseline.json
```

`score` is deterministic: run status, change type (major or minor), questions asked and
rounds per stage, acceptance criteria, whether the PRD and the plan pass their validators, engine
verification per repository, the acceptance-criteria trace, design drift, fix rounds, gates a
person answered, wall time — each checked against the case's `expect:`. `check_rounds` (hand-offs
a job made before its engine check passed) is reported alongside, not checked. The judge is a fresh
subagent that reads the run's documents, code and `rubric.md` and writes
`{"scores": {"<criterion>": 1-5}, "notes": "..."}`; its average must reach `expect.judge_min`.

`summary` flags regressions against `evals/baseline.json`: a case that passed and now fails,
questions up by more than a quarter, more fix rounds, or a judge average down by more than half a
point. After a release you accept, save the summary's `cases` object as the new baseline.
