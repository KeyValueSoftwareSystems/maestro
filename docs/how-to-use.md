# How to use Maestro — a plain-English guide

This guide is for anyone who has to *use* Maestro rather than build it: a developer new to the
team, a product person approving a design, a lead deciding a release. No knowledge of the engine
or workflow files is needed. Find the situation you are in, check the condition, do what it says.

For the full reference, see the [README](../README.md). For writing your own workflows, see
[workflow-spec.md](workflow-spec.md).

---

## What Maestro is, in one paragraph

Maestro is a checklist that your AI coding assistant (Claude Code, Cursor or Codex) is made to
follow, step by step, for every feature. The checklist is the same for everyone on the team:
write the product requirements, design the system, design each repository, agree on the API,
review the design, build it, test it, approve the release. The AI does the writing and coding.
**You** answer its questions and approve or reject its work at fixed checkpoints. It cannot skip a
step, cannot skip your approval, and remembers exactly where it stopped if you close the window.

## Words you will see

| Word | What it means for you |
|---|---|
| **Slug** | The short name of a feature, e.g. `phone-otp-login`. Everything about the feature is filed under it. |
| **Run** | One feature going through the checklist. You start it once and resume it as often as you like. |
| **Requirement folder** | `.maestro/runs/<slug>/requirement/` — where you drop the tickets, notes or PRD that describe the feature. |
| **PRD** | Product requirements: *what* the feature must do, in plain language, with numbered acceptance criteria (`AC-01`, `AC-02`…). |
| **HLD** | High-level design: the overall architecture for the feature across all services. |
| **LLD** | Low-level design: the detailed plan for **one** repository (backend, frontend, mobile…). |
| **API contract** | The agreed shape of the calls between services, so frontend and backend build against the same thing. |
| **Gate** | A checkpoint where the run stops and asks *you* to decide — usually Approve, Request changes, or Abort. |
| **Interview** | A round of questions the AI asks before writing a document, so it does not guess. |
| **Artifact** | Any file the run produces (PRD, HLD, review, test report…). A step is not "done" until its file exists. |
| **Umbrella workspace** | One parent folder that holds Maestro plus all the service repos a feature touches, so the AI sees all of them at once. |

## Commands at a glance

You type these **inside your AI assistant's chat**, not in a terminal.

| You want to… | Claude Code / Cursor | Codex |
|---|---|---|
| Set Maestro up in a repo (once) | `/maestro-init` | `$maestro-init` |
| Start or resume a feature | `/maestro my-feature` | `$maestro my-feature` |
| Start from a description | `/maestro add phone OTP login` | `$maestro add phone OTP login` |
| See your runs and pick one | `/maestro` | `$maestro` |
| Discuss one hard question separately | `/maestro-discuss …` (Maestro gives you the exact line) | `$maestro-discuss …` |

Two things are run in a **terminal**, and only when you want to look, never to drive a run:

```bash
python3 .maestro/engine/maestroctl.py todo --slug my-feature
```

```bash
./maestro ui
```

The first prints the feature's checklist; the second opens the visual board in your browser.

---

## Scenarios

Each scenario lists **when it applies** (the condition), **what to do**, and **what you will see**.

### 1. Setting up Maestro for the first time

**When:** your project has never used Maestro — there is no `.maestro/` folder at its root.

**Before you start, check:**
- `python3 --version` prints 3.8 or higher.
- `git`, `bash` and `curl` are installed. On Windows, use WSL.
- Every repository you will change is a git repo with **at least one commit**. If not, run
  `git init && git add -A && git commit -m "initial"` in it once.
- Your feature touches **more than one repo** (e.g. frontend + backend)? Set up an
  [umbrella workspace](umbrella-workspace.md) first and install into the umbrella, not into one
  of the service repos. A single-repo feature can install straight into that repo.

