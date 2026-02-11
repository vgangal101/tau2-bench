# Getting Started

This guide walks you through installing τ²-bench, configuring API keys, and running your first evaluation.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package and project manager
- Python 3.12+ (uv will download it automatically if not present)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/sierra-research/tau2-bench
cd tau2-bench
```

### 2. Install system dependencies

**PortAudio** (required for `pyaudio`):

**macOS:**
```bash
brew install portaudio
```

**ffmpeg** (required for voice features):

**macOS:**
```bash
brew install ffmpeg
```

### 3. Install τ²-bench

```bash
uv sync
```

This creates a virtual environment, installs all dependencies from the lockfile, and enables the `tau2` command. The Python version is pinned via `.python-version` (3.12) — uv will download it automatically if needed.

> **Note:** If you install without `-e` mode (e.g., `uv pip install .`), you'll need to set the `TAU2_DATA_DIR` environment variable to point to your data directory:
> ```bash
> export TAU2_DATA_DIR=/path/to/your/tau2-bench/data
> ```

### 4. Verify your installation

```bash
uv run tau2 check-data
```

This checks that your data directory is correctly configured and all required files are present.

## Setting Up API Keys

We use [LiteLLM](https://github.com/BerriAI/litellm) to manage LLM APIs, so you can use any LLM provider supported by LiteLLM.

Copy `.env.example` as `.env` and edit it to include your API keys:

```bash
cp .env.example .env
```

### Voice API Keys (for voice-enabled features)

If you're using voice features, add the following to your `.env` file:
- `ELEVENLABS_API_KEY` — for voice synthesis
- `DEEPGRAM_API_KEY` — for voice transcription

## Running Your First Evaluation

### Standard text-based evaluation (half-duplex)

```bash
tau2 run --domain airline --agent-llm gpt-4.1 --user-llm gpt-4.1 \
  --num-trials 1 --num-tasks 5
```

Results are saved in `data/simulations/`.

### Audio native mode (voice full-duplex)

```bash
tau2 run --domain retail --audio-native --num-tasks 1 --verbose-logs
```

See the [Audio Native Documentation](../src/tau2/voice/audio_native/README.md) for provider configuration and all options.

> **Note**: Text full-duplex and voice half-duplex modes are available via the Python API but are not currently exposed through the CLI. See the [Orchestrator documentation](../src/tau2/orchestrator/README.md) and [Voice documentation](../src/tau2/voice/README.md) for programmatic usage.

> **tip**: for full agent evaluation that matches the original τ²-bench methodology, remove `--num-tasks` to evaluate on the complete task set (the `base` split is used by default).

## Simulation Output Structure

Each simulation run creates a directory. The standard text-based run produces:

```
data/simulations/<timestamp>_<domain>_<agent>_<user>/
└── results.json             # Simulation results and metrics
```

When using `--audio-native --verbose-logs`, the output includes additional data:

```
data/simulations/<timestamp>_<domain>_<agent>_<user>/
├── results.json                    # Simulation results and metrics
├── llm_logs/                       # LLM call logs
│   └── task_<task_id>/
│       └── *.json
├── ticks/                          # Tick-by-tick conversation data
│   └── task_<task_id>.json
└── audio/                          # Audio files
    └── task_<task_id>/
        ├── combined.wav            # Full conversation audio
        ├── agent.wav               # Agent-only audio track
        └── user.wav                # User-only audio track
```

## Viewing Results

```bash
tau2 view
```

This allows you to browse simulation files, view agent performance metrics, inspect individual simulations, and view task details. Works for both standard text and audio native runs.

## Configuration

The framework is configured via [`src/tau2/config.py`](../src/tau2/config.py).

### LLM Call Caching

LLM call caching is disabled by default. To enable it:

1. Make sure `redis` is running
2. Update the redis config in `config.py` if necessary
3. Set `LLM_CACHE_ENABLED` to `True` in `config.py`

## Cleanup

To remove all generated files and the virtual environment:

```bash
make clean
```

## Next Steps

- [CLI Reference](cli-reference.md) — all `tau2` commands and options
- [Agent Developer Guide](../src/tau2/agent/README.md) — build and evaluate your own agent
- [Domain Documentation](../src/tau2/domains/README.md) — understand the available domains
- [Communication Modes](../src/tau2/orchestrator/README.md) — half-duplex, full-duplex, and event-driven orchestration
- [Voice Documentation](../src/tau2/voice/README.md) — voice synthesis and transcription
- [Audio Native Documentation](../src/tau2/voice/audio_native/README.md) — end-to-end voice with realtime providers
- [Gym/RL Interface](../src/tau2/gym/README.md) — Gymnasium-compatible environment for RL training
