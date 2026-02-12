import argparse
import json

from tau2.config import (
    DEFAULT_AGENT_IMPLEMENTATION,
    DEFAULT_AUDIO_NATIVE_MODELS,
    DEFAULT_AUDIO_NATIVE_PROVIDER,
    DEFAULT_BUFFER_UNTIL_COMPLETE,
    DEFAULT_FAST_FORWARD_MODE,
    DEFAULT_INTEGRATION_DURATION_SECONDS,
    DEFAULT_INTERRUPTION_CHECK_INTERVAL_SECONDS,
    DEFAULT_LLM_AGENT,
    DEFAULT_LLM_LOG_MODE,
    DEFAULT_LLM_TEMPERATURE_AGENT,
    DEFAULT_LLM_TEMPERATURE_USER,
    DEFAULT_LLM_USER,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_ERRORS,
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_STEPS_SECONDS,
    DEFAULT_NUM_TRIALS,
    DEFAULT_PCM_SAMPLE_RATE,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_RETRY_MIN_WAIT,
    DEFAULT_SEED,
    DEFAULT_SEND_AUDIO_INSTANT,
    DEFAULT_SILENCE_ANNOTATION_THRESHOLD_SECONDS,
    DEFAULT_SPEECH_COMPLEXITY,
    DEFAULT_TELEPHONY_RATE,
    DEFAULT_TICK_DURATION_SECONDS,
    DEFAULT_USER_IMPLEMENTATION,
    DEFAULT_WAIT_TO_RESPOND_THRESHOLD_OTHER_SECONDS,
    DEFAULT_WAIT_TO_RESPOND_THRESHOLD_SELF_SECONDS,
    DEFAULT_YIELD_THRESHOLD_WHEN_INTERRUPTED_SECONDS,
    DEFAULT_YIELD_THRESHOLD_WHEN_INTERRUPTING_SECONDS,
)
from tau2.data_model.persona import PersonaConfig
from tau2.data_model.simulation import AudioNativeConfig, RunConfig
from tau2.run import get_options, run_domain
from tau2.scripts.leaderboard.verify_trajectories import VerificationMode


