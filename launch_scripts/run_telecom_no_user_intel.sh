#!/usr/bin/env bash
#
# Run tau2-bench's telecom "no-user" ablation (llm_agent_solo + dummy_user)
# against the ASU RC OpenAI-compatible endpoint (openai.rc.asu.edu), using
# an Intel-hosted model and its own API key.
#
# Works two ways:
#   1. Locally, stepped through by hand:
#        MODEL_NAME=<model> STEP=1 bash launch_scripts/run_telecom_no_user_intel.sh
#      (each stage pauses for Enter; the #SBATCH lines below are ignored by bash)
#   2. Submitted to the Sol cluster as a batch job:
#        MODEL_NAME=<model> sbatch launch_scripts/run_telecom_no_user_intel.sh
#      (edit the #SBATCH block and the "Sol environment" step below first)
#
# MODEL_NAME defaults to llama4-maverick-17b; override to point at a
# different model string the endpoint expects.
#
#SBATCH --job-name=tau2-telecom-no-user-intel
#SBATCH --partition=general
#SBATCH --qos=public
#SBATCH --account=vgangal3
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail

# ---- Config -----------------------------------------------------------
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DOMAIN="telecom"
AGENT="llm_agent_solo"
USER_IMPL="dummy_user"
MODEL_NAME="${MODEL_NAME:-llama4-maverick-17b}"
AGENT_LLM="openai/${MODEL_NAME}"   # "openai/" prefix tells litellm to use OPENAI_API_BASE below
API_BASE_URL="${API_BASE_URL:-https://openai.rc.asu.edu/v1}"
NUM_TRIALS="${NUM_TRIALS:-3}"
SAVE_TO="${SAVE_TO:-results/telecom_no_user_intel_${MODEL_NAME//\//_}.json}"
STEP="${STEP:-0}"   # STEP=1 to pause between stages for manual step-through
KEY_FILE="${KEY_FILE:-$HOME/intel_ai_key.sh}"   # sourced to set OPENAI_API_KEY on Sol

pause() {
    echo ">>> $1"
    if [[ "$STEP" == "1" ]]; then
        read -rp "    press Enter to continue... " _
    fi
}

# ---- Step 1: repo + logging setup -------------------------------------
pause "cd into repo and create output dirs: $REPO_DIR"
cd "$REPO_DIR"
mkdir -p logs "$(dirname "$SAVE_TO")"

# ---- Step 2: Sol environment (only matters under sbatch) --------------
if [[ -n "${SLURM_JOB_ID:-}" ]]; then
    pause "Loading Sol modules / activating environment"
    module load mamba/latest 2>/dev/null || true
    source activate tau2-bench 2>/dev/null || true   # TODO: adjust to your Sol env name
fi

# ---- Step 3: sanity checks + endpoint config ---------------------------
pause "Checking tau2 CLI and Intel API key are available"
if ! command -v uv >/dev/null && ! command -v tau2 >/dev/null; then
    echo "Neither 'uv' nor 'tau2' found on PATH." >&2
    exit 1
fi
if [[ -f "$KEY_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$KEY_FILE"
fi
: "${OPENAI_API_KEY:?OPENAI_API_KEY not set and $KEY_FILE not found (only available on Sol) -- export it manually to run locally}"

# litellm reads these to route "openai/<model>" calls to a custom endpoint
# instead of api.openai.com.
export OPENAI_API_BASE="$API_BASE_URL"
export OPENAI_BASE_URL="$API_BASE_URL"

# ---- Step 4: run the no-user (solo) evaluation -------------------------
pause "Running tau2 in no-user mode: domain=$DOMAIN agent=$AGENT agent-llm=$AGENT_LLM base=$API_BASE_URL"
RUN_CMD=(tau2 run
    --domain "$DOMAIN"
    --agent "$AGENT"
    --agent-llm "$AGENT_LLM"
    --user "$USER_IMPL"
    --num-trials "$NUM_TRIALS"
    --save-to "$SAVE_TO"
)

if command -v uv >/dev/null; then
    uv run "${RUN_CMD[@]}"
else
    "${RUN_CMD[@]}"
fi

pause "Done. Results saved to $SAVE_TO"
