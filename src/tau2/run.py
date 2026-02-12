import json
import multiprocessing
import os
import random
import tempfile
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Optional

from loguru import logger

from tau2.agent.discrete_time_audio_native_agent import DiscreteTimeAudioNativeAgent
from tau2.agent.llm_agent import LLMAgent, LLMGTAgent, LLMSoloAgent
from tau2.data_model.persona import InterruptTendency, PersonaConfig, Verbosity
from tau2.data_model.simulation import (
    AgentInfo,
    AudioNativeConfig,
    HallucinationCheck,
    Info,
    Results,
    RunConfig,
    SimulationRun,
    TerminationReason,
    UserInfo,
)
from tau2.data_model.tasks import Task
from tau2.data_model.voice import SpeechEnvironment, SynthesisConfig, VoiceSettings
from tau2.environment.environment import EnvironmentInfo
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.evaluator.reviewer import check_hallucination
from tau2.gym.gym_agent import GymAgent
from tau2.metrics.agent_metrics import compute_metrics
from tau2.orchestrator.full_duplex_orchestrator import FullDuplexOrchestrator
from tau2.orchestrator.modes import CommunicationMode
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.registry import RegistryInfo, registry
from tau2.user.user_simulator import (
    DummyUser,
    UserSimulator,
    get_global_user_sim_guidelines,
    get_global_user_sim_guidelines_voice,
)
from tau2.user.user_simulator_streaming import VoiceStreamingUserSimulator
from tau2.user_simulation_voice_presets import (
    COMPLEXITY_CONFIGS,
    SpeechComplexity,
    get_or_load_task_voice_config,
    sample_voice_config,
)
from tau2.utils.display import ConsoleDisplay, Text
from tau2.utils.llm_utils import set_llm_log_dir
from tau2.utils.pydantic_utils import get_pydantic_hash
from tau2.utils.utils import DATA_DIR, get_commit_hash, get_now, show_dict_diff
from tau2.voice.synthesis.conversation_builder import generate_simulation_audio
from tau2.voice.utils.audio_debug import generate_audio_debug_info

# Context variable to track current simulation_id for log filtering
# This ensures task-specific log handlers only receive their own messages
_current_simulation_id: ContextVar[Optional[str]] = ContextVar(
    "_current_simulation_id", default=None
)


def create_speech_environment(
    seed: int,
    user_voice_settings: Optional[VoiceSettings] = None,
    complexity: SpeechComplexity = "regular",
) -> Optional[SpeechEnvironment]:
    """Create a SpeechEnvironment with seeded random selections.

    Also updates user_voice_settings.synthesis_config with merged effect configs.
    For full control over merged configs, use sample_voice_config() directly.

    Args:
        seed: Random seed for reproducibility.
        user_voice_settings: Voice settings for the user (mutated with merged configs).
        complexity: Speech environment complexity level ("control", "regular").
    """
    if not user_voice_settings or not user_voice_settings.synthesis_enabled:
        return None

    sampled = sample_voice_config(
        seed=seed,
        synthesis_config=user_voice_settings.synthesis_config,
        complexity=complexity,
    )

    # Update synthesis_config with merged effect configs
    user_voice_settings.synthesis_config.channel_effects_config = (
        sampled.channel_effects_config
    )
    user_voice_settings.synthesis_config.source_effects_config = (
        sampled.source_effects_config
    )
    user_voice_settings.synthesis_config.speech_effects_config = (
        sampled.speech_effects_config
    )

    return sampled.to_speech_environment(seed)


def _format_hallucination_feedback(
    hallucination_check: "HallucinationCheck",
) -> Optional[str]:
    """Format hallucination errors into feedback for the user simulator.

    Returns a string to append to user instructions, or None if no hallucinations.
    """
    if not hallucination_check.errors:
        return None

    error_lines = []
    for error in hallucination_check.errors:
        if error.correct_behavior:
            error_lines.append(f"- [hallucination] {error.correct_behavior}")
        else:
            error_lines.append(f"- [hallucination] {error.reasoning[:200]}")

    if not error_lines:
        return None

    return (
        "IMPORTANT: In a previous attempt at this conversation, the user simulator "
        "made these errors. You MUST avoid repeating them:\n" + "\n".join(error_lines)
    )


def run_auto_review(
    simulation: SimulationRun,
    task: Task,
    review_mode: str,
    user: str,
    llm_user: Optional[str],
    llm_args_user: Optional[dict],
    user_persona_config: Optional[PersonaConfig],
    user_voice_settings: Optional[VoiceSettings],
    policy: str,
    is_audio_native: bool,
) -> None:
    """
    Run LLM conversation review on a simulation and attach results.

    Args:
        simulation: The completed simulation to review.
        task: The task specification.
        review_mode: "full" (agent+user) or "user" (user only).
        user: User implementation name.
        llm_user: LLM used by user simulator.
        llm_args_user: LLM args for user simulator.
        user_persona_config: Persona config for user.
        user_voice_settings: Voice settings for user.
        policy: Environment policy string.
        is_audio_native: Whether audio-native mode was used.
    """
    from tau2.evaluator.reviewer import ReviewMode, review_simulation

    review_mode_enum = ReviewMode.FULL if review_mode == "full" else ReviewMode.USER

    # Get global guidelines for review context
    if is_audio_native:
        review_guidelines = get_global_user_sim_guidelines_voice()
    else:
        review_guidelines = get_global_user_sim_guidelines()

    # Build user_info for review context
    review_user_info = UserInfo(
        implementation=user,
        llm=llm_user,
        llm_args=llm_args_user,
        global_simulation_guidelines=review_guidelines,
        persona_config=user_persona_config,
        voice_settings=user_voice_settings,
    )

    logger.info(f"Starting review for task {task.id} (mode: {review_mode})...")

    review_result, auth_result = review_simulation(
        simulation=simulation,
        task=task,
        mode=review_mode_enum,
        user_info=review_user_info,
        policy=policy,
        interruption_enabled=is_audio_native,
    )

    # Attach review to simulation
    if review_mode == "full":
        simulation.review = review_result
        simulation.auth_classification = auth_result
    else:
        simulation.user_only_review = review_result

    logger.info(
        f"Review completed for task {task.id}: has_errors={review_result.has_errors}"
    )


