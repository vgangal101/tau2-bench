# CLI Reference

The `tau2` command provides a unified interface for all τ²-bench functionality. Use `tau2 <command> --help` to see full details for any command.

## `tau2 run` — Run Evaluations

Run agent evaluations across different communication modes.

### Basic Usage

```bash
tau2 run \
  --domain <domain> \
  --agent-llm <llm_name> \
  --user-llm <llm_name> \
  --num-trials <trial_count> \
  --num-tasks <task_count>
```

### Common Options

| Option | Description |
|--------|-------------|
| `--domain`, `-d` | Domain to evaluate (choices come from registered domains) |
| `--agent-llm` | LLM model for the agent |
| `--user-llm` | LLM model for the user simulator |
| `--agent-llm-args` | JSON dict of extra args for agent LLM (e.g. `'{"temperature": 0.5}'`) |
| `--user-llm-args` | JSON dict of extra args for user LLM |
| `--agent` | Agent implementation to use (default: `llm_agent`) |
| `--user` | User simulator implementation to use (default: `user_simulator`) |
| `--num-trials` | Number of evaluation trials (default: `1`) |
| `--num-tasks` | Number of tasks to evaluate (omit for all tasks) |
| `--task-ids` | Specific task IDs to evaluate |
| `--task-split-name` | Task split to use (default: `base`) |
| `--task-set-name` | Task set to use (default: domain default) |
| `--max-steps` | Maximum simulation steps (default: `200`) |
| `--max-errors` | Maximum consecutive tool errors allowed (default: `10`) |
| `--max-concurrency` | Maximum concurrent simulations (default: `3`) |
| `--seed` | Random seed for reproducibility (default: `300`) |
| `--save-to` | Custom output directory name (saved under `data/simulations/`) |
| `--log-level` | Log level (default: `ERROR`) |
| `--verbose-logs` | Save detailed logs (LLM calls, audio, ticks) |
| `--audio-debug` | Save per-tick audio files and timing analysis (requires `--audio-native`) |
| `--llm-log-mode` | LLM log mode when `--verbose-logs` is on: `all` or `latest` (default: `latest`) |
| `--max-retries` | Max retries for failed tasks (default: `3`) |
| `--retry-delay` | Delay in seconds between retries (default: `1.0`) |
| `--enforce-communication-protocol` | Enforce protocol rules (e.g. no mixed text + tool call messages) |
| `--user-persona` | User persona config as JSON dict |
| `--xml-prompt` | Force XML tags in system prompt |
| `--no-xml-prompt` | Force plain text system prompt (no XML tags) |
| `--auto-resume` | Automatically resume from existing save file without prompting |
| `--auto-review` | Automatically run LLM conversation review after each simulation |
| `--review-mode` | Review mode when `--auto-review` is on: `full` or `user` (default: `full`) |
| `--hallucination-retries` | Max retries when user simulator hallucination is detected (full-duplex only, default: `3`). Set to `0` to disable |
| `--audio-native` | Enable audio native mode (voice full-duplex) |

### Audio Native Options

| Option | Default | Description |
|--------|---------|-------------|
| `--audio-native` | `false` | Enable audio native mode |
| `--audio-native-provider` | `openai` | Provider: `openai`, `gemini`, `nova`, `xai`, `deepgram`, `qwen`, `livekit` |
| `--cascaded-config` | *(none)* | Cascaded config preset for `livekit` provider (e.g., `default`, `openai-thinking`, `openai-thinking-high`) |
| `--audio-native-model` | *(per-provider)* | Model to use (defaults to provider-specific model if not set) |
| `--tick-duration` | `0.2` | Tick duration in seconds (simulation timestep) |
| `--max-steps-seconds` | `600` | Maximum conversation duration in seconds |
| `--speech-complexity` | `regular` | Speech complexity: `control`, `regular`, or ablation variants (`control_audio`, `control_accents`, `control_behavior`, `control_audio_accents`, `control_audio_behavior`, `control_accents_behavior`) |
| `--pcm-sample-rate` | `16000` | User simulator PCM synthesis rate |
| `--telephony-rate` | `8000` | API/agent telephony rate |

**Turn-taking thresholds:**

| Option | Default | Description |
|--------|---------|-------------|
| `--wait-to-respond-other` | `1.0` | Min seconds since agent spoke before user responds |
| `--wait-to-respond-self` | `5.0` | Min seconds since user spoke before responding again |
| `--yield-when-interrupted` | `1.0` | How long user keeps speaking when agent interrupts |
| `--yield-when-interrupting` | `5.0` | How long user keeps speaking when interrupting agent |
| `--interruption-check-interval` | `2.0` | Interval for checking interruptions |
| `--integration-duration` | `0.5` | Integration duration for linearization |
| `--silence-annotation-threshold` | `4.0` | Silence threshold for annotations |

**Agent behavior flags:**

| Option | Default | Description |
|--------|---------|-------------|
| `--no-buffer-until-complete` | `false` | Don't buffer audio until complete utterance |
| `--fast-forward` | `false` | Enable fast-forward mode (run as fast as possible instead of real-time) |
| `--send-audio-instant` | `false` | Send audio instantly (all at once per tick) instead of streaming at real-time rate |

### Examples

```bash
# Standard text evaluation
tau2 run --domain airline --agent-llm gpt-4.1 --user-llm gpt-4.1 --num-trials 1 --num-tasks 5

# Audio native (voice full-duplex)
tau2 run --domain retail --audio-native --num-tasks 1 --verbose-logs

# Audio native with custom provider and settings
tau2 run --domain retail --audio-native --audio-native-provider gemini \
  --tick-duration 0.2 --max-steps-seconds 240 --speech-complexity control \
  --verbose-logs --save-to my_audio_native_run

# Audio native with LiveKit cascaded pipeline
tau2 run --domain retail --audio-native --audio-native-provider livekit \
  --cascaded-config default --num-tasks 1 --verbose-logs

# Audio native with hallucination retries disabled
tau2 run --domain retail --audio-native --hallucination-retries 0 --num-tasks 1
```

