"""Seeds tau2's own orchestrator with a Phase-1 blueprint and reads
pass/fail off tau2's own evaluator. No rollout loop or grading logic is
reimplemented here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from tau2.agent.llm_agent import LLMAgent
from tau2.data_model.simulation import SimulationRun
from tau2.data_model.tasks import Task
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.runner.simulation import run_simulation

from apigen_mt.domains.base import DomainPlugin
from apigen_mt.llm_client import LLMClient
from apigen_mt.phase1.schema import ValidatedTask
from apigen_mt.phase2.blueprint_adapter import blueprint_to_task
from apigen_mt.phase2.human_sim import build_bon_human_simulator, build_human_simulator, sample_persona_config


@dataclass
class Phase2Config:
    agent_model: str
    user_model: str
    agent_llm_args: dict = field(default_factory=dict)
    user_llm_args: dict = field(default_factory=dict)
    max_steps: int = 100
    max_errors: int = 10
    randomize_persona: bool = True
    use_bon: bool = False
    bon_n: int = 4
    bon_judge: Optional[LLMClient] = None


@dataclass
class TrajectoryResult:
    task: Task
    simulation: SimulationRun
    success: bool
    attempt_number: int

    @property
    def state_based_pass(self) -> bool:
        db_check = self.simulation.reward_info.db_check if self.simulation.reward_info else None
        return db_check.db_match if db_check is not None else False

    @property
    def output_based_pass(self) -> bool:
        info = self.simulation.reward_info
        if info is None or info.communicate_checks is None:
            return True  # no communicate_info to check
        return all(c.met for c in info.communicate_checks)


def build_task(validated: ValidatedTask, plugin: DomainPlugin, task_id: Optional[str] = None) -> Task:
    return blueprint_to_task(validated, plugin, task_id=task_id)


def run_phase2_trial(
    validated: ValidatedTask,
    plugin: DomainPlugin,
    config: Phase2Config,
    rng: random.Random,
    attempt_number: int = 1,
    task: Optional[Task] = None,
) -> TrajectoryResult:
    """Run one Phase 2 attempt: build the native task, wire a fresh
    environment/agent/human-simulator, drive tau2's Orchestrator, and grade
    with tau2's evaluator.
    """
    task = task or build_task(validated, plugin)
    env = plugin.env_factory()

    agent = LLMAgent(
        tools=env.get_tools(),
        domain_policy=env.get_policy(),
        llm=config.agent_model,
        llm_args=config.agent_llm_args,
    )

    persona_config = sample_persona_config(rng) if config.randomize_persona else None
    if config.use_bon:
        if config.bon_judge is None:
            raise ValueError("Phase2Config.use_bon=True requires bon_judge to be set")
        user = build_bon_human_simulator(
            task,
            llm=config.user_model,
            judge=config.bon_judge,
            n=config.bon_n,
            llm_args=config.user_llm_args,
            persona_config=persona_config,
        )
    else:
        user = build_human_simulator(
            task, llm=config.user_model, llm_args=config.user_llm_args, persona_config=persona_config
        )

    orchestrator = Orchestrator(
        domain=plugin.name,
        agent=agent,
        user=user,
        environment=env,
        task=task,
        max_steps=config.max_steps,
        max_errors=config.max_errors,
        seed=rng.randint(0, 2**31 - 1),
    )

    simulation = run_simulation(orchestrator, evaluation_type=EvaluationType.ALL)
    success = simulation.reward_info is not None and simulation.reward_info.reward >= 1.0
    return TrajectoryResult(task=task, simulation=simulation, success=success, attempt_number=attempt_number)
