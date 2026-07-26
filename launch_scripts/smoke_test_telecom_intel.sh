#!/usr/bin/env bash
#
# Smoke test: run a handful of telecom no-user-mode tasks against a model
# served at the ASU RC OpenAI-compatible endpoint and check the raw
# transcript for CJK (Chinese/Japanese/Korean) character leakage in the
# agent's output.
#
# This is deliberately small (--num-tasks) and cheap -- it's meant to
# answer "does this model code-switch into another language here?", not to
# produce a real benchmark number. For a full run use run_telecom_no_user_intel.sh.
#
# MODEL_NAME is required -- there's no safe default for a custom endpoint.
# It should be the exact model string the endpoint expects (e.g. what you'd
# pass as `model=` in the OpenAI client snippet for openai.rc.asu.edu).
#
# Usage:
#   export OPENAI_API_KEY=...          # Intel/ASU RC key
#   MODEL_NAME=<model> bash launch_scripts/smoke_test_telecom_intel.sh
#
# Override knobs:
#   MODEL_NAME=<model> NUM_TASKS=5 bash launch_scripts/smoke_test_telecom_intel.sh

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_DIR"

DOMAIN="telecom"
AGENT="llm_agent_solo"
USER_IMPL="dummy_user"
MODEL_NAME="${MODEL_NAME:?Set MODEL_NAME to the model string the openai.rc.asu.edu endpoint expects}"
AGENT_LLM="openai/${MODEL_NAME}"   # "openai/" prefix tells litellm to use OPENAI_API_BASE below
API_BASE_URL="${API_BASE_URL:-https://openai.rc.asu.edu/v1}"
NUM_TASKS="${NUM_TASKS:-5}"
NUM_TRIALS="${NUM_TRIALS:-1}"
SAVE_TO="${SAVE_TO:-results/smoke_test_telecom_intel_${MODEL_NAME//\//_}.json}"

echo ">>> Checking tau2 CLI and API key are available"
if ! command -v uv >/dev/null && ! command -v tau2 >/dev/null; then
    echo "Neither 'uv' nor 'tau2' found on PATH." >&2
    exit 1
fi
: "${OPENAI_API_KEY:?Export OPENAI_API_KEY (Intel/ASU RC key) before running this script}"

# litellm reads these to route "openai/<model>" calls to the custom endpoint
# instead of api.openai.com.
export OPENAI_API_BASE="$API_BASE_URL"
export OPENAI_BASE_URL="$API_BASE_URL"

mkdir -p "$(dirname "$SAVE_TO")"

echo ">>> Running smoke test: domain=$DOMAIN agent=$AGENT agent-llm=$AGENT_LLM num-tasks=$NUM_TASKS base=$API_BASE_URL"
RUN_CMD=(tau2 run
    --domain "$DOMAIN"
    --agent "$AGENT"
    --agent-llm "$AGENT_LLM"
    --user "$USER_IMPL"
    --num-trials "$NUM_TRIALS"
    --num-tasks "$NUM_TASKS"
    --save-to "$SAVE_TO"
)

if command -v uv >/dev/null; then
    uv run "${RUN_CMD[@]}"
else
    "${RUN_CMD[@]}"
fi

echo ">>> Scanning transcript for CJK characters in the agent's output"
python3 analysis_scripts/check_cjk_leakage.py "$SAVE_TO"