def save_simulation_audio(
    simulation: SimulationRun,
    task: Task,
    simulation_id: str,
    save_dir: Path,
    audio_native_config: AudioNativeConfig,
    audio_debug: bool = False,
) -> None:
    """
    Save audio files for an audio-native simulation.

    Args:
        simulation: The completed simulation.
        task: The task specification.
        simulation_id: Unique simulation ID.
        save_dir: Base directory for saving files.
        audio_native_config: Audio-native configuration.
        audio_debug: Whether to generate debug audio analysis.
    """
    task_audio_dir = (
        save_dir / "tasks" / f"task_{task.id}" / f"sim_{simulation_id}" / "audio"
    )
    task_audio_dir.mkdir(parents=True, exist_ok=True)

    # Generate audio debug info BEFORE serialization (while audio_content is in memory)
    # This must happen before generate_simulation_audio for proper analysis
    if audio_debug:
        try:
            debug_dir = task_audio_dir / "debug"
            report = generate_audio_debug_info(
                simulation,
                debug_dir,
                save_per_tick_audio_files=True,
                save_silence=True,  # Save all ticks for alignment analysis
                tick_duration_ms=audio_native_config.tick_duration_ms,
            )
            logger.info(
                f"Audio debug info saved to: {debug_dir} "
                f"(agent: {report.agent_ticks_with_audio}, user: {report.user_ticks_with_audio} ticks)"
            )
            if report.warnings:
                logger.warning(
                    f"Audio analysis found {len(report.warnings)} warning(s)"
                )
        except Exception as e:
            logger.warning(f"Failed to generate audio debug info: {e}")

    try:
        generate_simulation_audio(simulation, task_audio_dir)
        logger.debug(f"Audio saved to: {task_audio_dir}")
    except Exception as e:
        logger.warning(f"Failed to save audio for task {task.id}: {e}")


def get_options() -> RegistryInfo:
    """
    Returns options for the simulator.
    """
    return registry.get_info()


def get_environment_info(
    domain_name: str, include_tool_info: bool = False
) -> EnvironmentInfo:
    """Get information about the environment for a registered Domain"""
    global registry
    env_constructor = registry.get_env_constructor(domain_name)
    return env_constructor().get_info(include_tool_info=include_tool_info)


def load_task_splits(task_set_name: str) -> Optional[dict[str, list[str]]]:
    """
    Loads the task splits for the given domain.
    """
    global registry
    task_split_loader = registry.get_task_splits_loader(task_set_name)
    if task_split_loader is None:
        return None
    return task_split_loader()


def load_tasks(task_set_name: str, task_split_name: Optional[str] = None) -> list[Task]:
    """
    Loads the tasks for the given domain.
    """
    global registry
    task_loader = registry.get_tasks_loader(task_set_name)
    tasks = task_loader(task_split_name=task_split_name)
    return tasks


def get_tasks(
    task_set_name: str,
    task_split_name: Optional[str] = None,
    task_ids: Optional[list[str]] = None,
    num_tasks: Optional[int] = None,
) -> list[Task]:
    """
    Loads the tasks for the given domain.
    """
    if task_ids is None:
        tasks = load_tasks(task_set_name=task_set_name, task_split_name=task_split_name)
    else:
        tasks = [
            task
            for task in load_tasks(
                task_set_name=task_set_name, task_split_name=task_split_name
            )
            if task.id in task_ids
        ]
    if task_ids is not None and len(tasks) != len(task_ids):
        missing_tasks = set(task_ids) - set([task.id for task in tasks])
        raise ValueError(
            f"Not all tasks were found for task set {task_set_name} - {task_split_name}: {missing_tasks}"
        )
    if num_tasks is not None:
        tasks = tasks[:num_tasks]
    return tasks


def make_run_name(config: RunConfig) -> str:
    """
    Make a run name from the run config
    """
    # Use effective agent/user for audio-native mode
    effective_agent = config.get_effective_agent()
    effective_user = config.get_effective_user()

    # For audio-native mode, use the audio-native model name instead of llm_agent
    if config.is_audio_native:
        llm_agent_name = (
            f"{config.audio_native_config.provider}-{config.audio_native_config.model}"
        )
    else:
        llm_agent_name = config.llm_agent
    clean_llm_agent_name = [x for x in llm_agent_name.split("/") if x][-1]
    agent_name = f"{effective_agent}_{clean_llm_agent_name}"

    clean_llm_user_name = [x for x in config.llm_user.split("/") if x][-1]
    user_name = f"{effective_user}_{clean_llm_user_name}"

    name = (
        f"{get_now(use_compact_format=True)}_{config.domain}_{agent_name}_{user_name}"
    )

    # Add audio-native suffix if enabled
    if config.is_audio_native:
        name = f"{name}_audio_native"

    return name


def run_domain(config: RunConfig) -> Results:
    """
    Run simulations for a domain
    """
    config.validate()
    ConsoleDisplay.display_run_config(config)
    if config.task_set_name is None:
        task_set_name = config.domain
    else:
        task_set_name = config.task_set_name
    tasks = get_tasks(
        task_set_name=task_set_name,
        task_split_name=config.task_split_name,
        task_ids=config.task_ids,
        num_tasks=config.num_tasks,
    )

    # Get effective agent/user (handles audio-native mode)
    effective_agent = config.get_effective_agent()
    effective_user = config.get_effective_user()
    effective_max_steps = config.get_effective_max_steps()

    if "gt" in effective_agent:  # TODO: Clean up!
        total_num_tasks = len(tasks)
        tasks = [task for task in tasks if LLMGTAgent.check_valid_task(task)]
        num_tasks = len(tasks)
        console_text = Text(
            text=f"Running {num_tasks} out of {total_num_tasks} tasks for GT agent.",
            style="bold green",
        )
        ConsoleDisplay.console.print(console_text)
    if "solo" in effective_agent:  # TODO: Clean up!
        total_num_tasks = len(tasks)
        tasks = [task for task in tasks if LLMSoloAgent.check_valid_task(task)]
        num_tasks = len(tasks)
        console_text = Text(
            text=f"Running {num_tasks} out of {total_num_tasks} tasks for solo agent.",
            style="bold green",
        )
        ConsoleDisplay.console.print(console_text)

    num_trials = config.num_trials
    run_name = config.save_to
    if run_name is None:
        run_name = make_run_name(config)
    save_dir = DATA_DIR / "simulations" / run_name
    save_path = save_dir / "results.json"
    simulation_results = run_tasks(
        domain=config.domain,
        tasks=tasks,
        agent=effective_agent,
        user=effective_user,
        llm_agent=config.llm_agent,
        llm_args_agent=config.llm_args_agent,
        llm_user=config.llm_user,
        llm_args_user=config.llm_args_user,
        num_trials=num_trials,
        max_steps=effective_max_steps,
        max_errors=config.max_errors,
        save_to=save_path,
        save_dir=save_dir,
        console_display=True,
        evaluation_type=EvaluationType.ALL_WITH_NL_ASSERTIONS,  # TODO: Reset to ALL when done.
        max_concurrency=config.max_concurrency,
        seed=config.seed,
        log_level=config.log_level,
        enforce_communication_protocol=config.enforce_communication_protocol,
        speech_complexity=config.speech_complexity,
        audio_native_config=config.audio_native_config,
        verbose_logs=config.verbose_logs,
        max_retries=config.max_retries,
        retry_delay=config.retry_delay,
        auto_resume=config.auto_resume,
        auto_review=config.auto_review,
        review_mode=config.review_mode,
        hallucination_retries=config.hallucination_retries,
    )
    metrics = compute_metrics(simulation_results)
    ConsoleDisplay.display_agent_metrics(metrics)

    return simulation_results