def add_run_args(parser):
    """Add run arguments to a parser."""
    domains = get_options().domains
    parser.add_argument(
        "--domain",
        "-d",
        type=str,
        choices=domains,
        help="The domain to run the simulation on",
    )
    parser.add_argument(
        "--num-trials",
        type=int,
        default=DEFAULT_NUM_TRIALS,
        help="The number of times each task is run. Default is 1.",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default=DEFAULT_AGENT_IMPLEMENTATION,
        choices=get_options().agents,
        help=f"The agent implementation to use. Default is {DEFAULT_AGENT_IMPLEMENTATION}.",
    )
    parser.add_argument(
        "--agent-llm",
        type=str,
        default=DEFAULT_LLM_AGENT,
        help=f"The LLM to use for the agent. Default is {DEFAULT_LLM_AGENT}.",
    )
    parser.add_argument(
        "--agent-llm-args",
        type=json.loads,
        default={"temperature": DEFAULT_LLM_TEMPERATURE_AGENT},
        help=f"The arguments to pass to the LLM for the agent. Default is '{{\"temperature\": {DEFAULT_LLM_TEMPERATURE_AGENT}}}'.",
    )
    parser.add_argument(
        "--user",
        type=str,
        choices=get_options().users,
        default=DEFAULT_USER_IMPLEMENTATION,
        help=f"The user implementation to use. Default is {DEFAULT_USER_IMPLEMENTATION}.",
    )
    parser.add_argument(
        "--user-llm",
        type=str,
        default=DEFAULT_LLM_USER,
        help=f"The LLM to use for the user. Default is {DEFAULT_LLM_USER}.",
    )
    parser.add_argument(
        "--user-llm-args",
        type=json.loads,
        default={"temperature": DEFAULT_LLM_TEMPERATURE_USER},
        help=f"The arguments to pass to the LLM for the user. Default is '{{\"temperature\": {DEFAULT_LLM_TEMPERATURE_USER}}}'.",
    )
    parser.add_argument(
        "--task-set-name",
        type=str,
        default=None,
        choices=get_options().task_sets,
        help="The task set to run the simulation on. If not provided, will load default task set for the domain.",
    )
    parser.add_argument(
        "--task-split-name",
        type=str,
        default="base",
        help="The task split to run the simulation on. If not provided, will load 'base' split.",
    )
    parser.add_argument(
        "--task-ids",
        type=str,
        nargs="+",
        help="(Optional) run only the tasks with the given IDs. If not provided, will run all tasks.",
    )
    parser.add_argument(
        "--num-tasks",
        type=int,
        default=None,
        help="The number of tasks to run.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help=f"The maximum number of steps to run the simulation. Default is {DEFAULT_MAX_STEPS}.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=DEFAULT_MAX_ERRORS,
        help=f"The maximum number of tool errors allowed in a row in the simulation. Default is {DEFAULT_MAX_ERRORS}.",
    )
    parser.add_argument(
        "--save-to",
        type=str,
        required=False,
        help="The path to save the simulation results. Will be saved to data/simulations/<save_to>/results.json. If not provided, will save to <timestamp>_<domain>_<agent>_<user>. If the file already exists, it will try to resume the run.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=DEFAULT_MAX_CONCURRENCY,
        help=f"The maximum number of concurrent simulations to run. Default is {DEFAULT_MAX_CONCURRENCY}.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"The seed to use for the simulation. Default is {DEFAULT_SEED}.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=DEFAULT_LOG_LEVEL,
        help=f"The log level to use for the simulation. Default is {DEFAULT_LOG_LEVEL}.",
    )
    parser.add_argument(
        "--verbose-logs",
        action="store_true",
        default=False,
        help="Enable verbose logging: saves LLM call logs, audio files, per-task logs, and ticks (for audio-native). "
        "Files are saved to the save directory (auto-generated if --save-to not specified).",
    )
    parser.add_argument(
        "--audio-debug",
        action="store_true",
        default=False,
        help="Enable audio debugging for audio-native mode. Saves per-tick audio files and timing "
        "analysis report for diagnosing alignment issues. Requires --audio-native.",
    )
    parser.add_argument(
        "--llm-log-mode",
        type=str,
        choices=["all", "latest"],
        default=DEFAULT_LLM_LOG_MODE,
        help="LLM debug logging mode. Only takes effect when --verbose-logs is enabled. "
        "'all' saves every LLM call (can generate many files), "
        "'latest' keeps only the most recent call of each type (saves space). "
        f"Default is '{DEFAULT_LLM_LOG_MODE}'. Ignored if --verbose-logs is not specified.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_RETRY_ATTEMPTS,
        help=f"Maximum number of retries for failed tasks. Default is {DEFAULT_RETRY_ATTEMPTS}.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_MIN_WAIT,
        help=f"Delay in seconds between retries. Default is {DEFAULT_RETRY_MIN_WAIT}.",
    )
    parser.add_argument(
        "--enforce-communication-protocol",
        action="store_true",
        default=False,
        help="Enforce communication protocol rules (e.g., no mixed messages with text and tool calls). Default is False.",
    )
    parser.add_argument(
        "--user-persona",
        type=json.loads,
        default=None,
        help="User persona config as JSON dict. Supports explicit values or weighted probabilities. "
        'Examples: \'{"verbosity": "minimal"}\', '
        '\'{"verbosity": {"minimal": 0.8, "standard": 0.2}}\'. '
        "If not provided, uses default behavior (standard verbosity).",
    )

    # Audio-native mode arguments
    parser.add_argument(
        "--audio-native",
        action="store_true",
        default=False,
        help="Enable audio-native mode using DiscreteTimeAudioNativeAgent with VoiceStreamingUserSimulator. "
        "This enables full-duplex voice simulation using audio native APIs.",
    )
    parser.add_argument(
        "--audio-native-provider",
        type=str,
        choices=["openai", "gemini", "xai", "nova", "qwen", "deepgram"],
        default=DEFAULT_AUDIO_NATIVE_PROVIDER,
        help=f"Audio native API provider. 'openai' uses OpenAI Realtime API, "
        f"'gemini' uses Google Gemini Live API, 'xai' uses xAI Grok Voice Agent API, "
        f"'nova' uses Amazon Nova Sonic, 'qwen' uses Alibaba Qwen Omni Flash, "
        f"'deepgram' uses Deepgram Voice Agent (cascaded STT→LLM→TTS). "
        f"Default is '{DEFAULT_AUDIO_NATIVE_PROVIDER}'.",
    )
    parser.add_argument(
        "--audio-native-model",
        type=str,
        default=None,
        help="Audio native model to use. If not specified, uses the default model for the selected provider.",
    )
    parser.add_argument(
        "--tick-duration",
        type=float,
        default=DEFAULT_TICK_DURATION_SECONDS,
        help=f"Tick duration in seconds for audio-native mode. Default is {DEFAULT_TICK_DURATION_SECONDS}.",
    )
    parser.add_argument(
        "--max-steps-seconds",
        type=int,
        default=DEFAULT_MAX_STEPS_SECONDS,
        help=f"Maximum conversation duration in seconds for audio-native mode. Default is {DEFAULT_MAX_STEPS_SECONDS}.",
    )
    parser.add_argument(
        "--speech-complexity",
        type=str,
        choices=[
            "control",
            "regular",
            # Single-feature ablations
            "control_audio",
            "control_accents",
            "control_behavior",
            # Pairwise ablations
            "control_audio_accents",
            "control_audio_behavior",
            "control_accents_behavior",
        ],
        default=DEFAULT_SPEECH_COMPLEXITY,
        help=f"Speech complexity level for audio effects. Default is '{DEFAULT_SPEECH_COMPLEXITY}'.",
    )

    # Audio-native: Sample rates
    parser.add_argument(
        "--pcm-sample-rate",
        type=int,
        default=DEFAULT_PCM_SAMPLE_RATE,
        help=f"User simulator PCM synthesis sample rate. Default is {DEFAULT_PCM_SAMPLE_RATE}.",
    )
    parser.add_argument(
        "--telephony-rate",
        type=int,
        default=DEFAULT_TELEPHONY_RATE,
        help=f"API/agent telephony sample rate (OpenAI Realtime API). Default is {DEFAULT_TELEPHONY_RATE}.",
    )

    # Audio-native: Turn-taking thresholds
    parser.add_argument(
        "--wait-to-respond-other",
        type=float,
        default=DEFAULT_WAIT_TO_RESPOND_THRESHOLD_OTHER_SECONDS,
        help=f"Min time since OTHER (agent) spoke before user responds (seconds). Default is {DEFAULT_WAIT_TO_RESPOND_THRESHOLD_OTHER_SECONDS}.",
    )
    parser.add_argument(
        "--wait-to-respond-self",
        type=float,
        default=DEFAULT_WAIT_TO_RESPOND_THRESHOLD_SELF_SECONDS,
        help=f"Min time since SELF (user) spoke before responding (seconds). Default is {DEFAULT_WAIT_TO_RESPOND_THRESHOLD_SELF_SECONDS}.",
    )
    parser.add_argument(
        "--yield-when-interrupted",
        type=float,
        default=DEFAULT_YIELD_THRESHOLD_WHEN_INTERRUPTED_SECONDS,
        help=f"How long user keeps speaking when agent interrupts (seconds). Default is {DEFAULT_YIELD_THRESHOLD_WHEN_INTERRUPTED_SECONDS}.",
    )
    parser.add_argument(
        "--yield-when-interrupting",
        type=float,
        default=DEFAULT_YIELD_THRESHOLD_WHEN_INTERRUPTING_SECONDS,
        help=f"How long user keeps speaking when user interrupts agent (seconds). Default is {DEFAULT_YIELD_THRESHOLD_WHEN_INTERRUPTING_SECONDS}.",
    )
    parser.add_argument(
        "--interruption-check-interval",
        type=float,
        default=DEFAULT_INTERRUPTION_CHECK_INTERVAL_SECONDS,
        help=f"Interval for checking interruptions (seconds). Default is {DEFAULT_INTERRUPTION_CHECK_INTERVAL_SECONDS}.",
    )
    parser.add_argument(
        "--integration-duration",
        type=float,
        default=DEFAULT_INTEGRATION_DURATION_SECONDS,
        help=f"Integration duration for linearization (seconds). Default is {DEFAULT_INTEGRATION_DURATION_SECONDS}.",
    )
    parser.add_argument(
        "--silence-annotation-threshold",
        type=float,
        default=DEFAULT_SILENCE_ANNOTATION_THRESHOLD_SECONDS,
        help=f"Silence threshold for adding annotations to conversation history (seconds). Default is {DEFAULT_SILENCE_ANNOTATION_THRESHOLD_SECONDS}.",
    )

    # Audio-native: Agent behavior flags
    parser.add_argument(
        "--no-buffer-until-complete",
        action="store_true",
        default=False,
        help=f"Don't buffer audio until complete utterance. Default is {DEFAULT_BUFFER_UNTIL_COMPLETE}.",
    )
    parser.add_argument(
        "--no-fast-forward",
        action="store_true",
        default=False,
        help=f"Disable fast-forward mode (run in real-time instead of as fast as possible). Default is {DEFAULT_FAST_FORWARD_MODE}.",
    )
    parser.add_argument(
        "--no-send-audio-instant",
        action="store_true",
        default=False,
        help=f"Simulate streaming audio instead of sending instantly. Default is {DEFAULT_SEND_AUDIO_INSTANT}.",
    )

    # Prompt format
    prompt_format_group = parser.add_mutually_exclusive_group()
    prompt_format_group.add_argument(
        "--xml-prompt",
        action="store_true",
        default=False,
        help="Use XML tags in system prompt (overrides auto-detection).",
    )
    prompt_format_group.add_argument(
        "--no-xml-prompt",
        action="store_true",
        default=False,
        help="Use plain text system prompt without XML tags (overrides auto-detection).",
    )

    # Resume mode
    parser.add_argument(
        "--auto-resume",
        action="store_true",
        default=False,
        help="Automatically resume from existing save file without prompting (for non-interactive runs).",
    )

    # Auto-review mode
    parser.add_argument(
        "--auto-review",
        action="store_true",
        default=False,
        help="Automatically run LLM conversation review after each simulation.",
    )
    parser.add_argument(
        "--review-mode",
        type=str,
        choices=["full", "user"],
        default="full",
        help="Review mode when --auto-review is enabled: 'full' (agent+user errors, default) or 'user' (user simulator only).",
    )
    parser.add_argument(
        "--hallucination-retries",
        type=int,
        default=3,
        help="Max retries when a user simulator hallucination is detected (full-duplex only). Set to 0 to disable.",
    )


