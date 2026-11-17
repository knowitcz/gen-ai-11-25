---
name: 'bug-hunt-benchmark'
description: 'Measure the bug-hunt pipeline against seeded bugs — applies known defects in a throwaway worktree, runs /bug-hunt on it, and scores recall'
agent: 'agent'
tools: ['agent', 'read', 'search', 'edit', 'execute']
argument-hint: '[runs=3]'
---

# Bug Hunt Benchmark – Seeded-Bug Scoring

Arguments: the text the user typed after `/bug-hunt-benchmark` — the number of runs (default **3**).

You measure how many deliberately planted bugs the pipeline finds and confirms. The answer key is `benchmarks/bug-hunt/seeds.json` and `benchmarks/bug-hunt/seeds/`.

**Do not open the answer key, and do not run `bench.py candidates`, before step 3.** You consolidate the hunt's findings in step 2; knowing the seeds would bias that. Never mention seeds, the benchmark, or the answer key in any prompt to `BugFinder`, `Opponent`, or `Judge` — they must see an ordinary bug hunt.

## Steps

1. **Seed.** Run `python3 benchmarks/bug-hunt/bench.py setup`. It creates a worktree at `.tmp/worktrees/bug-bench` with all seeds applied and prints the `scope` to scan.
2. **Hunt.** Follow the [bug-hunt prompt](./bug-hunt.prompt.md) with arguments `{runs} {scope}` to the end, including writing `results.json` and `report.md`.
3. **Match.** Run `python3 benchmarks/bug-hunt/bench.py candidates {results.json}`. For each seed, decide which reported defects describe **that same incorrect behavior** — the same location alone is not a match, and a different bug in the same function is not a match. Write `matches.json` next to `results.json`:

   ```json
   {"S1": ["BUG-3"], "S2": [], "S3": ["BUG-1", "BUG-7"]}
   ```

   Every seed id must be present. A defect may match at most one seed. If a match is doubtful, leave it out and list it as doubtful in your final message.
4. **Score.** Run `python3 benchmarks/bug-hunt/bench.py score {results.json} {matches.json}`. It writes `score.md` and `score.json` next to `results.json`.
5. **Clean up.** Run `python3 benchmarks/bug-hunt/bench.py teardown` — also if an earlier step failed.

## Output

Show the user the contents of `score.md`, the output directory, and any doubtful matches. Do not interpret unmatched confirmed defects as false positives: the code may contain real bugs that were not seeded.
