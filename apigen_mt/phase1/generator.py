"""LLM-based task generator (Subsection 4.1.1, step 2). Prompt is templated
with plugin-supplied fill-ins (tools, policy excerpt, persona, data) -- no
domain-specific text lives here.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from apigen_mt.domains.base import DomainPlugin, ToolInfo
from apigen_mt.llm_client import LLMClient
from apigen_mt.phase1.samplers import SampledContext
from apigen_mt.phase1.schema import BlueprintAction, TaskBlueprint

SYSTEM_PROMPT = (
    "You are a meticulous data-generation agent for the {domain} customer service "
    "domain. You produce realistic task configurations for training and evaluating "
    "AI agents, following the instructions and guidelines exactly."
)

GENERATOR_PROMPT_TEMPLATE = """
## Instructions
Generate a task instruction that mimics a realistic human user and their intentions, with a distinct \
personality and goal. The task instruction should be followed by 'actions', a list of the tool calls \
needed to solve the task, and 'outputs', a list of answers to any specific information requests made \
by the user. Think step by step about the action(s) and corresponding tool_call(s) needed to fulfill \
the user's request. Focus on a realistic {domain} scenario consistent with the guidelines below.

## Guidelines for Generating the Task Instruction (q)
{policy_excerpt}

## Persona
{persona}

## User Data
{user_record}

## Related Records
{related_records}

## Guidelines for generating Groundtruth Actions (a_gt)
1. The main focus is to generate actions that modify the underlying database -- prefer the sampled \
'write' tool(s) below as the core of the task.
2. For requests that do not modify the database (pure information requests), do not create a tool call \
for them -- scan the data above directly and put the answer in 'outputs' (o_gt) instead.
3. Include any read/lookup tool calls that are genuinely necessary to establish identity or obtain \
IDs/arguments referenced later, using only the concrete data provided above.
4. Include multiple tool calls when the scenario requires multiple steps.
5. Every action must use arguments grounded in the data above and adhere to the guidelines.

## Suggested write tool(s) to center the task on
{write_tools}

## Other tools available
{read_tools}

## Output Format
Enclose your reasoning within <thought></thought> tags, and the final structured response within \
<answer></answer> tags. The structured response must be strict JSON with keys "intent", "actions", \
"outputs", where "actions" is a list of {{"name": ..., "arguments": {{...}}}} objects.

## Example Tasks
{examples}

Do not copy the instruction or action patterns from the examples verbatim. Ground the generation in the \
data provided above.
{feedback_block}
Generate the task now.
""".strip()


class GenerationParseError(ValueError):
    """Raised when the LLM output doesn't contain a parseable <answer> block."""


_THOUGHT_RE = re.compile(r"<thought>(.*?)</thought>", re.DOTALL)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def _format_tool(tool: ToolInfo) -> str:
    first_line = tool.signature.splitlines()[0] if tool.signature else tool.name
    return f"- {tool.name}: {first_line}"


def build_prompt(
    plugin: DomainPlugin, context: SampledContext, feedback: Optional[str]
) -> str:
    feedback_block = f"\n## Feedback From Previous Attempt\n{feedback}\n" if feedback else ""
    return GENERATOR_PROMPT_TEMPLATE.format(
        domain=plugin.name,
        policy_excerpt=context.policy_excerpt,
        persona=context.persona,
        user_record=json.dumps(context.user_record, indent=2),
        related_records=json.dumps(context.related_records, indent=2),
        write_tools="\n".join(_format_tool(t) for t in context.write_tools) or "(none sampled)",
        read_tools="\n".join(_format_tool(t) for t in context.read_tools) or "(none sampled)",
        examples=json.dumps(context.examples, indent=2),
        feedback_block=feedback_block,
    )


def parse_generation(raw_text: str) -> tuple[Optional[str], dict]:
    thought_match = _THOUGHT_RE.search(raw_text)
    answer_match = _ANSWER_RE.search(raw_text)
    if not answer_match:
        raise GenerationParseError(
            f"No <answer> block found in generator output: {raw_text[:500]!r}"
        )
    thought = thought_match.group(1).strip() if thought_match else None
    answer_text = _FENCE_RE.sub("", answer_match.group(1).strip()).strip()
    try:
        data = json.loads(answer_text)
    except json.JSONDecodeError as exc:
        raise GenerationParseError(
            f"Could not parse JSON in <answer>: {exc}\n{answer_text[:500]!r}"
        ) from exc
    return thought, data


def generate_blueprint(
    plugin: DomainPlugin,
    llm: LLMClient,
    context: SampledContext,
    feedback: Optional[str] = None,
) -> TaskBlueprint:
    prompt = build_prompt(plugin, context, feedback)
    raw = llm.complete(
        system=SYSTEM_PROMPT.format(domain=plugin.name), user=prompt, temperature=0.9
    )
    thought, data = parse_generation(raw)

    actions = [
        BlueprintAction(
            name=a["name"],
            arguments=a.get("arguments", {}),
            requestor=a.get("requestor", "assistant"),
        )
        for a in data.get("actions", [])
    ]
    return TaskBlueprint(
        domain=plugin.name,
        persona=context.persona,
        thought=thought,
        intent=data.get("intent", ""),
        actions=actions,
        outputs=list(data.get("outputs", [])),
    )
