import random

import pytest

from apigen_mt.phase1.generator import GenerationParseError, generate_blueprint, parse_generation
from apigen_mt.phase1.samplers import ContextSampler
from apigen_mt.tests.conftest import FakeLLMClient, make_answer_response


def test_parse_generation_extracts_thought_and_json_answer():
    raw = make_answer_response(
        "step by step", {"intent": "hi", "actions": [], "outputs": ["a"]}
    )
    thought, data = parse_generation(raw)
    assert thought == "step by step"
    assert data == {"intent": "hi", "actions": [], "outputs": ["a"]}


def test_parse_generation_tolerates_json_code_fences():
    raw = "<thought>t</thought><answer>```json\n{\"intent\": \"hi\", \"actions\": [], \"outputs\": []}\n```</answer>"
    _, data = parse_generation(raw)
    assert data["intent"] == "hi"


def test_parse_generation_raises_on_missing_answer_block():
    with pytest.raises(GenerationParseError):
        parse_generation("no tags here")


def test_parse_generation_raises_on_malformed_json():
    with pytest.raises(GenerationParseError):
        parse_generation("<answer>{not json}</answer>")


def test_generate_blueprint_builds_typed_blueprint_from_sampled_context(retail_plugin):
    rng = random.Random(11)
    sampler = ContextSampler(retail_plugin, rng)
    context = sampler.sample()
    answer = {
        "intent": "Do a thing",
        "actions": [{"name": "get_user_details", "arguments": {"user_id": "x"}}],
        "outputs": ["some info"],
    }
    llm = FakeLLMClient(make_answer_response("thinking", answer))
    blueprint = generate_blueprint(retail_plugin, llm, context)
    assert blueprint.intent == "Do a thing"
    assert blueprint.actions[0].name == "get_user_details"
    assert blueprint.outputs == ["some info"]
    assert blueprint.persona == context.persona
    # feedback text, if provided, must reach the prompt
    llm2 = FakeLLMClient(make_answer_response("t", answer))
    generate_blueprint(retail_plugin, llm2, context, feedback="fix your JSON")
    assert "fix your JSON" in llm2.calls[0]["user"]