def run_tasks(
    domain: str,
    tasks: list[Task],
    agent: str,
    user: str,
    llm_agent: Optional[str] = None,
    llm_args_agent: Optional[dict] = None,
    llm_user: Optional[str] = None,
    llm_args_user: Optional[dict] = None,
    num_trials: int = 1,
    max_steps: int = 100,
    max_errors: int = 10,
    save_to: Optional[str | Path] = None,
    save_dir: Optional[Path] = None,
    console_display: bool = True,
    evaluation_type: EvaluationType = EvaluationType.ALL,
    max_concurrency: int = 1,
    seed: Optional[int] = 300,
    log_level: Optional[str] = "INFO",
    enforce_communication_protocol: bool = False,
    speech_complexity: SpeechComplexity = "regular",
    audio_native_config: Optional[AudioNativeConfig] = None,
    verbose_logs: bool = False,
    audio_debug: bool = False,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    auto_resume: bool = False,
    auto_review: bool = False,
    review_mode: str = "full",
    hallucination_retries: int = 0,
) -> Results:
    """
    Runs tasks for a given domain.
    If llm_as_judge is True, the LLM will be used to annotate the simulation run.
    Calculates the reward for the simulation run.
    Args:
        domain (str): The domain to run the simulation on.
        tasks (list[Task]): The tasks to run.
        agent (str): The agent to run the simulation on.
        user (str): The user to run the simulation on.
        llm_agent (str): The model to use for the agent.
        llm_args_agent (dict): The arguments to pass to the LLM for the agent.
        llm_user (str): The model to use for the user.
        llm_args_user (dict): The arguments to pass to the LLM for the user.
        max_steps (int): The maximum number of steps to run the simulation.
        max_errors (int): The maximum number of errors to allow in the simulation.
        save_to (str | Path): The path to json file where to save the simulation results.
        evaluation_type (EvaluationType): The type of evaluation to use.
        max_concurrency (int): The maximum number of concurrent simulations to run.
        seed (int): The seed to use for the simulation.
        log_level (str): The log level to use.
        enforce_communication_protocol (bool): Whether to enforce communication protocol rules.
        speech_complexity (SpeechComplexity): Speech environment complexity level.
        audio_native_config (AudioNativeConfig): Configuration for audio-native mode.
        audio_debug (bool): Enable audio debugging (per-tick audio files and analysis).
        auto_resume (bool): Automatically resume from existing save file without prompting.
        hallucination_retries (int): Max retries on user simulator hallucinations (full-duplex only).
    Returns:
        The simulation results.
    """
    if isinstance(save_to, str):
        save_to = Path(save_to)
    # Set log level from config
    logger.remove()
    logger.add(lambda msg: print(msg), level=log_level)
    if len(tasks) == 0:
        raise ValueError("No tasks to run")
    if num_trials <= 0:
        raise ValueError("Number of trials must be greater than 0")
    if max_steps <= 0:
        raise ValueError("Max steps must be greater than 0")
    if max_errors <= 0:
        raise ValueError("Max errors must be greater than 0")

    random.seed(seed)

    seeds = [random.randint(0, 1000000) for _ in range(num_trials)]
    if "seed" in llm_args_agent:
        logger.warning("Each trial will modify the seed for the agent")

    if "seed" in llm_args_user:
        logger.warning("Each trial will modify the seed for the user")

    lock = multiprocessing.Lock()

    # Create run-level voice settings and persona config for audio-native mode
    user_voice_settings = None
    user_persona_config = None
    if audio_native_config is not None:
        # Base voice settings (speech_environment is per-task, set in run_task)
        user_voice_settings = VoiceSettings(
            transcription_config=None,
            synthesis_config=SynthesisConfig(),
        )

        # Persona config from complexity preset
        complexity_config = COMPLEXITY_CONFIGS[speech_complexity]
        user_persona_config = PersonaConfig(
            verbosity=Verbosity(complexity_config["verbosity"]),
            interrupt_tendency=InterruptTendency(
                complexity_config["interrupt_tendency"]
            ),
        )

    info = get_info(
        domain=domain,
        agent=agent,
        user=user,
        llm_agent=llm_agent,
        llm_args_agent=llm_args_agent,
        llm_user=llm_user,
        llm_args_user=llm_args_user,
        num_trials=num_trials,
        max_steps=max_steps,
        max_errors=max_errors,
        seed=seed,
        user_persona_config=user_persona_config,
        user_voice_settings=user_voice_settings,
        audio_native_config=audio_native_config,
        speech_complexity=speech_complexity if audio_native_config else None,
    )
    simulation_results = Results(
        info=info,
        tasks=tasks,
        simulations=[],
    )
    done_runs = set()
    if save_to is not None:
        # If save_to already exists, check if the user wants to resume the run.
        if save_to.exists():
            if auto_resume:
                # Auto-resume without prompting
                response = "y"
            else:
                response = (
                    ConsoleDisplay.console.input(
                        "[yellow]File [bold]{}[/bold] already exists. Do you want to resume the run? (y/n)[/yellow] ".format(
                            save_to
                        )
                    )
                    .lower()
                    .strip()
                )
            if response != "y":
                raise FileExistsError(
                    f"File {save_to} already exists. Please delete it or use a different save_to name."
                )
            with open(save_to, "r") as fp:
                prev_simulation_results = Results.model_validate_json(fp.read())
                # Check if the run config has changed
                if get_pydantic_hash(prev_simulation_results.info) != get_pydantic_hash(
                    simulation_results.info
                ):
                    diff = show_dict_diff(
                        prev_simulation_results.info.model_dump(),
                        simulation_results.info.model_dump(),
                    )
                    if auto_resume:
                        # Log the diff but continue without prompting
                        logger.warning(
                            f"Run config has changed, continuing with auto-resume:\n{diff}"
                        )
                        response = "y"
                    else:
                        ConsoleDisplay.console.print(
                            f"The run config has changed.\n\n{diff}\n\nDo you want to resume the run? (y/n)"
                        )
                        response = (
                            ConsoleDisplay.console.input(
                                "[yellow]File [bold]{}[/bold] already exists. Do you want to resume the run? (y/n)[/yellow] ".format(
                                    save_to
                                )
                            )
                            .lower()
                            .strip()
                        )
                    if response != "y":
                        raise ValueError(
                            "The run config has changed. Please delete the existing file or use a different save_to name."
                        )
                # Check if the task set is compatible (superset allowed, modifications not)
                prev_tasks_by_id = {t.id: t for t in prev_simulation_results.tasks}
                new_tasks_by_id = {t.id: t for t in simulation_results.tasks}

                # Check that all previous tasks are still present and unchanged
                modified_tasks = []
                removed_tasks = []
                for task_id, prev_task in prev_tasks_by_id.items():
                    if task_id not in new_tasks_by_id:
                        removed_tasks.append(task_id)
                    elif get_pydantic_hash(prev_task) != get_pydantic_hash(
                        new_tasks_by_id[task_id]
                    ):
                        modified_tasks.append(task_id)

                if removed_tasks:
                    raise ValueError(
                        f"Tasks were removed from the task set: {removed_tasks}. "
                        "Please delete the existing file or use a different save_to name."
                    )
                if modified_tasks:
                    raise ValueError(
                        f"Tasks were modified: {modified_tasks}. "
                        "Please delete the existing file or use a different save_to name."
                    )

                # Identify new tasks being added
                added_task_ids = set(new_tasks_by_id.keys()) - set(
                    prev_tasks_by_id.keys()
                )
                if added_task_ids:
                    logger.info(
                        f"Adding {len(added_task_ids)} new tasks to the run: {sorted(added_task_ids)}"
                    )
                # Check which of the runs have already been done successfully
                # Exclude infrastructure failures so they can be retried
                done_runs = set(
                    [
                        (sim.trial, sim.task_id, sim.seed)
                        for sim in prev_simulation_results.simulations
                        if sim.termination_reason
                        != TerminationReason.INFRASTRUCTURE_ERROR
                    ]
                )
                # Remove infrastructure failure simulations so they can be replaced
                prev_simulation_results.simulations = [
                    sim
                    for sim in prev_simulation_results.simulations
                    if sim.termination_reason != TerminationReason.INFRASTRUCTURE_ERROR
                ]

                # Merge tasks: keep previous tasks and add any new ones
                if added_task_ids:
                    new_tasks_to_add = [
                        t for t in simulation_results.tasks if t.id in added_task_ids
                    ]
                    prev_simulation_results.tasks = (
                        list(prev_simulation_results.tasks) + new_tasks_to_add
                    )
                    # Update the tasks variable to include all tasks for the run loop
                    tasks = prev_simulation_results.tasks

                    # Re-save the file with updated tasks list
                    # This is needed because _save() only appends simulations, not tasks
                    with open(save_to, "w") as fp:
                        fp.write(prev_simulation_results.model_dump_json(indent=2))
                    logger.info(
                        f"Updated results file with {len(added_task_ids)} new tasks"
                    )

                simulation_results = prev_simulation_results
                console_text = Text(
                    text=f"Resuming run from {len(done_runs)} runs. {len(tasks) * num_trials - len(done_runs)} runs remaining.",
                    style="bold yellow",
                )
                ConsoleDisplay.console.print(console_text)
        # Create new save file
        else:
            # Check if save_to exists and create parent directories if needed
            if not save_to.parent.exists():
                save_to.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Saving simulation batch to {save_to}")
            with open(save_to, "w") as fp:
                fp.write(simulation_results.model_dump_json(indent=2))

    def _save(simulation: SimulationRun):
        if save_to is None:
            return
        with lock:
            with open(save_to, "r") as fp:
                ckpt = json.load(fp)
            # Check if this simulation already exists (prevents duplicates from race conditions)
            # A simulation is uniquely identified by (trial, task_id, seed)
            existing_keys = {
                (sim.get("trial"), sim.get("task_id"), sim.get("seed"))
                for sim in ckpt["simulations"]
            }
            sim_key = (simulation.trial, simulation.task_id, simulation.seed)
            if sim_key in existing_keys:
                logger.warning(
                    f"Skipping duplicate save for task {simulation.task_id}, "
                    f"trial {simulation.trial}, seed {simulation.seed}"
                )
                return
            ckpt["simulations"].append(simulation.model_dump())
            # Atomic write: write to temp file, then rename
            # This prevents corruption if process crashes mid-write or file is read mid-write
            fd, tmp_path = tempfile.mkstemp(
                suffix=".json", prefix=".results_", dir=save_to.parent
            )
            try:
                with os.fdopen(fd, "w") as fp:
                    json.dump(ckpt, fp, indent=2)
                os.replace(tmp_path, save_to)  # Atomic on POSIX
            except Exception:
                # Clean up temp file if something goes wrong
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

    def _run(task: Task, trial: int, seed: int, progress_str: str) -> SimulationRun:
        console_text = Text(
            text=f"{progress_str}. Running task {task.id}, trial {trial + 1}",
            style="bold green",
        )
        ConsoleDisplay.console.print(console_text)

        # Retry logic - only retry on exceptions
        max_attempts = max_retries + 1  # +1 for the initial attempt
        last_exception = None
        last_error_reason = ""
        last_traceback = ""

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    retry_text = Text(
                        text=f"  🔄 Retry {attempt}/{max_retries} for task {task.id}: {last_error_reason}",
                        style="yellow",
                    )
                    ConsoleDisplay.console.print(retry_text)
                    time.sleep(retry_delay)

                simulation = run_task(
                    domain=domain,
                    task=task,
                    agent=agent,
                    user=user,
                    llm_agent=llm_agent,
                    llm_args_agent=llm_args_agent,
                    llm_user=llm_user,
                    llm_args_user=llm_args_user,
                    max_steps=max_steps,
                    max_errors=max_errors,
                    evaluation_type=evaluation_type,
                    seed=seed,
                    save_dir=save_dir,
                    enforce_communication_protocol=enforce_communication_protocol,
                    speech_complexity=speech_complexity,
                    audio_native_config=audio_native_config,
                    user_voice_settings=user_voice_settings,
                    user_persona_config=user_persona_config,
                    verbose_logs=verbose_logs,
                    audio_debug=audio_debug,
                    auto_review=auto_review,
                    review_mode=review_mode,
                )
                simulation.trial = trial

                # Hallucination retry: if hallucination check detects fabricated info, re-run
                is_full_duplex = (
                    simulation.ticks is not None and len(simulation.ticks) > 0
                )
                if hallucination_retries > 0 and is_full_duplex:
                    hallucination_retry_count = 0
                    while hallucination_retry_count < hallucination_retries:
                        # Run focused hallucination check
                        h_check = check_hallucination(simulation, task)
                        simulation.hallucination_check = h_check

                        if not h_check.hallucination_found:
                            break

                        hallucination_retry_count += 1
                        n_errors = len(h_check.errors)

                        retry_text = Text(
                            text=f"  ⚠️  Hallucination detected on task {task.id} ({n_errors} instance(s)). "
                            f"Re-running with feedback ({hallucination_retry_count}/{hallucination_retries})...",
                            style="yellow",
                        )
                        ConsoleDisplay.console.print(retry_text)

                        # Save the discarded run to a shared Results file for tau2 view
                        if save_dir is not None:
                            discarded_dir = save_dir / "hallucination_discarded"
                            discarded_dir.mkdir(parents=True, exist_ok=True)
                            discarded_path = discarded_dir / "results.json"

                            # Append to existing discarded results file, or create new one
                            if discarded_path.exists():
                                with open(discarded_path, "r") as fp:
                                    discarded_data = json.load(fp)
                                discarded_data["simulations"].append(
                                    simulation.model_dump(mode="json")
                                )
                                # Add task if not already present
                                existing_task_ids = {
                                    t["id"] for t in discarded_data["tasks"]
                                }
                                if task.id not in existing_task_ids:
                                    discarded_data["tasks"].append(
                                        task.model_dump(mode="json")
                                    )
                                with open(discarded_path, "w") as fp:
                                    json.dump(discarded_data, fp, indent=2)
                            else:
                                discarded_results = Results(
                                    info=simulation_results.info,
                                    tasks=[
                                        t
                                        for t in simulation_results.tasks
                                        if t.id == task.id
                                    ],
                                    simulations=[simulation],
                                )
                                with open(discarded_path, "w") as fp:
                                    fp.write(
                                        discarded_results.model_dump_json(indent=2)
                                    )

                            logger.info(
                                f"Saved discarded hallucination run to {discarded_path} "
                                f"(task {task.id}, retry {hallucination_retry_count})"
                            )

                        # Build feedback for the user simulator
                        feedback = _format_hallucination_feedback(h_check)

                        # Re-run with a different seed (and optionally feedback)
                        retry_seed = seed + hallucination_retry_count * 1000
                        simulation = run_task(
                            domain=domain,
                            task=task,
                            agent=agent,
                            user=user,
                            llm_agent=llm_agent,
                            llm_args_agent=llm_args_agent,
                            llm_user=llm_user,
                            llm_args_user=llm_args_user,
                            max_steps=max_steps,
                            max_errors=max_errors,
                            evaluation_type=evaluation_type,
                            seed=retry_seed,
                            save_dir=save_dir,
                            enforce_communication_protocol=enforce_communication_protocol,
                            speech_complexity=speech_complexity,
                            audio_native_config=audio_native_config,
                            user_voice_settings=user_voice_settings,
                            user_persona_config=user_persona_config,
                            verbose_logs=verbose_logs,
                            audio_debug=audio_debug,
                            auto_review=auto_review,
                            review_mode=review_mode,
                            hallucination_feedback=feedback,
                        )
                        simulation.trial = trial

                    simulation.hallucination_retries_used = hallucination_retry_count

                if console_display:
                    ConsoleDisplay.display_simulation(simulation, show_details=False)
                _save(simulation)

                if attempt > 0:
                    success_text = Text(
                        text=f"  ✅ Task {task.id} succeeded on retry {attempt}",
                        style="green",
                    )
                    ConsoleDisplay.console.print(success_text)

                return simulation

            except Exception as e:
                last_exception = e
                last_error_reason = str(e)
                last_traceback = traceback.format_exc()  # Capture while in except block
                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Task {task.id} failed (attempt {attempt + 1}/{max_attempts}): {e}"
                    )
                else:
                    logger.error(
                        f"Task {task.id} failed after {max_attempts} attempts: {e}"
                    )

        # All retries exhausted - return a failed simulation instead of raising
        # This allows the batch to continue with other tasks
        error_text = Text(
            text=f"  ❌ Task {task.id} failed permanently after {max_attempts} attempts: {last_error_reason}",
            style="bold red",
        )
        ConsoleDisplay.console.print(error_text)

        now = get_now()
        failed_simulation = SimulationRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            timestamp=now,
            start_time=now,
            end_time=now,
            duration=0.0,
            termination_reason=TerminationReason.INFRASTRUCTURE_ERROR,
            messages=[],
            trial=trial,
            seed=seed,
            info={
                "error": str(last_exception),
                "error_type": type(last_exception).__name__,
                "error_traceback": last_traceback,
                "failed_after_attempts": max_attempts,
            },
        )
        _save(failed_simulation)
        return failed_simulation

    args = []
    for trial in range(num_trials):
        for i, task in enumerate(tasks):
            if (trial, task.id, seeds[trial]) in done_runs:
                console_text = Text(
                    text=f"Skipping task {task.id}, trial {trial} because it has already been run.",
                    style="bold yellow",
                )
                ConsoleDisplay.console.print(console_text)
                continue
            progress_str = f"{i}/{len(tasks)} (trial {trial + 1}/{num_trials})"
            args.append((task, trial, seeds[trial], progress_str))

    # Track running tasks for status display
    running_tasks: dict[str, dict] = {}  # task_id -> {start_time, trial}
    running_tasks_lock = threading.Lock()
    # Include skipped (already completed) tasks in counts
    total_count = len(tasks) * num_trials
    completed_count = len(done_runs)  # Start with already-completed tasks
    stop_status_monitor = threading.Event()

    def status_monitor():
        """Print status every 30 seconds."""
        while not stop_status_monitor.wait(timeout=30.0):
            with running_tasks_lock:
                running_count = len(running_tasks)
                if running_count == 0:
                    continue
                now = time.time()
                task_statuses = []
                for task_id, info in running_tasks.items():
                    elapsed = now - info["start_time"]
                    task_statuses.append(f"{task_id}({elapsed:.0f}s)")

                # Calculate average reward from completed simulations
                reward_str = ""
                if completed_count > 0:
                    rewards = [
                        sim.reward_info.reward
                        for sim in simulation_results.simulations
                        if sim.reward_info is not None
                    ]
                    if rewards:
                        avg_reward = sum(rewards) / len(rewards)
                        reward_str = f"Avg reward: {avg_reward:.2f} (N={len(rewards)})"

                status_text = Text(
                    text=f"📊 Status: {completed_count}/{total_count} complete. {reward_str}. "
                    f"{running_count} running: {', '.join(task_statuses[:10])}"
                    + (f" +{running_count - 10} more" if running_count > 10 else ""),
                    style="cyan",
                )
                ConsoleDisplay.console.print(status_text)

    def _run_with_tracking(
        task: Task, trial: int, seed: int, progress_str: str
    ) -> SimulationRun:
        """Wrapper that tracks task start/end for status display."""
        task_key = f"{task.id}.{trial}"
        with running_tasks_lock:
            running_tasks[task_key] = {"start_time": time.time(), "trial": trial}
        try:
            return _run(task, trial, seed, progress_str)
        finally:
            with running_tasks_lock:
                running_tasks.pop(task_key, None)

    # Start status monitor thread
    status_thread = threading.Thread(target=status_monitor, daemon=True)
    status_thread.start()

    try:
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            # Submit all tasks and collect futures
            futures = {executor.submit(_run_with_tracking, *arg): arg for arg in args}
            # Process results as they complete
            for future in as_completed(futures):
                result = future.result()
                simulation_results.simulations.append(result)
                completed_count += 1
    finally:
        stop_status_monitor.set()
        status_thread.join(timeout=1.0)

    ConsoleDisplay.console.print(
        "\n✨ [bold green]Successfully completed all simulations![/bold green]\n"
        "To review the simulations, run: [bold blue]tau2 view[/bold blue]"
    )
    return simulation_results