def main():
    parser = argparse.ArgumentParser(description="Tau2 command line interface")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a benchmark")
    add_run_args(run_parser)

    def run_command(args):
        user_persona_config = None
        if args.user_persona:
            user_persona_config = PersonaConfig.from_dict(args.user_persona)

        # Build audio-native config if enabled
        audio_native_config = None
        if args.audio_native:
            # Resolve model based on provider if not specified
            audio_native_model = args.audio_native_model
            if audio_native_model is None:
                audio_native_model = DEFAULT_AUDIO_NATIVE_MODELS[
                    args.audio_native_provider
                ]

            # Determine use_xml_prompt: defaults to False (plain text)
            use_xml_prompt = False
            if args.xml_prompt:
                use_xml_prompt = True

            audio_native_config = AudioNativeConfig(
                # Provider
                provider=args.audio_native_provider,
                model=audio_native_model,
                # Timing
                tick_duration_seconds=args.tick_duration,
                max_steps_seconds=args.max_steps_seconds,
                # Sample rates
                pcm_sample_rate=args.pcm_sample_rate,
                telephony_rate=args.telephony_rate,
                # Turn-taking thresholds
                wait_to_respond_threshold_other_seconds=args.wait_to_respond_other,
                wait_to_respond_threshold_self_seconds=args.wait_to_respond_self,
                yield_threshold_when_interrupted_seconds=args.yield_when_interrupted,
                yield_threshold_when_interrupting_seconds=args.yield_when_interrupting,
                interruption_check_interval_seconds=args.interruption_check_interval,
                integration_duration_seconds=args.integration_duration,
                silence_annotation_threshold_seconds=args.silence_annotation_threshold,
                # Agent behavior
                buffer_until_complete=not args.no_buffer_until_complete,
                fast_forward_mode=not args.no_fast_forward,
                send_audio_instant=not args.no_send_audio_instant,
                use_xml_prompt=use_xml_prompt,
            )

        # Set global LLM log mode (used by verbose logging)
        from tau2.utils.llm_utils import set_llm_log_mode

        set_llm_log_mode(args.llm_log_mode)

        return run_domain(
            RunConfig(
                domain=args.domain,
                task_set_name=args.task_set_name,
                task_split_name=args.task_split_name,
                task_ids=args.task_ids,
                num_tasks=args.num_tasks,
                agent=args.agent,
                llm_agent=args.agent_llm,
                llm_args_agent=args.agent_llm_args,
                user=args.user,
                llm_user=args.user_llm,
                llm_args_user=args.user_llm_args,
                num_trials=args.num_trials,
                max_steps=args.max_steps,
                max_errors=args.max_errors,
                save_to=args.save_to,
                max_concurrency=args.max_concurrency,
                seed=args.seed,
                log_level=args.log_level,
                user_persona_config=user_persona_config,
                enforce_communication_protocol=args.enforce_communication_protocol,
                speech_complexity=args.speech_complexity,
                audio_native_config=audio_native_config,
                verbose_logs=args.verbose_logs,
                audio_debug=getattr(args, "audio_debug", False),
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                auto_resume=args.auto_resume,
                auto_review=args.auto_review,
                review_mode=args.review_mode,
                hallucination_retries=args.hallucination_retries,
            )
        )

    run_parser.set_defaults(func=run_command)

    # Play command
    play_parser = subparsers.add_parser(
        "play", help="Play manual mode - interact with a domain as the agent"
    )
    play_parser.set_defaults(func=lambda args: run_manual_mode())

    # View command
    view_parser = subparsers.add_parser("view", help="View simulation results")
    view_parser.add_argument(
        "--dir",
        type=str,
        help="Directory containing simulation files. Defaults to data/simulations if not specified.",
    )
    view_parser.add_argument(
        "--file",
        type=str,
        help="Path to the simulation results file to view",
    )
    view_parser.add_argument(
        "--only-show-failed",
        action="store_true",
        help="Only show failed tasks.",
    )
    view_parser.add_argument(
        "--only-show-all-failed",
        action="store_true",
        help="Only show tasks that failed in all trials.",
    )
    view_parser.add_argument(
        "--expanded-ticks",
        action="store_true",
        help="Show expanded tick view instead of consolidated (for full-duplex simulations).",
    )
    view_parser.set_defaults(func=lambda args: run_view_simulations(args))

    # Domain command
    domain_parser = subparsers.add_parser("domain", help="Show domain documentation")
    domain_parser.add_argument(
        "domain",
        type=str,
        help="Name of the domain to show documentation for (e.g., 'airline', 'mock')",
    )
    domain_parser.set_defaults(func=lambda args: run_show_domain(args))

    # Start command
    start_parser = subparsers.add_parser("start", help="Start all servers")
    start_parser.set_defaults(func=lambda args: run_start_servers())

    # Check data command
    check_data_parser = subparsers.add_parser(
        "check-data", help="Check if data directory is properly configured"
    )
    check_data_parser.set_defaults(func=lambda args: run_check_data())

    # Evaluate trajectories command
    evaluate_parser = subparsers.add_parser(
        "evaluate-trajs", help="Evaluate trajectories and update rewards"
    )
    evaluate_parser.add_argument(
        "paths",
        nargs="+",
        help="Paths to trajectory files, directories, or glob patterns",
    )
    evaluate_parser.add_argument(
        "-o",
        "--output-dir",
        help="Directory to save updated trajectory files with recomputed rewards. If not provided, only displays metrics.",
    )
    evaluate_parser.set_defaults(func=lambda args: run_evaluate_trajectories(args))

    # Review command - LLM-based conversation review
    review_parser = subparsers.add_parser(
        "review", help="Run LLM-based conversation review on simulation results"
    )
    review_parser.add_argument(
        "path",
        help="Path to a results.json file or a directory containing results.json files",
    )
    review_parser.add_argument(
        "-m",
        "--mode",
        type=str,
        choices=["full", "user"],
        default="full",
        help="Review mode: 'full' (agent+user, default) or 'user' (user simulator only)",
    )
    review_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output path for the reviewed results (only used for single file)",
    )
    review_parser.add_argument(
        "--interruption-enabled",
        action="store_true",
        help="Flag indicating that interruption was enabled for these simulations",
    )
    review_parser.add_argument(
        "--show-details",
        action="store_true",
        help="Show detailed review results for each simulation",
    )
    review_parser.add_argument(
        "-c",
        "--max-concurrency",
        type=int,
        default=32,
        help="Maximum number of concurrent reviews (default: 32)",
    )
    review_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit review to first N simulations",
    )
    review_parser.add_argument(
        "--task-ids",
        type=str,
        nargs="+",
        default=None,
        help="Only review simulations for these task IDs",
    )
    review_parser.add_argument(
        "--log-llm",
        action="store_true",
        help="Log LLM request/response for each review call",
    )
    review_parser.set_defaults(func=lambda args: run_review(args))

    # Leaderboard command
    leaderboard_parser = subparsers.add_parser(
        "leaderboard", help="Show the tau2-bench leaderboard"
    )
    leaderboard_parser.add_argument(
        "--domain",
        "-d",
        type=str,
        choices=["retail", "airline", "telecom"],
        default=None,
        help="Show leaderboard for a specific domain. If not specified, shows overall leaderboard.",
    )
    leaderboard_parser.add_argument(
        "--metric",
        "-m",
        type=str,
        choices=["pass_1", "pass_2", "pass_3", "pass_4", "cost"],
        default="pass_1",
        help="Metric to rank by. Default is 'pass_1'.",
    )
    leaderboard_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Limit the number of entries to show.",
    )
    leaderboard_parser.set_defaults(func=lambda args: run_leaderboard(args))

    # Submit command with subcommands
    submit_parser = subparsers.add_parser(
        "submit", help="Submission management for the leaderboard"
    )
    submit_subparsers = submit_parser.add_subparsers(
        dest="submit_command", help="Submit subcommands", required=True
    )

    # Submit prepare subcommand
    submit_prepare_parser = submit_subparsers.add_parser(
        "prepare", help="Prepare a submission for the leaderboard"
    )
    submit_prepare_parser.add_argument(
        "input_paths",
        nargs="+",
        help="Paths to trajectory files, directories, or glob patterns",
    )
    submit_prepare_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory to save the submission and trajectories",
    )
    submit_prepare_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip trajectory verification step",
    )
    submit_prepare_parser.set_defaults(func=lambda args: run_prepare_submission(args))

    # Submit validate subcommand
    submit_validate_parser = submit_subparsers.add_parser(
        "validate", help="Validate an existing submission directory"
    )
    submit_validate_parser.add_argument(
        "submission_dir",
        help="Path to the submission directory to validate",
    )
    submit_validate_parser.add_argument(
        "--mode",
        type=VerificationMode,
        choices=[mode.value for mode in VerificationMode],
        default=VerificationMode.PUBLIC,
        help=f"Verification mode. Default is '{VerificationMode.PUBLIC.value}'",
    )
    submit_validate_parser.set_defaults(func=lambda args: run_validate_submission(args))

    # Submit verify-trajs subcommand
    submit_verify_parser = submit_subparsers.add_parser(
        "verify-trajs", help="Verify trajectory files"
    )
    submit_verify_parser.add_argument(
        "paths",
        nargs="+",
        help="Paths to trajectory files, directories, or glob patterns",
    )
    submit_verify_parser.add_argument(
        "--mode",
        type=VerificationMode,
        choices=[mode.value for mode in VerificationMode],
        default=VerificationMode.PUBLIC,
        help=f"Verification mode. Default is '{VerificationMode.PUBLIC.value}'",
    )
    submit_verify_parser.set_defaults(func=lambda args: run_verify_trajectories(args))

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return

    args.func(args)


