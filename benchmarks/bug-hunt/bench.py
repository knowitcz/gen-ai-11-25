#!/usr/bin/env python3
"""Seeded-bug benchmark helper for the /bug-hunt pipeline.

  bench.py setup                      create a worktree with all seeds applied, print the scope to scan
  bench.py teardown                   remove that worktree
  bench.py candidates RESULTS         per seed, list reported defects in the same file (for matching)
  bench.py score RESULTS MATCHES      compute recall metrics, write score.json / score.md next to RESULTS
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORKTREE = REPO / ".tmp" / "worktrees" / "bug-bench"
TOLERANCE = 3  # lines of slack when comparing a reported range with a seed's range


def git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def load_seeds() -> list[dict]:
    return json.loads((HERE / "seeds.json").read_text())["seeds"]


def norm_path(path: str) -> str:
    """Strip any worktree prefix so paths compare from 'app/' onwards."""
    path = path.strip().strip("`")
    i = path.find("app/")
    return path[i:] if i >= 0 else path


def line_range(text) -> tuple[int, int] | None:
    nums = [int(n) for n in "".join(c if c.isdigit() else " " for c in str(text)).split()]
    return (min(nums), max(nums)) if nums else None


def overlaps(a, b) -> bool:
    ra, rb = line_range(a), line_range(b)
    if not ra or not rb:
        return False
    return ra[0] - TOLERANCE <= rb[1] and rb[0] - TOLERANCE <= ra[1]


def teardown() -> None:
    if WORKTREE.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(WORKTREE)], cwd=REPO, capture_output=True)
        shutil.rmtree(WORKTREE, ignore_errors=True)
    git("worktree", "prune")


def setup() -> None:
    teardown()
    WORKTREE.parent.mkdir(parents=True, exist_ok=True)
    git("worktree", "add", "--detach", str(WORKTREE), "HEAD")
    for seed in load_seeds():
        git("apply", str(HERE / "seeds" / seed["patch"]), cwd=WORKTREE)
    # The answer key must not be readable from inside the tree being scanned.
    shutil.rmtree(WORKTREE / "benchmarks", ignore_errors=True)
    print(json.dumps({"scope": str((WORKTREE / "app").relative_to(REPO)), "seeds_applied": len(load_seeds())}))


def candidates(results_path: str) -> None:
    results = json.loads(Path(results_path).read_text())
    out = []
    for seed in load_seeds():
        same_file = [b for b in results["bugs"] if norm_path(b["file"]) == seed["file"]]
        out.append({
            "seed": seed["id"],
            "file": seed["file"],
            "lines": seed["lines"],
            "defect": seed["defect"],
            "candidates": [
                {"id": b["id"], "title": b["title"], "lines": b["lines"], "claim": b.get("claim", ""),
                 "lines_overlap": overlaps(b["lines"], seed["lines"])}
                for b in same_file
            ],
        })
    print(json.dumps(out, indent=2))


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def score(results_path: str, matches_path: str) -> None:
    results = json.loads(Path(results_path).read_text())
    matches = json.loads(Path(matches_path).read_text())
    seeds = load_seeds()
    n_runs = int(results["runs"])
    runs = list(range(1, n_runs + 1))
    bugs = {b["id"]: b for b in results["bugs"]}

    unknown = sorted({g for ids in matches.values() for g in ids} - set(bugs))
    if unknown:
        sys.exit(f"matches reference unknown defect ids: {unknown}")

    per_seed = []
    for seed in seeds:
        occ = [o for gid in matches.get(seed["id"], []) for o in bugs[gid]["occurrences"]]
        by_run = {}
        for k in runs:
            mine = [o for o in occ if int(o["run"]) == k]
            if not mine:
                by_run[k] = "missed"
            elif any(o["ruling"] == "confirmed" for o in mine):
                by_run[k] = "confirmed"
            else:
                by_run[k] = "lost"  # found by bugfinder, then rejected / inconclusive
        per_seed.append({
            **{f: seed[f] for f in ("id", "file", "lines", "difficulty", "category")},
            "matched": matches.get(seed["id"], []),
            "by_run": by_run,
            "found_runs": sum(v != "missed" for v in by_run.values()),
            "confirmed_runs": sum(v == "confirmed" for v in by_run.values()),
            "contested": sum(o["rebuttal"] == "contested" for o in occ),
            "occurrences": len(occ),
        })

    total = len(seeds)
    per_run = [{
        "run": k,
        "found": sum(s["by_run"][k] != "missed" for s in per_seed),
        "confirmed": sum(s["by_run"][k] == "confirmed" for s in per_seed),
    } for k in runs]
    # How many distinct seeds were confirmed by the first k runs taken together.
    cumulative = [sum(any(s["by_run"][j] == "confirmed" for j in runs[:k]) for s in per_seed) for k in runs]

    matched_ids = {g for ids in matches.values() for g in ids}
    unmatched = [b for b in results["bugs"] if b["id"] not in matched_ids]
    unmatched_confirmed = [b for b in unmatched if any(o["ruling"] == "confirmed" for o in b["occurrences"])]

    found_occ = sum(s["occurrences"] for s in per_seed)
    summary = {
        "seeds": total,
        "runs": n_runs,
        "mean_found_per_run": sum(r["found"] for r in per_run) / n_runs,
        "mean_confirmed_per_run": sum(r["confirmed"] for r in per_run) / n_runs,
        "found_any_run": sum(s["found_runs"] > 0 for s in per_seed),
        "confirmed_any_run": sum(s["confirmed_runs"] > 0 for s in per_seed),
        "confirmed_every_run": sum(s["confirmed_runs"] == n_runs for s in per_seed),
        "seed_occurrences_found": found_occ,
        "seed_occurrences_contested": sum(s["contested"] for s in per_seed),
        "seed_occurrences_lost": sum(v == "lost" for s in per_seed for v in s["by_run"].values()),
        "cumulative_confirmed": cumulative,
        "unmatched_defects": len(unmatched),
        "unmatched_confirmed": [b["id"] for b in unmatched_confirmed],
    }
    out_dir = Path(results_path).resolve().parent
    (out_dir / "score.json").write_text(
        json.dumps({"summary": summary, "per_run": per_run, "per_seed": per_seed}, indent=2)
    )

    mark = {"confirmed": "✔", "lost": "✘", "missed": "·"}
    mean_found, mean_conf = summary["mean_found_per_run"], summary["mean_confirmed_per_run"]
    md = [
        "# Seeded-bug benchmark score", "",
        f"- **Seeds:** {total} · **Runs:** {n_runs}",
        f"- **Recall per run, found by bugfinder (mean):** {mean_found:.1f}/{total} ({100 * mean_found / total:.0f}%)",
        f"- **Recall per run, confirmed by judge (mean):** {mean_conf:.1f}/{total} ({100 * mean_conf / total:.0f}%)",
        f"- **Confirmed in at least one run:** {pct(summary['confirmed_any_run'], total)}",
        f"- **Confirmed in every run:** {pct(summary['confirmed_every_run'], total)}",
        f"- **Never found:** {pct(total - summary['found_any_run'], total)}",
        f"- **Seeded bugs contested by opponent:** {pct(summary['seed_occurrences_contested'], found_occ)} of found occurrences",
        f"- **Seeded bugs found but not confirmed:** {pct(summary['seed_occurrences_lost'], found_occ)} of found occurrences",
        f"- **Cumulative distinct seeds confirmed after run 1..{n_runs}:** {' → '.join(map(str, cumulative))}",
        f"- **Reported defects that match no seed:** {len(unmatched)}, of which confirmed: {len(unmatched_confirmed)}",
        "", "Legend: ✔ confirmed · ✘ found, then rejected or inconclusive · · not found", "",
        "| Seed | Difficulty | File | " + " | ".join(f"R{k}" for k in runs) + " | Matched |",
        "|---|---|---|" + "---|" * n_runs + "---|",
    ]
    for s in per_seed:
        md.append(f"| {s['id']} | {s['difficulty']} | `{s['file']}:{s['lines']}` | "
                  + " | ".join(mark[s["by_run"][k]] for k in runs) + f" | {', '.join(s['matched']) or '—'} |")
    md += ["", "| Run | Found | Confirmed |", "|---|---|---|"]
    md += [f"| {r['run']} | {r['found']}/{total} | {r['confirmed']}/{total} |" for r in per_run]
    md += ["", "| Difficulty | Confirmed in ≥1 run | Confirmed run-slots |", "|---|---|---|"]
    for d in ("easy", "medium", "hard"):
        group = [s for s in per_seed if s["difficulty"] == d]
        if group:
            md.append(f"| {d} | {pct(sum(s['confirmed_runs'] > 0 for s in group), len(group))} | "
                      f"{pct(sum(s['confirmed_runs'] for s in group), len(group) * n_runs)} |")
    if unmatched_confirmed:
        md += ["", "## Confirmed defects that match no seed", "",
               "These are either real bugs that were already in the code or false positives; "
               "the benchmark cannot tell which.", ""]
        md += [f"- **{b['id']}** `{norm_path(b['file'])}:{b['lines']}` — {b['title']}" for b in unmatched_confirmed]
    text = "\n".join(md) + "\n"
    (out_dir / "score.md").write_text(text)
    print(text)


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "setup" and not args:
        setup()
    elif cmd == "teardown" and not args:
        teardown()
    elif cmd == "candidates" and len(args) == 1:
        candidates(args[0])
    elif cmd == "score" and len(args) == 2:
        score(args[0], args[1])
    else:
        sys.exit(__doc__)
