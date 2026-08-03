# Conjunctive-Goal Tasks — Telecom

Tasks flagged by [`scan_conjunctive_goals.py`](../benchmark_analysis_scripts/scan_conjunctive_goals.py) as stating multiple subgoals in `reason_for_call`. See [benchmark_subgoal_task_scanning.md](benchmark_subgoal_task_scanning.md) for the method, and [subgoal_analysis.md](subgoal_analysis.md) for the definition of subgoal used.

**0 / 2285 tasks flagged (0.0%).**

No tasks flagged. All telecom `reason_for_call` scenarios reduce to 3 distinct templates (fix no-service / fix MMS / fix mobile data), each stating exactly one user-facing goal — see the caveat section of `subgoal_analysis.md` for why telecom's long multi-tool repair chains are diagnostic depth, not compound goals.
