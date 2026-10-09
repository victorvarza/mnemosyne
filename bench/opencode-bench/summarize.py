"""Summarize opencode-bench A/B results written by run-ab.sh.

Usage: python3 bench/opencode-bench/summarize.py [results-dir] [--json out.json]

Reads <results>/<task>/<arm>/run<N>/bench.log (opencode-bench CLI output) and
plugin.log (Mnemosyne log lines), and prints a markdown table: final score
mean ± sd per task and arm, the difference from the "off" arm, per-criterion
averages (mean of the three judges), and whether the plugin injected memories.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

FINAL_RE = re.compile(r"Final score:\s*([0-9.]+)")
CRITERION_RE = re.compile(r"Criterion:\s*(\S+)")
JUDGE_RE = re.compile(r"\s(\S+/\S+):\s*([0-9.]+)\s*$")
COST_RE = re.compile(r"Avg cost:\s*\$([0-9.]+)")
ARM_ORDER = ["off", "on", "on-sim"]


def parse_run(run_dir: Path) -> dict | None:
    log = run_dir / "bench.log"
    if not log.exists():
        return None
    text = log.read_text(errors="replace")
    finals = FINAL_RE.findall(text)
    if not finals:
        return {"valid": False, "reason": "no final score"}

    criteria: dict[str, list[float]] = {}
    current = None
    for line in text.splitlines():
        if m := CRITERION_RE.search(line):
            current = m.group(1)
            criteria.setdefault(current, [])
        elif current and (m := JUDGE_RE.search(line)):
            criteria[current].append(float(m.group(2)))

    plugin_log = run_dir / "plugin.log"
    plugin = plugin_log.read_text() if plugin_log.exists() else ""
    arm = run_dir.parent.name
    initialized = "Mnemosyne plugin initialized" in plugin
    valid = not initialized if arm == "off" else initialized
    cost = COST_RE.findall(text)
    return {
        "valid": valid,
        "reason": "" if valid else f"plugin initialized={initialized} in arm {arm}",
        "final": float(finals[-1]),
        "criteria": {k: statistics.mean(v) for k, v in criteria.items() if v},
        "injections": len(re.findall(r"Injected [0-9]+ memories", plugin)),
        "cost": float(cost[-1]) if cost else None,
    }


def mean_sd(values: list[float]) -> str:
    if not values:
        return "—"
    if len(values) == 1:
        return f"{values[0]:.3f}"
    return f"{statistics.mean(values):.3f} ± {statistics.stdev(values):.3f}"


def main() -> None:
    args = sys.argv[1:]
    out_json = None
    if "--json" in args:
        i = args.index("--json")
        out_json = Path(args[i + 1])
        del args[i : i + 2]
    root = Path(args[0]) if args else Path(__file__).parent / "results"

    data: dict[str, dict[str, list[dict]]] = {}
    for run_dir in sorted(root.glob("*/*/run*")):
        task, arm = run_dir.parent.parent.name, run_dir.parent.name
        run = parse_run(run_dir)
        if run is not None:
            data.setdefault(task, {}).setdefault(arm, []).append(run)
    if not data:
        sys.exit(f"no runs found under {root}")

    arm_names = [a for a in ARM_ORDER if any(a in arms for arms in data.values())]
    print("| Task | Arm | Final score | Δ vs off | Valid runs | Runs with injection |")
    print("|---|---|---|---|---|---|")
    for task, arms in data.items():
        off = [r["final"] for r in arms.get("off", []) if r["valid"]]
        for arm in arm_names:
            runs = arms.get(arm, [])
            scores = [r["final"] for r in runs if r["valid"]]
            delta = (
                f"{statistics.mean(scores) - statistics.mean(off):+.3f}"
                if arm != "off" and scores and off
                else "—"
            )
            injected = "—" if arm == "off" else f"{sum(1 for r in runs if r.get('injections'))}/{len(runs)}"
            print(f"| {task} | {arm} | {mean_sd(scores)} | {delta} | {len(scores)}/{len(runs)} | {injected} |")

    print("\nPer-criterion averages (mean of the three judges, valid runs):\n")
    print("| Task | Criterion | " + " | ".join(arm_names) + " |")
    print("|---|---|" + "---|" * len(arm_names))
    for task, arms in data.items():
        names = sorted({c for runs in arms.values() for r in runs if r["valid"] for c in r["criteria"]})
        for name in names:
            cells = []
            for a in arm_names:
                vals = [r["criteria"][name] for r in arms.get(a, []) if r["valid"] and name in r["criteria"]]
                cells.append(mean_sd(vals))
            print(f"| {task} | {name} | " + " | ".join(cells) + " |")

    invalid = [
        f"{t}/{a}: {r['reason']}" for t, arms in data.items() for a, runs in arms.items() for r in runs if not r["valid"]
    ]
    if invalid:
        print("\nInvalid runs (excluded):")
        for line in invalid:
            print(f"- {line}")

    if out_json:
        out_json.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