def run_view_simulations(args):
    from tau2.scripts.view_simulations import main as view_main

    view_main(
        sim_file=args.file,
        only_show_failed=args.only_show_failed,
        only_show_all_failed=args.only_show_all_failed,
        sim_dir=args.dir,
        expanded_ticks=args.expanded_ticks,
    )


def run_show_domain(args):
    from tau2.scripts.show_domain_doc import main as domain_main

    domain_main(args.domain)


def run_start_servers():
    from tau2.scripts.start_servers import main as start_main

    start_main()


def run_check_data():
    from tau2.scripts.check_data import main as check_data_main

    check_data_main()


def run_verify_trajectories(args):
    import sys

    from loguru import logger

    from tau2.scripts.leaderboard.verify_trajectories import verify_trajectories

    logger.configure(handlers=[{"sink": sys.stderr, "level": "ERROR"}])

    verify_trajectories(args.paths, args.mode)


def run_evaluate_trajectories(args):
    import sys

    from loguru import logger

    from tau2.scripts.evaluate_trajectories import evaluate_trajectories

    logger.configure(handlers=[{"sink": sys.stderr, "level": "ERROR"}])

    evaluate_trajectories(args.paths, args.output_dir)


def run_review(args):
    """Run LLM-based conversation review."""
    import sys
    from pathlib import Path

    from loguru import logger
    from rich.console import Console

    from tau2.scripts.review_conversation import ReviewMode, find_results_files, review

    logger.configure(handlers=[{"sink": sys.stderr, "level": "WARNING"}])

    # Find all results files
    input_path = Path(args.path)
    results_files = find_results_files(input_path)

    if not results_files:
        console = Console()
        console.print(f"[red]No results.json files found in: {args.path}[/red]")
        sys.exit(1)

    # Run review for each results file
    mode = ReviewMode.FULL if args.mode == "full" else ReviewMode.USER
    console = Console()

    if len(results_files) > 1:
        console.print(
            f"\n📁 Found {len(results_files)} results files to review:",
            style="bold blue",
        )
        for i, rf in enumerate(results_files, 1):
            console.print(f"  {i}. {rf.parent.name}/results.json")
        console.print()

    for i, results_file in enumerate(results_files):
        if len(results_files) > 1:
            console.print(
                f"\n{'=' * 60}\n[bold cyan]Processing ({i + 1}/{len(results_files)}): {results_file.parent.name}[/bold cyan]\n{'=' * 60}"
            )

        review(
            results_path=str(results_file),
            mode=mode,
            output_path=args.output if len(results_files) == 1 else None,
            interruption_enabled=args.interruption_enabled,
            show_details=args.show_details,
            max_concurrency=args.max_concurrency,
            limit=args.limit,
            task_ids=args.task_ids,
            log_llm=args.log_llm,
        )


def run_prepare_submission(args):
    """Run the prepare submission command."""
    from tau2.scripts.leaderboard.prepare_submission import prepare_submission

    prepare_submission(
        input_paths=args.input_paths,
        output_dir=args.output,
        run_verification=not args.no_verify,
    )


def run_validate_submission(args):
    """Run the validate submission command."""
    from tau2.scripts.leaderboard.prepare_submission import validate_submission

    validate_submission(submission_dir=args.submission_dir, mode=args.mode)


def run_manual_mode():
    from tau2.scripts.manual_mode import main as manual_main

    manual_main()


def run_leaderboard(args):
    """Show the tau2-bench leaderboard."""
    from tau2.scripts.leaderboard.leaderboard import show_leaderboard

    show_leaderboard(
        domain=args.domain,
        metric=args.metric,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