def run_task(
    domain: str,
    task: Task,
    agent: str,
    user: str,
    llm_agent: Optional[str] = None,
    llm_args_agent: Optional[dict] = None,
    llm_user: Optional[str] = None,
    llm_args_user: Optional[dict] = None,
    max_steps: int = 100,
    max_errors: int = 10,
    evaluation_type: EvaluationType = EvaluationType.ALL,
    seed: Optional[int] = None,
    save_dir: Optional[Path] = None,
    enforce_communication_protocol: bool = False,
    speech_complexity: SpeechComplexity = "regular",
    audio_native_config: Optional[AudioNativeConfig] = None,
    user_voice_settings: Optional[VoiceSettings] = None,
    user_persona_config: Optional[PersonaConfig] = None,
    verbose_logs: bool = False,
    audio_debug: bool = False,
    auto_review: bool = False,
    review_mode: str = "full",
    hallucination_feedback: Optional[str] = None,
) -> SimulationRun:
    """
    Runs a single task simulation.

    Args:
        domain: The domain to run the simulation on.
        task: The task to run.
        agent: The agent implementation to use.
        user: The user implementation to use.
        llm_agent: The model to use for the agent.
        llm_args_agent: The arguments to pass to the LLM for the agent.
        llm_user: The model to use for the user.
        llm_args_user: The arguments to pass to the LLM for the user.
        max_steps: The maximum number of steps to run the simulation.
        max_errors: The maximum number of errors to allow in the simulation.
        evaluation_type: The type of evaluation to use.
        seed: The seed to use for the simulation.
        enforce_communication_protocol: Whether to enforce communication protocol rules.
        speech_complexity: Speech complexity level for audio effects.
        audio_native_config: Configuration for audio-native mode.
        user_voice_settings: Base voice settings for user (run-level). Deep copied and
            extended with per-task speech_environment. If None, created with defaults.
        user_persona_config: Persona config for user (run-level). If None, derived from
            speech_complexity.
        verbose_logs: Enable verbose logging (per-task logs, ticks, etc.).
        audio_debug: Enable audio debugging. Saves per-tick audio files and analysis
            report for diagnosing timing issues. Only works for audio-native mode.

    Returns:
        The simulation run.
    """
    if max_steps <= 0:
        raise ValueError("Max steps must be greater than 0")
    if max_errors <= 0:
        raise ValueError("Max errors must be greater than 0")
    global registry
    logger.info(
        f"STARTING SIMULATION: Domain: {domain}, Task: {task.id}, Agent: {agent}, User: {user}"
    )
    environment_constructor = registry.get_env_constructor(domain)
    environment = environment_constructor()

    # Generate simulation ID early for consistent directory structure
    simulation_id = str(uuid.uuid4())

    # Set up task-specific log directory (always computed if save_dir exists)
    task_log_handler_id = None
    task_log_dir = None
    if save_dir:
        task_log_dir = save_dir / "tasks" / f"task_{task.id}" / f"sim_{simulation_id}"
        task_log_dir.mkdir(parents=True, exist_ok=True)

    # Set up verbose logging handler if enabled
    if verbose_logs and task_log_dir:
        # Set the context variable for this simulation
        # This is used by the filter to ensure only this simulation's logs go to this file
        _current_simulation_id.set(simulation_id)

        # Create a filter that only accepts messages from this simulation
        # The filter captures simulation_id by value at definition time
        def make_simulation_filter(sim_id: str):
            def simulation_filter(record):
                return _current_simulation_id.get() == sim_id

            return simulation_filter

        # Add task-specific log file handler with filter
        log_file_path = task_log_dir / "task.log"
        task_log_handler_id = logger.add(
            log_file_path,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            rotation=None,  # No rotation for task-specific logs
            enqueue=True,  # Thread-safe logging
            filter=make_simulation_filter(
                simulation_id
            ),  # Only accept this simulation's logs
        )
        logger.debug(f"Task log file: {log_file_path}")

    # Set up LLM debug log directory for this simulation (inside task/sim directory)
    # Only enable LLM debug logging when verbose logging is explicitly requested
    if task_log_dir and verbose_logs:
        llm_log_dir = task_log_dir / "llm_debug"
        set_llm_log_dir(llm_log_dir)
        # LLM log mode is set globally via context variable before run starts

    try:
        user_tools = environment.get_user_tools()
    except Exception:
        user_tools = None

    solo_mode = False

    # Handle audio-native mode (full-duplex voice with DiscreteTimeAudioNativeAgent)
    if audio_native_config is not None:
        # Use provided voice settings or create defaults
        if user_voice_settings is not None:
            # Deep copy to avoid mutating run-level settings
            task_voice_settings = deepcopy(user_voice_settings)
        else:
            # Fallback: create default voice settings
            task_voice_settings = VoiceSettings(
                transcription_config=None,
                synthesis_config=SynthesisConfig(),
            )

        # Get voice config for this task (from pre-sampled file or sample on the fly)
        # Seed calculation: base_seed + hash(task.id) % 1000000
        task_seed = (seed or 42) + hash(task.id) % 1000000
        sampled_voice_config = get_or_load_task_voice_config(
            domain=domain,
            task_id=task.id,
            task_seed=task_seed,
            complexity=speech_complexity,
            synthesis_config=task_voice_settings.synthesis_config,
        )

        # Update synthesis_config with merged effect configs (complexity overrides applied)
        task_voice_settings.synthesis_config.channel_effects_config = (
            sampled_voice_config.channel_effects_config
        )
        task_voice_settings.synthesis_config.source_effects_config = (
            sampled_voice_config.source_effects_config
        )
        task_voice_settings.synthesis_config.speech_effects_config = (
            sampled_voice_config.speech_effects_config
        )

        # Set speech environment on task voice settings and local variable for simulation
        speech_environment = sampled_voice_config.to_speech_environment(task_seed)
        task_voice_settings.speech_environment = speech_environment

        # Use provided persona config or use the one from sampled config
        if user_persona_config is None:
            user_persona_config = sampled_voice_config.persona_config

        # Create DiscreteTimeAudioNativeAgent
        agent_instance = DiscreteTimeAudioNativeAgent(
            tools=environment.get_tools(),
            domain_policy=environment.get_policy(),
            tick_duration_ms=audio_native_config.tick_duration_ms,
            modality="audio",
            send_audio_instant=audio_native_config.send_audio_instant,
            buffer_until_complete=audio_native_config.buffer_until_complete,
            fast_forward_mode=audio_native_config.fast_forward_mode,
            provider=audio_native_config.provider,
            model=audio_native_config.model,
            use_xml_prompt=audio_native_config.use_xml_prompt,
        )

        # Create VoiceStreamingUserSimulator
        user_instructions = str(task.user_scenario)
        if hallucination_feedback:
            user_instructions += f"\n\n{hallucination_feedback}"
        user_instance = VoiceStreamingUserSimulator(
            tools=user_tools,
            instructions=user_instructions,
            llm=llm_user,
            llm_args=llm_args_user,
            voice_settings=task_voice_settings,
            chunk_size=audio_native_config.user_chunk_size,
            wait_to_respond_threshold_other=audio_native_config.wait_to_respond_threshold_other_ticks,
            wait_to_respond_threshold_self=audio_native_config.wait_to_respond_threshold_self_ticks,
            yield_threshold_when_interrupted=audio_native_config.yield_threshold_when_interrupted_ticks,
            yield_threshold_when_interrupting=audio_native_config.yield_threshold_when_interrupting_ticks,
            backchannel_min_threshold=(
                int(
                    sampled_voice_config.backchannel_min_threshold
                    / audio_native_config.tick_duration_seconds
                )
                if sampled_voice_config.backchannel_min_threshold is not None
                else None
            ),
            backchannel_max_threshold=audio_native_config.backchannel_max_threshold_ticks,
            backchannel_poisson_rate=audio_native_config.backchannel_poisson_rate,
            use_llm_backchannel=sampled_voice_config.use_llm_backchannel,
            interruption_check_interval=audio_native_config.interruption_check_interval_ticks,
            integration_ticks=audio_native_config.integration_ticks,
            silence_annotation_threshold_ticks=audio_native_config.silence_annotation_threshold_ticks,
            tick_duration_seconds=audio_native_config.tick_duration_seconds,
            persona_config=user_persona_config,
        )

        # Use FullDuplexOrchestrator for audio-native mode
        orchestrator = FullDuplexOrchestrator(
            domain=domain,
            agent=agent_instance,
            user=user_instance,
            environment=environment,
            task=task,
            max_steps=max_steps,
            max_errors=max_errors,
            seed=seed,
            simulation_id=simulation_id,
            tick_duration_seconds=audio_native_config.tick_duration_seconds,
        )
    else:
        # Standard half-duplex mode
        AgentConstructor = registry.get_agent_constructor(agent)
        UserConstructor = registry.get_user_constructor(user)

        # Create agent based on type
        if issubclass(AgentConstructor, LLMAgent):
            agent_instance = AgentConstructor(
                tools=environment.get_tools(),
                domain_policy=environment.get_policy(),
                llm=llm_agent,
                llm_args=llm_args_agent,
            )
        elif issubclass(AgentConstructor, LLMGTAgent):
            agent_instance = AgentConstructor(
                tools=environment.get_tools(),
                domain_policy=environment.get_policy(),
                llm=llm_agent,
                llm_args=llm_args_agent,
                task=task,
            )
        elif issubclass(AgentConstructor, LLMSoloAgent):
            solo_mode = True
            environment = environment_constructor(solo_mode=True)
            user_tools = environment.get_user_tools() if environment.user_tools else []
            agent_instance = AgentConstructor(
                tools=environment.get_tools() + user_tools,
                domain_policy=environment.get_policy(),
                llm=llm_agent,
                llm_args=llm_args_agent,
                task=task,
            )
        elif issubclass(AgentConstructor, GymAgent):
            agent_instance = AgentConstructor(
                tools=environment.get_tools(),
                domain_policy=environment.get_policy(),
            )
        else:
            raise ValueError(
                f"Unknown agent type: {AgentConstructor}. Should be LLMAgent, LLMGTAgent, LLMSoloAgent, or GymAgent"
            )

        # Create user based on type
        if issubclass(UserConstructor, DummyUser):
            assert isinstance(agent_instance, LLMSoloAgent), (
                "Dummy user can only be used with solo agent"
            )

        user_instructions = str(task.user_scenario)
        if hallucination_feedback:
            user_instructions += f"\n\n{hallucination_feedback}"
        user_kwargs = {
            "tools": user_tools,
            "instructions": user_instructions,
            "llm": llm_user,
            "llm_args": llm_args_user,
        }
        if issubclass(UserConstructor, UserSimulator):
            user_kwargs["persona_config"] = user_persona_config

        user_instance = UserConstructor(**user_kwargs)

        # Use standard Orchestrator for half-duplex mode
        orchestrator = Orchestrator(
            domain=domain,
            agent=agent_instance,
            user=user_instance,
            environment=environment,
            task=task,
            max_steps=max_steps,
            max_errors=max_errors,
            seed=seed,
            solo_mode=solo_mode,
            simulation_id=simulation_id,
            validate_communication=enforce_communication_protocol,
        )

    try:
        simulation = orchestrator.run()

        # Determine communication mode for evaluation
        eval_mode = (
            CommunicationMode.FULL_DUPLEX
            if audio_native_config is not None
            else CommunicationMode.HALF_DUPLEX
        )

        reward_info = evaluate_simulation(
            domain=domain,
            task=task,
            simulation=simulation,
            evaluation_type=evaluation_type,
            solo_mode=solo_mode,
            mode=eval_mode,
        )

        simulation.reward_info = reward_info
        # Note: speech_environment is already set by the orchestrator from user.voice_settings

        # Auto-review: run LLM conversation review if enabled
        if auto_review:
            run_auto_review(
                simulation=simulation,
                task=task,
                review_mode=review_mode,
                user=user,
                llm_user=llm_user,
                llm_args_user=llm_args_user,
                user_persona_config=user_persona_config,
                user_voice_settings=user_voice_settings,
                policy=environment.get_policy(),
                is_audio_native=audio_native_config is not None,
            )

        # Always save audio for audio-native mode (regardless of verbose_logs)
        if audio_native_config is not None and save_dir:
            save_simulation_audio(
                simulation=simulation,
                task=task,
                simulation_id=simulation_id,
                save_dir=save_dir,
                audio_native_config=audio_native_config,
                audio_debug=audio_debug,
            )

        logger.info(
            f"FINISHED SIMULATION: Domain: {domain}, Task: {task.id}, Agent: {agent_instance.__class__.__name__}, User: {user_instance.__class__.__name__}. Reward: {reward_info.reward}"
        )
        return simulation

    finally:
        # Clear the LLM log directory context for this simulation
        if save_dir:
            set_llm_log_dir(None)

        # Remove task-specific log handler and clear context
        if task_log_handler_id is not None:
            logger.remove(task_log_handler_id)
            _current_simulation_id.set(None)


