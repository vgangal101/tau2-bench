# $\tau^2$-Bench: Evaluating Conversational Agents in a Dual-Control Environment

[![python](https://img.shields.io/badge/Python-3.12%2B-blue.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![arXiv](http://img.shields.io/badge/cs.AI-arXiv%3A2506.07982-B31B1B.svg?logo=arxiv&logoColor=red)](https://arxiv.org/abs/2506.07982)
[![blog](https://img.shields.io/badge/blog-tau2--bench-green)](https://sierra.ai/blog/benchmarking-agents-in-collaborative-real-world-scenarios)
[![Twitter](https://img.shields.io/twitter/url/https/twitter.com/sierra.svg?style=social&label=Follow%20%40SierraPlatform)](https://x.com/SierraPlatform/status/1932464265207889974)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?logo=linkedin&logoColor=white)](https://www.linkedin.com/posts/sierra_last-year-we-introduced-%F0%9D%9C%8F-bench-a-benchmark-activity-7338229693898231809-F8L4?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAdc8goBmhEsiEo1_t_XSJbAnY4_zMfAWcE)
[![Leaderboard](https://img.shields.io/badge/🏆_Live_Leaderboard-taubench.com-brightgreen?style=flat)](https://taubench.com)

<div align="center">
<img src="figs/overview.png" width="95%" alt="System Overview"><br>
<em>Figure 1: τ²-bench allows users to interact with the agent and the environment</em>
</div>

<div align="center">
<img src="figs/traj.png" width="95%" alt="Trajectory"><br>
<em>Figure 2: Trajectory of a conversation between an agent and a user</em>
</div>

## What's New

- **Knowledge Domain (`banking_knowledge`)** — A knowledge-retrieval-based customer service domain with configurable RAG pipelines, document search, embeddings, and agentic shell-based search. [Learn more →](src/tau2/knowledge/README.md)
- **Voice Full-Duplex (Audio Native)** — End-to-end voice evaluation with multiple realtime providers (OpenAI, Gemini, Nova Sonic, xAI, Deepgram, Qwen). [Learn more →](src/tau2/voice/audio_native/README.md)
- **Reinforcement Learning Support** — Gymnasium-compatible interface for training RL agents, interactive play mode, and train/test task splits. [Learn more →](src/tau2/gym/README.md)
- **Live Leaderboard** — Compare model performance at [taubench.com](https://taubench.com). [Submit your results →](docs/leaderboard-submission.md)

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

> **Backward compatibility note**: If you are evaluating an agent (not training), use the `base` task split to evaluate on the complete task set that matches the original τ²-bench structure. This is the default.

## Overview

$\tau^2$-bench is a simulation framework for evaluating customer service agents across multiple domains. It supports text and voice interactions in both half-duplex (turn-based) and full-duplex (simultaneous) communication modes.

**$\tau^2$-bench is the new iteration of the original $\tau$-bench**, featuring code fixes and an additional telecom domain.

Each domain specifies:
- A **policy** that the agent must follow
- A set of **tools** that the agent can use
- A set of **tasks** to evaluate the agent's performance
- Optionally: a set of **user tools** for the user simulator

**Available domains**: `mock` · `airline` · `retail` · `telecom` · `banking_knowledge`

| Modality | Half-Duplex | Full-Duplex |
|----------|-------------|-------------|
| **Text** | Turn-based chat | Streaming with interruptions |
| **Voice** | Synthesis + transcription | Audio native (realtime providers) |

## Quick Start

### 1. Install

```bash
git clone https://github.com/sierra-research/tau2-bench
cd tau2-bench
brew install portaudio  # required for pyaudio
uv sync
```

This requires [uv](https://docs.astral.sh/uv/getting-started/installation/). You also need `portaudio` installed on your system (`brew install portaudio` on macOS). See the [full installation guide](docs/getting-started.md) for details on all system dependencies.

### 2. Set up API keys

```bash
cp .env.example .env
# Edit .env with your API keys (uses LiteLLM — any supported provider works)
```

### 3. Run an evaluation

```bash
tau2 run --domain airline --agent-llm gpt-4.1 --user-llm gpt-4.1 \
  --num-trials 1 --num-tasks 5
```

Results are saved to `data/simulations/`. Use `tau2 view` to browse them.

## Documentation

### Getting Started

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, API keys, first run, output structure, configuration |
| [CLI Reference](docs/cli-reference.md) | All `tau2` commands and options |

### Core Concepts

| Document | Description |
|----------|-------------|
| [Agent Developer Guide](src/tau2/agent/README.md) | Build and evaluate your own agent |
| [Domains](src/tau2/domains/README.md) | Domain structure, data format, and available domains |
| [Orchestrator & Communication Modes](src/tau2/orchestrator/README.md) | Half-duplex, full-duplex, async-tool, and event-driven orchestration |

### Knowledge Retrieval

| Document | Description |
|----------|-------------|
| [Knowledge Retrieval](src/tau2/knowledge/README.md) | Retrieval pipeline configs, embeddings, RAG, and sandbox setup for the `banking_knowledge` domain |

### Voice & Audio

| Document | Description |
|----------|-------------|
| [Voice Mode](src/tau2/voice/README.md) | Voice synthesis, transcription, and noise simulation |
| [Audio Native Mode](src/tau2/voice/audio_native/README.md) | End-to-end voice with realtime providers (OpenAI, Gemini, Nova, xAI, Deepgram, Qwen) |

### RL & Training

| Document | Description |
|----------|-------------|
| [Gym Interface](src/tau2/gym/README.md) | Gymnasium-compatible environment, play mode, train/test splits |

### Leaderboard & Experiments

| Document | Description |
|----------|-------------|
| [Leaderboard Submission](docs/leaderboard-submission.md) | How to submit results to [taubench.com](https://taubench.com) |
| [Experiments](src/experiments/README.md) | Experimental features and research code |

### Project

| Document | Description |
|----------|-------------|
| [Contributing](CONTRIBUTING.md) | How to contribute to τ²-bench |
| [Changelog](CHANGELOG.md) | Version history and release notes |

## Contributing

We welcome contributions! Whether you're fixing bugs, adding features, creating domains, or contributing research code, see our [Contributing Guide](CONTRIBUTING.md) for guidelines.

## Citation

```bibtex
@misc{barres2025tau2,
      title={$\tau^2$-Bench: Evaluating Conversational Agents in a Dual-Control Environment}, 
      author={Victor Barres and Honghua Dong and Soham Ray and Xujie Si and Karthik Narasimhan},
      year={2025},
      eprint={2506.07982},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2506.07982}, 
}
```