> **Note**: Text full-duplex and voice half-duplex modes are available programmatically via the Python API but are not exposed as CLI flags. See the [Orchestrator documentation](../src/tau2/orchestrator/README.md) and [Voice documentation](../src/tau2/voice/README.md) for programmatic usage.

---

## `tau2 play` — Interactive Play Mode

Experience τ²-bench interactively from either perspective.

```bash
tau2 play
```

Play mode allows you to:
- **Play as Agent**: Manually control the agent's responses and tool calls
- **Play as User**: Control the user while an LLM agent handles requests (available in domains with user tools like telecom)
- **Understand tasks** by walking through scenarios step-by-step
- **Test strategies** before implementing them in code
- **Choose task splits** to practice on training data or test on held-out tasks

See the [Gym Documentation](../src/tau2/gym/README.md) for using the gymnasium interface programmatically.

---

## `tau2 view` — View Results

Browse and analyze simulation results.

```bash
tau2 view
```

| Option | Description |
|--------|-------------|
| `--dir` | Directory containing simulation files (defaults to `data/simulations/`) |
| `--file` | Path to a specific results file to view |
| `--only-show-failed` | Only show failed tasks |
| `--only-show-all-failed` | Only show tasks that failed in all trials |
| `--expanded-ticks` | Show expanded tick view (for full-duplex simulations) |

---

## `tau2 domain` — View Domain Documentation

View domain policy and API documentation.

```bash
tau2 domain <domain>
```

Then visit http://127.0.0.1:8004/redoc to see the domain policy and available tools.

---

## `tau2 check-data` — Check Data Configuration

Verify that your data directory is properly configured.

```bash
tau2 check-data
```

---

## `tau2 start` — Start All Servers

Start all domain servers.

```bash
tau2 start
```

---

## `tau2 evaluate-trajs` — Evaluate Trajectories

Re-evaluate trajectory files and optionally update rewards.

```bash
tau2 evaluate-trajs <paths...>
```

| Option | Description |
|--------|-------------|
| `<paths>` | Paths to trajectory files, directories, or glob patterns |
| `-o`, `--output-dir` | Directory to save updated trajectories. If omitted, only displays metrics |

---

## `tau2 review` — LLM Conversation Review

Run LLM-based review on simulation results to detect agent and/or user errors.

```bash
tau2 review <path>
```

| Option | Description |
|--------|-------------|
| `<path>` | Path to a `results.json` file or directory containing them |
| `-m`, `--mode` | Review mode: `full` (agent + user, default) or `user` (user simulator only) |
| `-o`, `--output` | Output path for reviewed results (single file only) |
| `--interruption-enabled` | Flag indicating interruption was enabled in these simulations |
| `--show-details` | Show detailed review for each simulation |
| `-c`, `--max-concurrency` | Max concurrent reviews (default: `32`) |
| `--limit` | Limit review to first N simulations |
| `--task-ids` | Only review simulations for these task IDs |
| `--log-llm` | Log LLM request/response for each review call |

---

## `tau2 leaderboard` — View Leaderboard

Show the τ²-bench leaderboard in the terminal.

```bash
tau2 leaderboard
```

| Option | Description |
|--------|-------------|
| `--domain`, `-d` | Show leaderboard for a specific domain: `retail`, `airline`, or `telecom` |
| `--metric`, `-m` | Metric to rank by: `pass_1`, `pass_2`, `pass_3`, `pass_4`, `cost` (default: `pass_1`) |
| `--limit`, `-n` | Limit the number of entries shown |

---

## `tau2 submit` — Leaderboard Submission

See the full [Leaderboard Submission Guide](leaderboard-submission.md).

```bash
# Prepare a submission
tau2 submit prepare <paths...> --output ./my_submission

# Validate a submission
tau2 submit validate <submission_dir>

# Verify trajectory files
tau2 submit verify-trajs <paths...>
```

---

## Environment CLI (beta)

An interactive CLI for directly querying and testing domain environments.

```bash
make env-cli
```

**Commands:**
- `:q` — quit
- `:d` — change domain
- `:n` — start new session (clears history)

**Example:**
```bash
$ make env-cli

Welcome to the Environment CLI!
Connected to airline domain.

Query (:n new session, :d change domain, :q quit)> What flights are available from SF to LA tomorrow?
Assistant: Let me check the flight availability for you...
```

Useful for testing domain tools, debugging environment responses, and exploring domain functionality without starting the full server stack.

---

## Running Tests

```bash
make test
```

---

## Advanced: Ablation Studies

The `telecom` domain supports ablation studies for research purposes.

### No-user mode

The LLM is given all tools and information upfront (no user interaction):

```bash
tau2 run \
  --domain telecom \
  --agent llm_agent_solo \
  --agent-llm gpt-4.1 \
  --user dummy_user
```

### Oracle-plan mode

The LLM is given an oracle plan, removing the need for action planning:

```bash
tau2 run \
  --domain telecom \
  --agent llm_agent_gt \
  --agent-llm gpt-4.1 \
  --user-llm gpt-4.1
```

### Workflow policy format

Test the impact of policy format using the workflow policy for telecom:

```bash
tau2 run \
  --domain telecom-workflow \
  --agent-llm gpt-4.1 \
  --user-llm gpt-4.1
```
