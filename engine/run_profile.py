#!/usr/bin/env python3
"""Debug-mode timing profile of a run: every visit of every step, split into work and human time.

Off by default. `maestroctl init --debug` turns it on for a run (on a resumed run too, from that
point on); the ledger then keeps one record per finished visit under `profile.visits`, and every
serving call rewrites `profile.json` and `profile.md` in the feature folder. Without debug the
ledger keeps only each step's last visit, as before.

A visit runs from the moment the step is entered to the moment it finishes. When the engine
handed it out (`next`), the part before that is `queued` (the lead had not picked it up yet:
busy with other work, or no session running); the rest is `active`. Active time is
  work    worker and lead agents, scripts
  human   gates and interviews a person answered (autopilot answers count as work)
Stages (subworkflow and parallel nodes) are recorded for their wall time and never summed.
`idle` is run wall time when no visit was active — the time nothing ran and nobody was asked.
The engine is not called while a lead or worker step is running, so a session that was paused or
closed mid-step (a laptop asleep overnight) still counts as that step's work. A work visit of an
hour or more is therefore listed under `long_visits` as suspect, not trusted as real work time.

  run_profile.py --slug S [--root .] [--json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state as statemod  # noqa: E402

SERVED_KEY = "served_at_ms"
STAGE_TYPES = ("subworkflow", "parallel")
HUMAN_TYPES = ("gate", "interview")
GAP_MS = 5 * 60 * 1000  # idle stretches at least this long are listed
LONG_VISIT_MS = 60 * 60 * 1000  # a work visit this long is flagged: likely a paused session
TOP = 10


def enabled(state):
    return bool((state.get("run") or {}).get("debug"))


def stamp_served(state, paths):
    """Mark the steps an action hands out as served, once per visit (debug runs only)."""
    if not enabled(state):
        return False
    stamped = False
    for path in paths:
        entry = (state.get("steps") or {}).get(path)
        if entry is not None and SERVED_KEY not in entry:
            entry[SERVED_KEY] = statemod.now_ms()
            stamped = True
    return stamped


def record_visit(state, path, entry):
    """Append the visit `entry` just closed (call after mark_step_finished)."""
    if not enabled(state):
        return
    start, duration = entry.get("started_at_ms"), entry.get("duration_ms")
    if not isinstance(start, int) or not isinstance(duration, int):
        return
    end = start + duration
    kind = entry.get("node_type") or "agent"
    visit = {"step": path, "type": kind, "visit": entry.get("visits", 0),
             "status": entry.get("status"), "start_ms": start, "end_ms": end}
    if kind == "agent":
        visit["execution"] = entry.get("execution", "worker")
    served = entry.get(SERVED_KEY)
    if isinstance(served, int) and start <= served <= end:
        visit["served_ms"] = served
    if (entry.get("outputs") or {}).get("by") == "autopilot":
        visit["by"] = "autopilot"
    state.setdefault("profile", {}).setdefault("visits", []).append(visit)


def _category(visit):
    if visit["type"] in STAGE_TYPES:
        return "stage"
    if visit["type"] in HUMAN_TYPES and visit.get("by") != "autopilot":
        return "human"
    return "work"


def _split(visit):
    """-> (queued_ms, active_ms, active_start_ms)."""
    active_from = visit.get("served_ms", visit["start_ms"])
    return active_from - visit["start_ms"], visit["end_ms"] - active_from, active_from


def _union_ms(intervals):
    """Total length of the union of [a, b) intervals, plus the gaps between them."""
    total, gaps, cur_a, cur_b = 0, [], None, None
    for a, b in sorted(intervals):
        if cur_b is None:
            cur_a, cur_b = a, b
        elif a > cur_b:
            total += cur_b - cur_a
            gaps.append((cur_b, a))
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += cur_b - cur_a
    return total, gaps


def _blank():
    return {"visits": 0, "work_ms": 0, "human_ms": 0, "queued_ms": 0, "longest_ms": 0}


def build(state):
    """The profile report as a dict (see the module docstring for the categories)."""
    visits = list((state.get("profile") or {}).get("visits") or [])
    steps, stages, active, top, long_visits = {}, {}, [], [], []
    totals = {"work_ms": 0, "human_ms": 0, "queued_ms": 0}
    for visit in visits:
        category = _category(visit)
        queued, active_ms, active_from = _split(visit)
        if category == "stage":
            row = stages.setdefault(visit["step"], {"visits": 0, "wall_ms": 0})
            row["visits"] += 1
            row["wall_ms"] += visit["end_ms"] - visit["start_ms"]
            continue
        row = steps.setdefault(visit["step"], {**_blank(), "type": visit["type"],
                                               "execution": visit.get("execution")})
        row["visits"] += 1
        row[f"{category}_ms"] += active_ms
        row["queued_ms"] += queued
        row["longest_ms"] = max(row["longest_ms"], active_ms)
        totals[f"{category}_ms"] += active_ms
        totals["queued_ms"] += queued
        active.append((active_from, visit["end_ms"]))
        top.append({"step": visit["step"], "visit": visit["visit"], "category": category,
                    "active_ms": active_ms})
        if category == "work" and active_ms >= LONG_VISIT_MS:
            long_visits.append({"step": visit["step"], "visit": visit["visit"],
                                "active_ms": active_ms})
    starts = [v["start_ms"] for v in visits]
    ends = [v["end_ms"] for v in visits]
    wall = (max(ends) - min(starts)) if visits else 0
    covered, gaps = _union_ms(active)
    long_gaps = [{"from": _iso(a), "to": _iso(b), "ms": b - a} for a, b in gaps if b - a >= GAP_MS]
    top.sort(key=lambda t: -t["active_ms"])
    return {
        "schema_version": 1,
        "slug": state.get("slug"),
        "mode": (state.get("run") or {}).get("mode") or "human",
        "status": (state.get("run") or {}).get("status"),
        "visits_recorded": len(visits),
        "wall_ms": wall,
        **totals,
        "idle_ms": max(0, wall - covered),
        "stages": stages,
        "steps": steps,
        "top": top[:TOP],
        "gaps": long_gaps,
        "long_visits": sorted(long_visits, key=lambda t: -t["active_ms"]),
    }


def _iso(ms):
    import datetime
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _dur(ms):
    seconds = round(ms / 1000)
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def render_md(report):
    lines = [f"# Run profile — {report['slug']}", "",
             f"Mode {report['mode']}, status {report['status']}, "
             f"{report['visits_recorded']} visits recorded.", "",
             "| Total | Time |", "|---|---|",
             f"| Wall | {_dur(report['wall_ms'])} |",
             f"| Work (agents, scripts; parallel workers add up) | {_dur(report['work_ms'])} |",
             f"| Human (gates, interviews) | {_dur(report['human_ms'])} |",
             f"| Queued (ready, not yet picked up) | {_dur(report['queued_ms'])} |",
             f"| Idle (nothing running, nobody asked) | {_dur(report['idle_ms'])} |", ""]
    if report["stages"]:
        lines += ["## Stages", "", "| Stage | Visits | Wall |", "|---|---|---|"]
        for path, row in sorted(report["stages"].items(), key=lambda kv: -kv[1]["wall_ms"]):
            lines.append(f"| {path} | {row['visits']} | {_dur(row['wall_ms'])} |")
        lines.append("")
    if report["steps"]:
        lines += ["## Steps", "",
                  "| Step | Type | Visits | Work | Human | Queued | Longest visit |",
                  "|---|---|---|---|---|---|---|"]
        rows = sorted(report["steps"].items(),
                      key=lambda kv: -(kv[1]["work_ms"] + kv[1]["human_ms"]))
        for path, row in rows:
            kind = row["type"] + (f" ({row['execution']})" if row.get("execution") else "")
            lines.append(f"| {path} | {kind} | {row['visits']} | {_dur(row['work_ms'])} | "
                         f"{_dur(row['human_ms'])} | {_dur(row['queued_ms'])} | "
                         f"{_dur(row['longest_ms'])} |")
        lines.append("")
    if report["top"]:
        lines += ["## Longest visits", "", "| Step | Visit | Kind | Active |", "|---|---|---|---|"]
        for item in report["top"]:
            lines.append(f"| {item['step']} | {item['visit']} | {item['category']} | "
                         f"{_dur(item['active_ms'])} |")
        lines.append("")
    if report.get("long_visits"):
        lines += ["## Suspect long visits (1 h or more)", "",
                  "The engine cannot see a paused or closed session, so these may include time "
                  "nothing ran. Their Work above is an upper bound.", "",
                  "| Step | Visit | Counted as work |", "|---|---|---|"]
        for item in report["long_visits"]:
            lines.append(f"| {item['step']} | {item['visit']} | {_dur(item['active_ms'])} |")
        lines.append("")
    if report["gaps"]:
        lines += ["## Idle stretches (5 min or more)", "", "| From | To | Length |", "|---|---|---|"]
        for gap in report["gaps"]:
            lines.append(f"| {gap['from']} | {gap['to']} | {_dur(gap['ms'])} |")
        lines.append("")
    return "\n".join(lines)


def write_files(slug, state, root="."):
    """Rewrite profile.json and profile.md in the feature folder (debug runs only)."""
    if not enabled(state):
        return None
    folder = statemod.feature_dir(slug, root)
    if not os.path.isdir(folder):
        return None
    report = build(state)
    with open(os.path.join(folder, "profile.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    path = os.path.join(folder, "profile.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_md(report) + "\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    state = statemod.load(args.slug, args.root)
    if state is None:
        print(f"no run {args.slug!r}", file=sys.stderr)
        return 3
    if not enabled(state):
        print(f"run {args.slug!r} is not in debug mode: start or resume it with "
              f"`maestroctl init --debug` to record a profile", file=sys.stderr)
        return 3
    write_files(args.slug, state, args.root)
    report = build(state)
    print(json.dumps(report, indent=2) if args.json else render_md(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
