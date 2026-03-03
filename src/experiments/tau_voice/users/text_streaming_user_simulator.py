"""
Text-based full-duplex user simulator (experimental).

Extracted from tau2.user.user_simulator_streaming when text streaming agents
were moved to experiments/tau_voice/. The production voice streaming user
simulator (VoiceStreamingUserSimulator) remains in tau2.
"""

from typing import List, Optional, Tuple

from loguru import logger

from experiments.tau_voice.utils.text_chunking import TextChunkingMixin
from tau2.agent.base.llm_config import LLMConfigMixin
from tau2.agent.base.streaming import (
    LinearizationStrategy,
    ListenerReactionDecision,
    TurnTakingAction,
    basic_turn_taking_policy,
    merge_homogeneous_chunks,
)
from tau2.data_model.message import (
    AssistantMessage,
    EnvironmentMessage,
    Message,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from tau2.data_model.persona import InterruptTendency, PersonaConfig
from tau2.environment.tool import Tool
from tau2.user.user_simulator import SYSTEM_PROMPT, get_global_user_sim_guidelines
from tau2.user.user_simulator_base import (
    OUT_OF_SCOPE,
    STOP,
    TRANSFER,
    FullDuplexUser,
    ValidUserInputMessage,
)
from tau2.user.user_simulator_streaming import (
    UserStreamingState,
    user_backchannel_policy,
    user_interruption_policy,
)
from tau2.utils.llm_utils import generate
from tau2.utils.utils import get_now


class UserTextChunkingMixin(
    TextChunkingMixin[ValidUserInputMessage, UserMessage, UserStreamingState]
):
    """
    User-specific text chunking mixin.

    This is a specialization of TextChunkingMixin for users with text-based chunking.
    """


class TextStreamingUserSimulator(
    UserTextChunkingMixin,
    LLMConfigMixin,
    FullDuplexUser[UserStreamingState],
):
    """
    Full-duplex LLM-based user simulator with text-based streaming.

    Inherits from:
    - UserTextChunkingMixin: Provides text chunking and streaming logic
    - LLMConfigMixin: Provides LLM configuration (llm, llm_args, set_seed)
    - FullDuplexUser: Provides full-duplex streaming interface

    Features:
    - Enhanced tool call handling (tool calls are never chunked)
    - Custom turn-taking logic (responds immediately by default)
    - Proper state typing with UserStreamingState

    Usage:
        user = TextStreamingUserSimulator(
            instructions="You are a customer with a complaint",
            llm="gpt-4",
            chunk_by="words",  # "chars", "words", or "sentences"
            chunk_size=8
        )

        # FULL_DUPLEX mode
        state = user.get_init_state()  # Returns UserStreamingState
        chunk, state = user.get_next_chunk(state, incoming_chunk)
    """

    def __init__(
        self,
        instructions: Optional[str] = None,
        llm: Optional[str] = None,
        llm_args: Optional[dict] = None,
        tools: Optional[List[Tool]] = None,
        chunk_by: str = "words",
        chunk_size: int = 1,
        wait_to_respond_threshold_other: int = 2,
        wait_to_respond_threshold_self: int = 4,
        yield_threshold_when_interrupted: Optional[int] = 2,
        yield_threshold_when_interrupting: Optional[int] = None,
        backchannel_min_threshold: Optional[int] = None,
        backchannel_max_threshold: Optional[int] = None,
        backchannel_poisson_rate: Optional[float] = None,
        use_llm_backchannel: bool = True,
        interruption_check_interval: Optional[int] = None,
        integration_ticks: int = 1,
        silence_annotation_threshold_ticks: Optional[int] = None,
        tick_duration_seconds: Optional[float] = None,
        persona_config: Optional[PersonaConfig] = None,
    ):
        """
        Initialize the streaming user simulator.

        Args:
            instructions: Instructions for the user simulator
            llm: LLM model name
            llm_args: Additional LLM arguments
            tools: Optional tools the user can call
            chunk_by: Chunking strategy - "chars", "words", or "sentences"
            chunk_size: Number of units per chunk
            wait_to_respond_threshold_other: Minimum time to wait since OTHER (agent) last spoke before generating a response.
                Both this AND wait_to_respond_threshold_self must be satisfied.
            wait_to_respond_threshold_self: Minimum time to wait since SELF (user) last spoke before generating a response.
                Both this AND wait_to_respond_threshold_other must be satisfied.
            yield_threshold_when_interrupted: How long user keeps speaking when agent interrupts user. If None, cannot be interrupted.
            yield_threshold_when_interrupting: How long user keeps speaking when user interrupts agent. If None, uses yield_threshold_when_interrupted.
            backchannel_min_threshold: Min threshold for backchanneling (ticks). If None and using Poisson, cannot backchannel.
            backchannel_max_threshold: Max threshold for backchanneling (ticks). Used with Poisson policy.
            backchannel_poisson_rate: Poisson rate for backchanneling (events/second). Used with Poisson policy.
            use_llm_backchannel: If True, use LLM-based backchannel policy. If False, use Poisson-based policy.
            interruption_check_interval: If set, only check for interruption every N ticks. Useful to reduce callback frequency.
            integration_ticks: Number of consecutive silent ticks before an overlap region ends
                during linearization. Higher values are more tolerant of brief pauses. Default is 1.
            silence_annotation_threshold_ticks: If set, add silence annotations to conversation history
                when both parties are silent for more than this many ticks. Requires tick_duration_seconds.
            tick_duration_seconds: Duration of each tick in seconds. Required for silence annotations.
            persona_config: Runtime persona configuration for user behavior (e.g., verbosity level, interrupt tendency)
        """
        # Initialize mixin and base class
        super().__init__(
            instructions=instructions,
            llm=llm,
            llm_args=llm_args,
            tools=tools,
            chunk_by=chunk_by,
            chunk_size=chunk_size,
        )

        self.persona_config = persona_config or PersonaConfig()
        self.integration_ticks = integration_ticks
        self.silence_annotation_threshold_ticks = silence_annotation_threshold_ticks
        self.tick_duration_seconds = tick_duration_seconds

        # Enable user-initiated interruption based on persona config
        if persona_config is not None and persona_config.interrupt_tendency is not None:
            # Enable user-initiated interruption for users with INTERRUPTS tendency
            self.enable_user_initiated_interruption = (
                persona_config.interrupt_tendency == InterruptTendency.INTERRUPTS
            )
        else:
            # No persona config or interrupt_tendency is None
            self.enable_user_initiated_interruption = False

        self.wait_to_respond_threshold_other = wait_to_respond_threshold_other
        self.wait_to_respond_threshold_self = wait_to_respond_threshold_self
        self.yield_threshold_when_interrupted = yield_threshold_when_interrupted
        self.yield_threshold_when_interrupting = yield_threshold_when_interrupting
        self.backchannel_min_threshold = backchannel_min_threshold
        self.backchannel_max_threshold = backchannel_max_threshold
        self.backchannel_poisson_rate = backchannel_poisson_rate
        self.use_llm_backchannel = use_llm_backchannel
        self.interruption_check_interval = interruption_check_interval

        # Default yield_threshold_when_interrupting to yield_threshold_when_interrupted if not set
        if (
            self.yield_threshold_when_interrupting is None
            and self.yield_threshold_when_interrupted is not None
        ):
            self.yield_threshold_when_interrupting = (
                self.yield_threshold_when_interrupted
            )
            logger.info(
                f"yield_threshold_when_interrupting not set, defaulting to yield_threshold_when_interrupted={self.yield_threshold_when_interrupted}"
            )
        self.validate_turn_taking_settings()

    def validate_turn_taking_settings(self) -> None:
        """Validate the turn-taking settings."""
        if (
            self.yield_threshold_when_interrupted is not None
            and self.yield_threshold_when_interrupted < 2
        ):
            raise ValueError(
                f"yield_threshold_when_interrupted must be at least 2. Got {self.yield_threshold_when_interrupted}. Setting it lower will result in unstable behavior."
            )
        if (
            self.yield_threshold_when_interrupting is not None
            and self.yield_threshold_when_interrupting < 2
        ):
            raise ValueError(
                f"yield_threshold_when_interrupting must be at least 2. Got {self.yield_threshold_when_interrupting}. Setting it lower will result in unstable behavior."
            )

    @property
    def global_simulation_guidelines(self) -> str:
        """The simulation guidelines for the user simulator."""
        use_tools = self.tools is not None
        return get_global_user_sim_guidelines(use_tools=use_tools)

    @property
    def system_prompt(self) -> str:
        """The system prompt for the user simulator."""
        if self.instructions is None:
            logger.warning("No instructions provided for user simulator")

        guidelines = self.global_simulation_guidelines

        # Check if persona config adds any guidelines
        persona_guidelines = self.persona_config.to_guidelines_text()
        if persona_guidelines is None:
            persona_guidelines = ""
        if persona_guidelines:
            persona_guidelines = f"\n\n{persona_guidelines}\n"
        guidelines_with_persona = guidelines.replace(
            "<PERSONA_GUIDELINES>", persona_guidelines
        )

        system_prompt = SYSTEM_PROMPT.format(
            global_user_sim_guidelines_with_persona=guidelines_with_persona,
            instructions=self.instructions,
        )
        return system_prompt

    @classmethod
    def is_stop(cls, message: UserMessage) -> bool:
        """Check if the message is a stop message."""
        if message.is_tool_call():
            return False
        # Audio-only messages (chunks) don't have text content
        if message.content is None:
            return False
        return (
            STOP in message.content
            or TRANSFER in message.content
            or OUT_OF_SCOPE in message.content
        )

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> UserStreamingState:
        """
        Get the initial state of the streaming user.

        Args:
            message_history: The message history of the conversation.

        Returns:
            The initial state of the streaming user (UserStreamingState).
        """
        if message_history is None:
            message_history = []

        return UserStreamingState(
            system_messages=[SystemMessage(role="system", content=self.system_prompt)],
            messages=message_history,
            input_turn_taking_buffer=[],
            output_streaming_queue=[],
        )

    def speech_detection(self, chunk: Optional[ValidUserInputMessage]) -> bool:
        """
        Check if the chunk is a speech chunk.
        """
        if not isinstance(chunk, AssistantMessage):
            return False
        # Check contains_speech flag - defaults to True for backward compatibility if not set
        return chunk.contains_speech if chunk.contains_speech is not None else True

    def _next_turn_taking_action(self, state: UserStreamingState) -> TurnTakingAction:
        """
        Decide the next action to take in the turn-taking.
        Returns:
            The next action to take in the turn-taking.
        """
        logger.debug(
            f"Applying turn-taking action to user simulator state: {state.info}"
        )
        # Prepare listener reaction callbacks
        should_interrupt_callback = None
        should_backchannel_callback = None
        integration_ticks = self.integration_ticks

        # Interruption callback is tied to persona's interrupt tendency
        if self.enable_user_initiated_interruption:

            def should_interrupt_callback(
                s: UserStreamingState,
            ) -> ListenerReactionDecision:
                return user_interruption_policy(s, integration_ticks=integration_ticks)

        # Backchannel callback is tied to the use_llm_backchannel config
        if self.use_llm_backchannel:

            def should_backchannel_callback(
                s: UserStreamingState,
            ) -> ListenerReactionDecision:
                return user_backchannel_policy(s, integration_ticks=integration_ticks)

        action, info = basic_turn_taking_policy(
            state=state,
            yield_threshold_when_interrupted=self.yield_threshold_when_interrupted,
            yield_threshold_when_interrupting=self.yield_threshold_when_interrupting,
            wait_to_respond_threshold_other=self.wait_to_respond_threshold_other,
            wait_to_respond_threshold_self=self.wait_to_respond_threshold_self,
            backchannel_min_threshold=self.backchannel_min_threshold,
            backchannel_max_threshold=self.backchannel_max_threshold,
            backchannel_poisson_rate=self.backchannel_poisson_rate,
            tick_duration_seconds=self.tick_duration_seconds,
            should_interrupt_callback=should_interrupt_callback,
            should_backchannel_callback=should_backchannel_callback,
            use_llm_backchannel=self.use_llm_backchannel,
            listener_reaction_check_interval=self.interruption_check_interval,
        )
        logger.debug(f"USER SIMULATOR TURN-TAKING ACTION: {action}. Reason: {info}")

        # Extract timing/cost metadata from state (set by basic_turn_taking_policy)
        timing = getattr(state, "_listener_reaction_timing", None) or {}

        return TurnTakingAction(
            action=action,
            info=info,
            interrupt_check_seconds=timing.get("interrupt_check_seconds"),
            interrupt_check_cost=timing.get("interrupt_check_cost"),
            interrupt_check_usage=timing.get("interrupt_check_usage"),
            backchannel_check_seconds=timing.get("backchannel_check_seconds"),
            backchannel_check_cost=timing.get("backchannel_check_cost"),
            backchannel_check_usage=timing.get("backchannel_check_usage"),
        )

    def _perform_turn_taking_action(
        self, state: UserStreamingState, action: TurnTakingAction
    ) -> Tuple[UserMessage, UserStreamingState]:
        """
        Perform the next action in the turn-taking.

        Note: Chunk recording in tick-based history is handled by get_next_chunk()
        in the StreamingMixin, not here. This method just produces the chunk
        and manages pending buffers.

        Args:
            state: The current state of the turn-taking.
            action: The action to perform.
        Returns:
            A tuple of the next chunk and the updated state.
        """
        logger.debug(f"Performing turn-taking action: {action}")
        next_user_chunk = None
        is_speech_action = False
        if action.action == "keep_talking":
            next_user_chunk = state.output_streaming_queue.pop(0)
            next_user_chunk.timestamp = get_now()
            is_speech_action = True
            # Clear flags when queue is empty
            if len(state.output_streaming_queue) == 0:
                if state.is_backchanneling:
                    state.is_backchanneling = False
                    logger.debug("Backchannel complete")
                if state.delivering_tool_result_speech:
                    state.delivering_tool_result_speech = False
                    logger.debug("Tool result speech delivery complete")
        elif action.action == "stop_talking":
            state.output_streaming_queue = []
            state.is_backchanneling = False
        elif action.action == "generate_message":
            merged_message = merge_homogeneous_chunks(state.input_turn_taking_buffer)
            full_message, new_state = self._generate_full_duplex_message(
                merged_message, state
            )
            state.input_turn_taking_buffer = []
            if full_message.is_tool_call():
                full_message.turn_taking_action = action
                return full_message, new_state
            else:
                chunk_messages = self._create_chunk_messages(full_message)
                state.output_streaming_queue.extend(chunk_messages)
                next_user_chunk = state.output_streaming_queue.pop(0)
                next_user_chunk.timestamp = get_now()
                is_speech_action = True
        elif action.action == "wait":
            pass
        elif action.action == "backchannel":
            backchannel_message = self._generate_backchannel_message()
            chunk_messages = self._create_chunk_messages(backchannel_message)
            state.output_streaming_queue.extend(chunk_messages)
            next_user_chunk = state.output_streaming_queue.pop(0)
            next_user_chunk.timestamp = get_now()
            is_speech_action = True
            # Mark that we're delivering a backchannel (prevents interruption)
            state.is_backchanneling = True
            # Reset backchannel cooldown timer
            state.ticks_since_last_backchannel = 0
        else:
            raise ValueError(f"Invalid action: {action}")
        if is_speech_action:
            next_user_chunk.contains_speech = True
            state.time_since_last_talk = 0
        else:
            state.time_since_last_talk += 1
        if next_user_chunk is None:
            next_user_chunk = UserMessage(
                role="user",
                content=None,
                cost=0.0,
                usage=None,
                raw_data=None,
                chunk_id=0,
                is_final_chunk=True,
                contains_speech=False,
            )
        next_user_chunk.turn_taking_action = action
        return next_user_chunk, state

    def _process_tool_result(
        self,
        tool_result: EnvironmentMessage,
        state: UserStreamingState,
    ) -> Tuple[UserMessage, UserStreamingState]:
        """Process a tool result by calling the LLM and returning the response."""
        saved_buffer = state.input_turn_taking_buffer
        state.input_turn_taking_buffer = [tool_result]

        full_message, state = self._generate_full_duplex_message(tool_result, state)

        state.input_turn_taking_buffer = saved_buffer

        if full_message.is_tool_call():
            logger.debug("Tool result processing: LLM returned another tool call")
            return full_message, state
        elif self.is_stop(full_message):
            logger.debug("Tool result processing: stop message detected")
            return full_message, state
        else:
            logger.debug("Tool result processing: queuing speech chunks")
            chunk_messages = self._create_chunk_messages(full_message)
            state.output_streaming_queue.extend(chunk_messages)
            state.delivering_tool_result_speech = True
            waiting_chunk, state = self._emit_waiting_chunk(state)
            return waiting_chunk, state

    def _emit_waiting_chunk(
        self, state: UserStreamingState
    ) -> Tuple[UserMessage, UserStreamingState]:
        """Emit an empty chunk while waiting for tool results."""
        state.time_since_last_talk += 1
        chunk = UserMessage(
            role="user",
            content=None,
            cost=0.0,
            usage=None,
            raw_data=None,
            chunk_id=0,
            is_final_chunk=True,
            contains_speech=False,
        )
        return chunk, state

    def _generate_full_duplex_message(
        self, message: ValidUserInputMessage, state: UserStreamingState
    ) -> Tuple[UserMessage, UserStreamingState]:
        """
        Generate a message using tick-based history for LLM context.

        This method linearizes the tick history to build the LLM context,
        rather than using the legacy messages list. This properly handles
        the concurrent nature of full-duplex communication.

        Note: User simulator flips roles when calling LLM (it acts as if it's
        the assistant, receiving messages from the "user" which is actually
        the agent).

        Args:
            message: The incoming message to respond to.
            state: The current streaming state with tick history.

        Returns:
            A tuple of the user message and updated state.
        """
        # Build LLM context from linearized ticks (including current pending input)
        linearized_messages = state.get_linearized_messages(
            strategy=LinearizationStrategy.CONTAINMENT_AWARE,
            include_pending_input=True,
            indicate_current_incomplete=True,
            integration_ticks=self.integration_ticks,
            silence_annotation_threshold_ticks=self.silence_annotation_threshold_ticks,
            tick_duration_seconds=self.tick_duration_seconds,
        )

        # Check that last message is a valid user input message
        if not isinstance(linearized_messages[-1], (ValidUserInputMessage)):
            if isinstance(linearized_messages[-1], SystemMessage):
                # SystemMessage at end is expected (e.g., silence annotations)
                logger.debug(
                    "Running user generation with SystemMessage as last message (e.g., silence annotation)"
                )
            else:
                logger.warning(
                    f"Last message is not a valid user input message: {type(linearized_messages[-1]).__name__}"
                )

        if isinstance(linearized_messages[-1], (AssistantMessage)):
            if linearized_messages[-1].content is None:
                logger.warning(
                    f"Last message is an assistant message with no content: {linearized_messages[-1]}"
                )

        # Flip roles for user simulator (it sees itself as assistant)
        flipped_messages = self._flip_roles_for_llm(linearized_messages)

        # Build full message list with system messages
        messages = state.system_messages + flipped_messages

        # Add a role identity reminder as a system message to help the LLM stay in character
        role_reminder = SystemMessage(
            role="system",
            content="REMINDER: You are the CUSTOMER calling for help. Respond as the customer would - with questions, requests, or information about your issue. Do NOT respond as the customer service agent.",
        )
        messages = messages + [role_reminder]

        # Generate response
        assistant_message = generate(
            model=self.llm,
            messages=messages,
            tools=self.tools,
            call_name="user_streaming_response",
            **self.llm_args,
        )

        # Convert assistant response to user message
        user_message = UserMessage(
            role="user",
            content=assistant_message.content,
            cost=assistant_message.cost,
            usage=assistant_message.usage,
            raw_data=assistant_message.raw_data,
        )

        my_str = ""
        for message in linearized_messages:
            my_str += f"{message.role}: {message.content}\n"

        logger.info(
            f"USER SIMULATOR:\nSent to LLM:\n{my_str}\nReceived from LLM:\n{user_message.content}\n\n\n"
        )

        # Flip the requestor of tool calls
        if assistant_message.tool_calls is not None:
            user_message.tool_calls = []
            for tool_call in assistant_message.tool_calls:
                user_message.tool_calls.append(
                    ToolCall(
                        id=tool_call.id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                        requestor="user",
                    )
                )

        return user_message, state

    def _flip_roles_for_llm(self, messages: list[Message]) -> list[Message]:
        """
        Flip message roles for user simulator LLM context.

        The user simulator acts as an assistant internally, so:
        - UserMessage (what user said) -> AssistantMessage (what "I" said)
        - AssistantMessage (what agent said) -> UserMessage (what "they" said)
        - ToolMessage for user -> kept as-is (user's tool results)
        - SystemMessage -> kept as-is (e.g., silence annotations)

        Args:
            messages: The linearized message history.

        Returns:
            Messages with roles flipped for LLM consumption.
        """
        from tau2.data_model.message import SystemMessage, ToolMessage

        flipped = []
        for msg in messages:
            if isinstance(msg, UserMessage):
                # User's message -> becomes assistant response
                flipped.append(
                    AssistantMessage(
                        role="assistant",
                        tool_calls=msg.tool_calls,
                        content=msg.content,
                    )
                )
            elif isinstance(msg, AssistantMessage):
                # Agent's message -> becomes user input
                # Skip tool calls and messages without text content
                # (audio-only messages can't be converted to text UserMessage)
                if not msg.is_tool_call() and msg.content:
                    flipped.append(
                        UserMessage(
                            role="user",
                            content=msg.content,
                        )
                    )
            elif isinstance(msg, ToolMessage):
                # Tool messages for user are kept
                if msg.requestor == "user":
                    flipped.append(
                        ToolMessage(
                            id=msg.id,
                            role=msg.role,
                            content=msg.content,
                        )
                    )
            elif isinstance(msg, SystemMessage):
                # System messages are kept as-is (e.g., silence annotations)
                flipped.append(msg)
        return flipped

    def _generate_backchannel_message(
        self,
    ) -> UserMessage:
        """
        Generate a backchannel message.
        """
        user_message = UserMessage(
            role="user",
            content="uh-huh",
            cost=0.0,
            usage=None,
            raw_data=None,
            chunk_id=0,
            is_final_chunk=True,
        )
        return user_message