def get_info(
    domain: str,
    agent: str,
    user: str,
    llm_agent: Optional[str] = None,
    llm_args_agent: Optional[dict] = None,
    llm_user: Optional[str] = None,
    llm_args_user: Optional[dict] = None,
    num_trials: int = 1,
    max_steps: int = 100,
    max_errors: int = 10,
    seed: Optional[int] = None,
    user_persona_config: Optional[PersonaConfig] = None,
    user_voice_settings: Optional[VoiceSettings] = None,
    audio_native_config: Optional[AudioNativeConfig] = None,
    speech_complexity: Optional[SpeechComplexity] = None,
) -> Info:
    """Create Info object for storing run configuration.

    Args:
        domain: Domain name.
        agent: Agent implementation name.
        user: User implementation name.
        llm_agent: LLM model for agent.
        llm_args_agent: LLM arguments for agent.
        llm_user: LLM model for user.
        llm_args_user: LLM arguments for user.
        num_trials: Number of trials.
        max_steps: Maximum steps per simulation.
        max_errors: Maximum errors allowed.
        seed: Random seed.
        user_persona_config: Persona config for user (verbosity, interrupt tendency).
        user_voice_settings: Voice settings for user (synthesis config, etc.).
        audio_native_config: Configuration for audio-native mode.
        speech_complexity: Speech complexity level (control/regular).
    """
    # Use voice guidelines for audio-native mode
    if audio_native_config is not None:
        global_user_sim_guidelines = get_global_user_sim_guidelines_voice()
    else:
        global_user_sim_guidelines = get_global_user_sim_guidelines()

    user_info = UserInfo(
        implementation=user,
        llm=llm_user,
        llm_args=llm_args_user,
        global_simulation_guidelines=global_user_sim_guidelines,
        persona_config=user_persona_config,
        voice_settings=user_voice_settings,
    )

    # For audio-native mode, agent uses Realtime API, not a regular LLM
    if audio_native_config is not None:
        agent_llm = f"{audio_native_config.provider}:{audio_native_config.model}"
        agent_llm_args = None  # Realtime API config is in audio_native_config
    else:
        agent_llm = llm_agent
        agent_llm_args = llm_args_agent

    agent_info = AgentInfo(
        implementation=agent,
        llm=agent_llm,
        llm_args=agent_llm_args,
    )
    environment_info = get_environment_info(
        domain, include_tool_info=False
    )  # NOTE: Not saving tool info to avoid clutter.

    return Info(
        git_commit=get_commit_hash(),
        num_trials=num_trials,
        max_steps=max_steps,
        max_errors=max_errors,
        user_info=user_info,
        agent_info=agent_info,
        environment_info=environment_info,
        seed=seed,
        speech_complexity=speech_complexity,
        audio_native_config=audio_native_config,
    )