**Do:**
1. From the project root, install for your assistant (pick one or more of `claude-code`, `cursor`,
   `codex`):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/kv-skills/main/install.sh | bash -s -- claude-code
   ```

2. Open your assistant in that folder and run `/maestro-init` (or `$maestro-init`).
3. If it reports repositories that are behind their remote, choose whether to update them first.
4. Reload or restart your assistant so it picks up the newly installed skills.

**You will see:** the detected tech stacks, the skills installed for them, and new documentation
under `docs/` describing your codebase. You only do this once per project; re-running is safe.

### 2. Starting a new feature when you already have a PRD or ticket

**When:** someone has already written down what the feature must do (a PRD, Jira ticket,
Confluence page, meeting notes).

**Do:**
1. Run `/maestro my-feature` (pick a short, hyphenated name).
2. Maestro creates `.maestro/runs/my-feature/requirement/` and, finding it empty, stops at
   *No requirement found*. Drop your files in there — every file in that folder is read — then
   choose **I'll add files now — re-check**. (Tip: connect Jira / Confluence / Figma to your
   assistant so it can also read linked tickets and designs directly.)
3. If it asks for starting references, add links or paths, or choose **No references — continue**.
4. Confirm the short project summary and the one-line feature goal it shows you.

**You will see:** if your document is already a complete PRD, it goes almost straight to
**PRD approval**. If it is partial, the AI asks only about what is missing, then writes the PRD.

### 3. Starting a new feature from just an idea

**When:** you have no written requirement — only a sentence in your head.

**Do:** run `/maestro add phone OTP and Google sign-in` (any description). Maestro turns it into a
slug such as `phone-otp-google-sign-in` and starts. When it finds the requirement folder empty, it
offers **Clarify it with me** — choose that.

**You will see:** a short series of question pop-ups about how the feature should behave, then a
written PRD for you to approve. Expect more questions than in scenario 2; that is how it avoids
guessing.

### 4. Answering interview questions

**When:** a pop-up appears with a question and several options.

Each question gives you a **recommended** answer (with the reason), up to two **alternatives**
(with their trade-offs), **Not sure — let's discuss**, and a free-text box.

| If you… | Choose |
|---|---|
| agree with the recommendation | the recommendation |
| prefer a listed alternative | that alternative |
| have a different answer, or a side question | type it in the free-text box |
| genuinely don't know yet | **Not sure — let's discuss** |
| want to talk it through at length | type *take it to a side chat*, run the `/maestro-discuss …` line it gives you in a **new** chat, settle it there, then say *continue* in the original chat |
| still can't decide after discussing | adopt the recommendation as a **working assumption** (the document will mark it unverified) or **park it** as an open item |

The last pop-up of each round asks **Anything to add?** — use it for anything the AI missed.
For the HLD and each LLD, the round ends with a **direction** question: a short summary of the
whole intended design. Read it carefully; this is your chance to redirect *before* anything is
written.

### 5. Reviewing and approving a document

**When:** the run stops at a gate named *PRD approval*, *HLD approval*, *Repository LLD approval*
or *Contract approval*.

**Do:** open the file it points to and read it. Then pick:

| Your verdict | Choose | What happens |
|---|---|---|
| It's right | **Approve** | The run moves to the next stage. |
| Small fixes needed | **Request changes** | It then asks you *what* to change (you must type something). Only that document is edited, and you are asked again. |
| The thinking is wrong, not just the wording | **Correct the feature goal** (PRD) / **Re-clarify** (HLD, LLD) | You go back to the questions for that document and it is rewritten. |
| The whole feature should stop | **Reject / Abort** | The run ends. Your files stay on disk. |
| You have a question about the document | type it instead of choosing | It answers from that document only and shows the gate again. |

### 6. Each team designing its own repository (LLD)

**When:** the HLD is approved and the feature touches several repos.

Maestro splits the detailed design into one **separate run per repository**, named
`<feature>--lld--<repo>` (e.g. `my-feature--lld--backend`). Each team owns only its own.

**If you are a repo team member:** run `/maestro my-feature`. A selector lists every repository's
status — pick yours. Answer its questions, then approve your LLD. Commit and push the
`.maestro/runs/my-feature--lld--<repo>/` folder along with your approval.

**If you are the feature coordinator:** pull everyone's changes, run `/maestro my-feature`, choose
the coordinator option and **Refresh repository approval status**. The feature moves on to the API
contract only when **every** selected repo is approved. You can also **Change selected
repositories** here.

### 7. The architecture review finds a blocking problem

**When:** the gate *Blocking architecture findings* appears after the design is complete.

| If the fix… | Choose |
|---|---|
| only affects the detailed design of some repos | **Approve correction — update affected LLDs only**. Only those repos' LLDs are reopened; the PRD and HLD stay approved. |
| belongs in an earlier document (PRD or HLD) | **Revise the identified source layer**, then describe the change. |
| is a risk you knowingly accept | **Waive — proceed anyway**. |
| means the feature should not continue | **Abort the run**. |

### 8. Building only part of the feature now

**When:** the contract is approved and you reach *Implementation scope*, but you only want to
build some repositories now (e.g. backend this sprint, frontend next).

**Do:** choose **Pick repositories for this batch** and name the ones to build now, instead of
**Implement all available repositories**. The others are
kept as deferred work. After that batch is approved, a *Deferred implementation repositories*
gate offers **Implement another deferred batch now**, **Finish this feature with those
repositories deferred**, or **Abort**. Coming back later with `/maestro my-feature` resumes
here — the design is not redone, but Maestro still checks whether the code changed underneath it.

### 9. Approving the release

**When:** the gate *Release approval* appears, after building, code review and QA.

**Do:** read the review pack it points to — what changed, why, test proof, and any issues found.

| If… | Choose |
|---|---|
| you are happy to ship this batch | **Approve this implementation batch** |
| the build exposed a design problem | **Send back to design**, then describe it |
| it should not ship | **Reject — abort** |

After approval, Maestro finalises the design documents, saves lessons for future features, and
updates the docs. **It does not merge your branches** — merging stays a human job, done after
archival.

### 10. You closed the window, or the AI stopped mid-way

**When:** you come back to an unfinished feature, or the assistant ended its turn before the run
finished.

**Do:** run `/maestro my-feature` again (or just `/maestro` and pick it from the list). It resumes
from the exact step; nothing finished is redone. This works on another machine too, as long as
the `.maestro/runs/my-feature/` folder was committed and pulled.

- **Claude Code:** you can make it continue automatically between your approvals by enabling the
  optional stop hook described in the README under *Pausing & resuming a run*.
- **Cursor:** it never continues by itself — re-run the command. Running one phase at a time
  (`/maestro my-feature .maestro/workflows/design.yaml`) keeps sessions short and stops less often.
- **Codex:** re-run `$maestro my-feature`.

### 11. Someone else's code changed since the design was approved

**When:** Maestro reports *Workspace updates available* at the start of a feature or before
building.

| If… | Choose |
|---|---|
| you want the latest code (the normal case) | **Apply safe updates**. Only clean repos are fast-forwarded; repos with local changes are left untouched and listed. |
| you must keep working on exactly what you have | **Continue without updating** |
| something looks wrong | **Abort the run** |

If code moved *after* the design was approved, Maestro regenerates the affected design and asks
you to approve it again before any building starts.

### 12. Checking where a feature stands

**When:** you want to know progress without touching anything.

- In the chat: your assistant's task list mirrors the checklist —
  e.g. `Design phase › HLD — waiting on you: HLD approval`.
- In a terminal: `python3 .maestro/engine/maestroctl.py todo --slug my-feature` prints the same
  checklist; `… status --slug my-feature` shows every step in detail.
- Visually: `./maestro ui`, then open **Runs** and pick the feature. Green is done, orange is
  running, red failed, grey not started.

None of these change the run.

### 13. Using one step without the whole pipeline

**When:** you only need one piece — say, a review of your current changes or a run of the tests —
not a full feature.

**Do:** call the step directly, e.g. `/verify` (run the project's checks), `/backend-review`,
`/frontend-review`, `/architecture-review`, `/fix-loop` (one attempt to fix failing checks),
`/human-review-pack`, `/build-knowledge`. In Codex, use `$` instead of `/`. Nothing is tracked
as a run; it just does that one job.

### 14. Something went wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| *"workflow changed"* / hash mismatch | Someone edited a workflow file during your run. | If the edit is intended, run `python3 .maestro/engine/maestroctl.py rebase --slug my-feature`. Otherwise undo the edit. |
| A step refuses to complete | The step did not produce its required file. | Let the assistant retry the step; if it keeps failing, it can mark it failed and you decide at the next gate. |
| Merge conflict in `state.yaml` | Two people pushed the same run. | **Never** hand-edit it. Keep one side, then check `status --slug my-feature` and continue. |
| You need to redo from an earlier step | A decision turned out wrong. | `python3 .maestro/engine/maestroctl.py reset --slug my-feature --step <id> --cascade` (get the step id from `status`). |
| `/maestro` offers to "upgrade" an old run | The run was started on an older Maestro version. | Accept. It backs everything up and asks you to re-approve the imported documents; old approvals are not carried over silently. |
| Building fails on a repo | The repo has no commits, so it cannot get its own working copy. | Make one initial commit in that repo, then resume. |

---

## Golden rules

1. **Talk to Maestro through your assistant**, not by editing its files. Never hand-edit anything
   under `.maestro/runs/<slug>/` except dropping files into `requirement/`.
2. **Read before you approve.** Every gate is a real decision; approving moves the work on.
3. **Say what you want changed.** "Request changes" always needs text — vague feedback gets vague
   fixes.
4. **One person per feature run at a time.** Repo LLD runs are split so each team can work in
   parallel without collisions.
5. **Commit the `.maestro/runs/` folder** so others (and other machines) can resume.
6. **Merging is yours.** Maestro prepares and approves; a human merges.
