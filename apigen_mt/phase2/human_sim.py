"""Wraps tau2's own UserSimulator for Phase 2, constrained to be purely
conversational (dual-control off) and persona-aware.

tau2 is dual-control: user_simulator.py's UserSimulator can be given tools
and make tool calls of its own. APIGen-MT's Phase 2 human is a *constrained*
case of that -- conversational only, no environment access -- so we build
the same UserSimulator tau2's own runner uses (see runner/build.py::build_user)
but hardcode ``tools=None`` instead of wiring in the domain's user tools.

Incremental disclosure and the stop/transfer/out-of-scope sentinels are
already implemented by tau2's global simulation guidelines
(data/tau2/user_simulator/simulation_guidelines.md) and UserSimulator.is_stop
-- nothing to reimplement there. What this module adds on top: sampling a
PersonaConfig (verbosity/interrupt behavior) per attempt for extra diversity,
and the Best-of-N stabilization wrapper (see BoNUserSimulator below).
"""

from __future__ import annotations

import random
import re
from typing import Optional

from tau2.data_model.message import AssistantMessage, Message, MultiToolMessage, ToolMessage, UserMessage
from tau2.data_model.persona import PersonaConfig, Verbosity
from tau2.data_model.tasks import Task
from tau2.user.user_simulator import UserSimulator, UserState
from tau2.user.user_simulator_base import ValidUserInputMessage

from apigen_mt.llm_client import LLMClient


def sample_persona_config(rng: random.Random) -> PersonaConfig:
    verbosity = rng.choice(list(Verbosity))
    return PersonaConfig(verbosity=verbosity)


def build_human_simulator(
    task: Task,
    llm: str,
    llm_args: Optional[dict] = None,
    persona_config: Optional[PersonaConfig] = None,
) -> UserSimulator:
    """Build a conversational-only (dual-control disabled) user simulator
    for ``task``, mirroring tau2's own runner/build.py::build_user but with
    ``tools`` hardcoded to None regardless of what user tools the domain
    registers -- the simulated human never sees environment/tool schemas,
    matching the paper's "environment state is latent to the human" model.
    """
    return UserSimulator(
        llm=llm,
        instructions=str(task.user_scenario),
        tools=None,
        llm_args=llm_args or {},
        persona_config=persona_config,
    )


_SCORE_RE = re.compile(r"<score>\s*(\d+(?:\.\d+)?)\s*</score>")

BON_JUDGE_SYSTEM_PROMPT = "You are a fair judge and an expert in following details."

BON_JUDGE_PROMPT_TEMPLATE = """
A human is interacting with a customer service assistant to get help on solving their task. You are \
provided with the description of the human and the task the human wants to accomplish (wrapped with \
<description></description>), and a candidate response (wrapped with <response></response>) the human \
wants to give the assistant. Please help the human evaluate this candidate response: give an integer \
score (ranging from 0 to 10) indicating the correctness of the response, higher score means better \
quality.

1. If the response includes specific item / order / reservation / personal details, and they correctly \
match the task description, give a full score of 10. If some details are changed or wrong, give a \
correspondingly lower score.
2. The response can include any normal conversation otherwise (e.g. asking for details, saying \
###STOP###) which are all correct responses.
3. If the candidate response keeps the conversation flowing by describing the task clearly / gives \
information properly, give a high score; if not (e.g. "I don't remember" or an unhelpful response), \
give a correspondingly lower score.

<description>
{description}
</description>

<response>
{response}
</response>

After scoring using the guideline above, tell me your score, wrapped in <score></score> tags.
""".strip()


class BoNUserSimulator(UserSimulator):
    """Best-of-N (N=4 by default) stabilized human simulator (Subsection
    4.2, "Stabilizing Simulated Human"). At each turn, samples N candidate
    responses from the underlying UserSimulator and uses a self-critique
    LLM call to pick the best one, instead of taking the first sample.
    """

    def __init__(
        self,
        llm: str,
        instructions: Optional[str],
        judge: LLMClient,
        n: int = 4,
        tools=None,
        llm_args: Optional[dict] = None,
        persona_config: Optional[PersonaConfig] = None,
    ):
        super().__init__(
            llm=llm,
            instructions=instructions,
            tools=tools,
            llm_args=llm_args,
            persona_config=persona_config,
        )
        self._judge = judge
        self._n = n

    def generate_next_message(
        self, message: ValidUserInputMessage, state: UserState
    ) -> tuple[UserMessage, UserState]:
        candidates: list[UserMessage] = []
        candidate_state: Optional[UserState] = None
        for _ in range(self._n):
            trial_state = state.model_copy(deep=True)
            candidate_msg = self._generate_next_message(message, trial_state)
            candidates.append(candidate_msg)
            if candidate_state is None:
                candidate_state = trial_state

        best = self._pick_best(candidates)
        candidate_state.messages.append(best)
        return best, candidate_state

    def _pick_best(self, candidates: list[UserMessage]) -> UserMessage:
        # Tool calls and stop/transfer sentinels are unambiguous -- no need
        # to spend a judge call scoring them.
        for msg in candidates:
            if msg.is_tool_call() or self.is_stop(msg):
                return msg

        best_msg = candidates[0]
        best_score = -1.0
        for msg in candidates:
            score = self._score_candidate(msg)
            if score > best_score:
                best_score = score
                best_msg = msg
        return best_msg

    def _score_candidate(self, msg: UserMessage) -> float:
        prompt = BON_JUDGE_PROMPT_TEMPLATE.format(
            description=self.instructions, response=msg.content or ""
        )
        raw = self._judge.complete(
            system=BON_JUDGE_SYSTEM_PROMPT, user=prompt, temperature=0.0, max_tokens=200
        )
        match = _SCORE_RE.search(raw)
        return float(match.group(1)) if match else 0.0


def build_bon_human_simulator(
    task: Task,
    llm: str,
    judge: LLMClient,
    n: int = 4,
    llm_args: Optional[dict] = None,
    persona_config: Optional[PersonaConfig] = None,
) -> BoNUserSimulator:
    return BoNUserSimulator(
        llm=llm,
        instructions=str(task.user_scenario),
        judge=judge,
        n=n,
        tools=None,
        llm_args=llm_args or {},
        persona_config=persona_config,
    )
