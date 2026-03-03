from typing import List, Optional, Tuple

from loguru import logger

from experiments.tau_voice.utils.text_chunking import TextChunkingMixin
from tau2.agent.base.llm_config import LLMConfigMixin
from tau2.agent.base.streaming import (
    AudioChunkingMixin,
    LinearizationStrategy,
    StreamingState,
    basic_turn_taking_policy,
    merge_homogeneous_chunks,
)
from tau2.agent.base.voice import VoiceMixin, VoiceState
from tau2.agent.base_agent import (
    FullDuplexAgent,
    FullDuplexVoiceAgent,
    ValidAgentInputMessage,
)
from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT, LLMAgentState
from tau2.data_model.audio import TELEPHONY_SAMPLE_RATE
from tau2.data_model.message import (
    AssistantMessage,
    EnvironmentMessage,
    Message,
    TurnTakingAction,
    UserMessage,
)
from tau2.data_model.voice import VoiceSettings
from tau2.environment.tool import Tool
from tau2.utils.llm_utils import generate
from tau2.utils.utils import get_now
from tau2.voice.synthesis.audio_effects import BackgroundNoiseGenerator


class LLMAgentStreamingState(
    LLMAgentState, StreamingState[ValidAgentInputMessage, AssistantMessage]
):
    """
    State for agent streaming.
    Extends LLMAgentState with streaming-specific fields.
    """


class LLMAgentAudioStreamingState(
    LLMAgentState, StreamingState[ValidAgentInputMessage, AssistantMessage], VoiceState
):
    """
    State for agent audio streaming.
    Extends LLMAgentState, StreamingState, and VoiceState with audio streaming-specific fields.
    """


class LLMAgentTextChunkingMixin(
    TextChunkingMixin[ValidAgentInputMessage, AssistantMessage, LLMAgentStreamingState]
):
    """
    Agent-specific text chunking mixin.
    This is a specialization of TextChunkingMixin for agents with text-based chunking.
    """


class TextStreamingLLMAgent(
    LLMAgentTextChunkingMixin,
    LLMConfigMixin,
    FullDuplexAgent[LLMAgentStreamingState],
):
    """
    Full-duplex LLM Agent with text-based streaming.

    Inherits from:
    - LLMAgentTextChunkingMixin: Provides text chunking and streaming logic
    - LLMConfigMixin: Provides LLM configuration (llm, llm_args, set_seed)
    - FullDuplexAgent: Provides full-duplex streaming interface

    Features:
    - Enhanced tool call handling (tool calls are never chunked)
    - Custom turn-taking logic (responds immediately by default)
    - Proper state typing with LLMAgentStreamingState

    Usage:
        agent = TextStreamingLLMAgent(
            tools=tools,
            domain_policy=policy,
            llm="gpt-4",
            chunk_by="words",  # "chars", "words", or "sentences"
            chunk_size=10
        )

        # FULL_DUPLEX mode
        state = agent.get_init_state()  # Returns LLMAgentStreamingState
        chunk, state = agent.get_next_chunk(state, incoming_chunk)
    """

    def __init__(
        self,
        tools: List[Tool],
        domain_policy: str,
        llm: Optional[str] = None,
        llm_args: Optional[dict] = None,
        chunk_by: str = "words",
        chunk_size: int = 10,
        wait_to_respond_threshold_other: int = 2,
        wait_to_respond_threshold_self: int = 4,
    ):
        """
        Initialize the streaming LLM agent.

        Args:
            tools: List of available tools
            domain_policy: The domain-specific policy
            llm: LLM model name
            llm_args: Additional LLM arguments
            chunk_by: Chunking strategy - "chars", "words", or "sentences"
            chunk_size: Number of units per chunk
            wait_to_respond_threshold_other: The threshold for waiting before responding when OTHER person (user) spoke last.
            wait_to_respond_threshold_self: The threshold for waiting before responding when SELF (agent) spoke last.
        """
        # Initialize mixin and base class
        super().__init__(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=llm_args,
            chunk_by=chunk_by,
            chunk_size=chunk_size,
        )
        self.wait_to_respond_threshold_other = wait_to_respond_threshold_other
        self.wait_to_respond_threshold_self = wait_to_respond_threshold_self

    @property
    def system_prompt(self) -> str:
        """Get the system prompt for the agent."""
        return SYSTEM_PROMPT.format(
            domain_policy=self.domain_policy, agent_instruction=AGENT_INSTRUCTION
        )

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> LLMAgentStreamingState:
        """
        Get the initial state of the streaming agent.

        Args:
            message_history: The message history of the conversation.

        Returns:
            The initial state of the streaming agent (LLMAgentStreamingState).
        """
        from tau2.data_model.message import SystemMessage

        if message_history is None:
            message_history = []

        return LLMAgentStreamingState(
            system_messages=[SystemMessage(role="system", content=self.system_prompt)],
            messages=message_history,
            input_turn_taking_buffer=[],
            output_streaming_queue=[],
        )

    def speech_detection(self, chunk: Optional[ValidAgentInputMessage]) -> bool:
        """
        Check if the chunk is a speech chunk.
        """
        if not isinstance(chunk, UserMessage):
            return False
        return chunk.contains_speech

    def _next_turn_taking_action(
        self, state: LLMAgentStreamingState
    ) -> TurnTakingAction:
        """
        Decide the next action to take in the turn-taking.
        Returns:
            The next action to take in the turn-taking.
        """
        action, info = basic_turn_taking_policy(
            state,
            yield_threshold_when_interrupted=0,
            wait_to_respond_threshold_other=self.wait_to_respond_threshold_other,
            wait_to_respond_threshold_self=self.wait_to_respond_threshold_self,
            backchannel_min_threshold=None,
        )
        logger.debug(f"AGENT TURN-TAKING ACTION: {action}. Reason: {info}")
        return TurnTakingAction(action=action, info=info)

    def _perform_turn_taking_action(
        self, state: LLMAgentStreamingState, action: TurnTakingAction
    ) -> Tuple[AssistantMessage, LLMAgentStreamingState]:
        """
        Perform the next action in the turn-taking.

        Note: Chunk recording in tick-based history is handled by get_next_chunk()
        in the StreamingMixin, not here. This method just produces the chunk
        and manages pending buffers.

        Args:
            state: The current state of the turn-taking.
            action: The action to perform.
        Returns:
            A tuple of the next assistant message and the updated state.
        """
        logger.debug(f"Performing turn-taking action: {action}")
        next_agent_chunk = None
        is_speech_action = False
        if action.action == "keep_talking":
            next_agent_chunk = state.output_streaming_queue.pop(0)
            next_agent_chunk.timestamp = get_now()
            is_speech_action = True
            if (
                len(state.output_streaming_queue) == 0
                and state.delivering_tool_result_speech
            ):
                state.delivering_tool_result_speech = False
                logger.debug("Tool result speech delivery complete")
        elif action.action == "stop_talking":
            state.output_streaming_queue = []
        elif action.action == "generate_message":
            merged_message = merge_homogeneous_chunks(state.input_turn_taking_buffer)
            full_message, new_state = self._generate_full_duplex_message(
                merged_message, state
            )
            state.input_turn_taking_buffer = []
            if full_message.is_tool_call():
                return full_message, new_state
            else:
                chunk_messages = self._create_chunk_messages(full_message)
                state.output_streaming_queue.extend(chunk_messages)
                next_agent_chunk = state.output_streaming_queue.pop(0)
                next_agent_chunk.timestamp = get_now()
                is_speech_action = True
        elif action.action == "wait":
            pass
        # Backchannel placeholder
        elif action.action == "backchannel":
            # TODO: Implement backchannel logic.
            pass
        else:
            raise ValueError(f"Invalid action: {action}")

        if is_speech_action:
            next_agent_chunk.contains_speech = True
            state.time_since_last_talk = 0
        else:
            state.time_since_last_talk += 1
        if next_agent_chunk is None:
            next_agent_chunk = AssistantMessage(
                role="assistant",
                content=None,
                timestamp=get_now(),
                cost=0.0,
                usage=None,
                raw_data=None,
                chunk_id=0,
                is_final_chunk=True,
                contains_speech=False,
            )
        next_agent_chunk.turn_taking_action = action
        return next_agent_chunk, state

    def _process_tool_result(
        self,
        tool_result: EnvironmentMessage,
        state: LLMAgentStreamingState,
    ) -> Tuple[AssistantMessage, LLMAgentStreamingState]:
        """Process a tool result by calling the LLM and returning the response."""
        saved_buffer = state.input_turn_taking_buffer
        state.input_turn_taking_buffer = [tool_result]

        full_message, state = self._generate_full_duplex_message(tool_result, state)

        state.input_turn_taking_buffer = saved_buffer

        if full_message.is_tool_call():
            logger.debug("Tool result processing: LLM returned another tool call")
            return full_message, state
        else:
            logger.debug("Tool result processing: queuing speech chunks")
            chunk_messages = self._create_chunk_messages(full_message)
            state.output_streaming_queue.extend(chunk_messages)
            state.delivering_tool_result_speech = True
            waiting_chunk, state = self._emit_waiting_chunk(state)
            return waiting_chunk, state

    def _emit_waiting_chunk(
        self, state: LLMAgentStreamingState
    ) -> Tuple[AssistantMessage, LLMAgentStreamingState]:
        """Emit an empty chunk while waiting for tool results."""
        state.time_since_last_talk += 1
        chunk = AssistantMessage(
            role="assistant",
            content=None,
            timestamp=get_now(),
            cost=0.0,
            usage=None,
            raw_data=None,
            chunk_id=0,
            is_final_chunk=True,
            contains_speech=False,
        )
        return chunk, state

    def _generate_full_duplex_message(
        self, message: ValidAgentInputMessage, state: LLMAgentStreamingState
    ) -> Tuple[AssistantMessage, LLMAgentStreamingState]:
        """
        Generate a message using tick-based history for LLM context.

        This method linearizes the tick history to build the LLM context,
        rather than using the legacy messages list. This properly handles
        the concurrent nature of full-duplex communication.

        Args:
            message: The incoming message to respond to.
            state: The current streaming state with tick history.

        Returns:
            A tuple of the assistant message and updated state.
        """
        from tau2.utils.llm_utils import generate

        # Build LLM context from linearized ticks
        linearized_messages = state.get_linearized_messages(
            strategy=LinearizationStrategy.CONTAINMENT_AWARE,
            include_pending_input=True,
        )

        # Build full message list with system messages
        messages = state.system_messages + linearized_messages

        # Generate response
        assistant_message = generate(
            model=self.llm,
            tools=self.tools,
            messages=messages,
            call_name="streaming_agent_response",
            **self.llm_args,
        )
        my_str = ""
        for message in linearized_messages:
            my_str += f"{message.role}: {message.content}\n"

        logger.info(
            f"AGENT:\nSent to LLM:\n{my_str}\nReceived from LLM:\n{assistant_message.content}\n\n\n"
        )
        return assistant_message, state


class LLMAgentAudioChunkingMixin(
    AudioChunkingMixin[
        ValidAgentInputMessage, AssistantMessage, LLMAgentAudioStreamingState
    ]
):
    """
    Agent-specific audio chunking mixin.
    This is a specialization of AudioChunkingMixin for agents with audio-based chunking.
    """


class LLMAgentVoiceStreamingState(LLMAgentStreamingState, VoiceState):
    """
    State for agent voice streaming.
    Extends LLMAgentStreamingState and VoiceState.
    """


class VoiceStreamingLLMAgent(
    VoiceMixin[UserMessage, AssistantMessage, LLMAgentVoiceStreamingState],
    LLMAgentTextChunkingMixin,
    LLMConfigMixin,
    FullDuplexVoiceAgent[LLMAgentVoiceStreamingState],
):
    """
    Full-duplex LLM Agent with voice-based streaming.

    Inherits from:
    - VoiceMixin: Provides voice logic (TTS, STT, background noise)
    - LLMAgentTextChunkingMixin: Provides text chunking and streaming logic
    - LLMConfigMixin: Provides LLM configuration (llm, llm_args, set_seed)
    - FullDuplexVoiceAgent: Provides full-duplex streaming + voice interface

    Features:
    - Enhanced tool call handling (tool calls are never chunked)
    - Custom turn-taking logic (responds immediately by default)
    - Proper state typing with LLMAgentVoiceStreamingState

    Usage:
        agent = VoiceStreamingLLMAgent(
            tools=tools,
            domain_policy=policy,
            llm="gpt-4",
            chunk_size=10,
        )

        # FULL_DUPLEX mode
        state = agent.get_init_state()  # Returns LLMAgentVoiceStreamingState
        chunk, state = agent.get_next_chunk(state, incoming_chunk)
    """

    def __init__(
        self,
        tools: List[Tool],
        domain_policy: str,
        llm: Optional[str] = None,
        llm_args: Optional[dict] = None,
        chunk_by: str = "words",
        chunk_size: int = 10,
        voice_settings: VoiceSettings = VoiceSettings(),
        wait_to_respond_threshold_other: int = 2,
        wait_to_respond_threshold_self: int = 4,
    ):
        """
        Initialize the streaming LLM agent.

        Args:
            tools: List of available tools
            domain_policy: The domain-specific policy
            llm: LLM model name
            llm_args: Additional LLM arguments
            chunk_size: Number of units per chunk
            wait_to_respond_threshold_other: The threshold for waiting before responding when OTHER person (user) spoke last.
            wait_to_respond_threshold_self: The threshold for waiting before responding when SELF (agent) spoke last.
            voice_settings: Voice settings for the agent.
        """
        # Initialize mixin and base class
        super().__init__(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=llm_args,
            chunk_by=chunk_by,
            chunk_size=chunk_size,
            voice_settings=voice_settings,
        )
        self.wait_to_respond_threshold_other = wait_to_respond_threshold_other
        self.wait_to_respond_threshold_self = wait_to_respond_threshold_self
        self.voice_settings = voice_settings
        self.validate_voice_settings()

    @property
    def system_prompt(self) -> str:
        """Get the system prompt for the agent."""
        return SYSTEM_PROMPT.format(
            domain_policy=self.domain_policy, agent_instruction=AGENT_INSTRUCTION
        )

    def validate_voice_settings(self) -> None:
        """Validate the voice settings."""
        if self.voice_settings is None:
            raise ValueError("Voice settings must be provided")
        if not self.voice_settings.transcription_enabled:
            raise ValueError("Voice transcription must be enabled")

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> LLMAgentVoiceStreamingState:
        """
        Get the initial state of the streaming agent.

        Args:
            message_history: The message history of the conversation.

        Returns:
            The initial state of the streaming agent (LLMAgentVoiceStreamingState).
        """
        from tau2.data_model.message import SystemMessage

        if message_history is None:
            message_history = []

        # Create a silent noise generator (agent doesn't synthesize voice, but field is required)
        # Agent receives audio and sends text, so the generator won't be used
        noise_generator = BackgroundNoiseGenerator(
            sample_rate=TELEPHONY_SAMPLE_RATE,
            silent_mode=True,
        )

        # Create voice agent state
        return LLMAgentVoiceStreamingState(
            system_messages=[SystemMessage(role="system", content=self.system_prompt)],
            messages=message_history,
            noise_generator=noise_generator,
            input_turn_taking_buffer=[],
            output_streaming_queue=[],
        )

    def speech_detection(self, chunk: ValidAgentInputMessage) -> bool:
        """
        Check if the chunk is a speech chunk.
        """
        # TODO: This is just a placeholder. We need to implement a proper VAD logic.
        if not isinstance(chunk, UserMessage):
            return False
        return chunk.contains_speech

    def _next_turn_taking_action(
        self, state: LLMAgentVoiceStreamingState
    ) -> TurnTakingAction:
        """
        Decide the next action to take in the turn-taking.
        """
        action, info = basic_turn_taking_policy(
            state,
            yield_threshold_when_interrupted=0,
            wait_to_respond_threshold_other=self.wait_to_respond_threshold_other,
            wait_to_respond_threshold_self=self.wait_to_respond_threshold_self,
            backchannel_min_threshold=None,
        )
        logger.debug(f"AGENT TURN-TAKING ACTION: {action}. Reason: {info}")
        return TurnTakingAction(action=action, info=info)

    def _perform_turn_taking_action(
        self, state: LLMAgentVoiceStreamingState, action: TurnTakingAction
    ) -> Tuple[AssistantMessage, LLMAgentVoiceStreamingState]:
        """
        Perform the next action in the turn-taking.

        Note: Chunk recording in tick-based history is handled by get_next_chunk()
        in the StreamingMixin, not here. This method just produces the chunk
        and manages pending buffers.

        Args:
            state: The current state of the turn-taking.
            action: The action to perform.
        Returns:
            A tuple of the next assistant message and the updated state.
        """
        logger.debug(f"Performing turn-taking action: {action}")
        next_agent_chunk = None
        is_speech_action = False
        if action.action == "keep_talking":
            next_agent_chunk = state.output_streaming_queue.pop(0)
            next_agent_chunk.timestamp = get_now()
            is_speech_action = True
            if (
                len(state.output_streaming_queue) == 0
                and state.delivering_tool_result_speech
            ):
                state.delivering_tool_result_speech = False
                logger.debug("Tool result speech delivery complete")
        elif action.action == "stop_talking":
            state.output_streaming_queue = []
        elif action.action == "generate_message":
            merged_message = merge_homogeneous_chunks(state.input_turn_taking_buffer)
            full_message, new_state = self._generate_full_duplex_voice_message(
                merged_message, state
            )
            state.input_turn_taking_buffer = []
            if full_message.is_tool_call():
                return full_message, new_state
            else:
                chunk_messages = self._create_chunk_messages(full_message)
                state.output_streaming_queue.extend(chunk_messages)
                next_agent_chunk = state.output_streaming_queue.pop(0)
                next_agent_chunk.timestamp = get_now()
                is_speech_action = True
        elif action.action == "wait":
            pass
        # Backchannel placeholder
        elif action.action == "backchannel":
            # TODO: Implement backchannel logic.
            pass
        else:
            raise ValueError(f"Invalid action: {action}")

        if is_speech_action:
            next_agent_chunk.contains_speech = True
            state.time_since_last_talk = 0
        else:
            state.time_since_last_talk += 1
        if next_agent_chunk is None:
            next_agent_chunk = AssistantMessage(
                role="assistant",
                content=None,
                timestamp=get_now(),
                cost=0.0,
                usage=None,
                raw_data=None,
                chunk_id=0,
                is_final_chunk=True,
                contains_speech=False,
            )
        next_agent_chunk.turn_taking_action = action
        return next_agent_chunk, state

    def _process_tool_result(
        self,
        tool_result: EnvironmentMessage,
        state: LLMAgentVoiceStreamingState,
    ) -> Tuple[AssistantMessage, LLMAgentVoiceStreamingState]:
        """Process a tool result by calling the LLM and returning the response."""
        saved_buffer = state.input_turn_taking_buffer
        state.input_turn_taking_buffer = [tool_result]

        full_message, state = self._generate_full_duplex_voice_message(
            tool_result, state
        )

        state.input_turn_taking_buffer = saved_buffer

        if full_message.is_tool_call():
            logger.debug("Tool result processing: LLM returned another tool call")
            return full_message, state
        else:
            logger.debug("Tool result processing: queuing speech chunks")
            chunk_messages = self._create_chunk_messages(full_message)
            state.output_streaming_queue.extend(chunk_messages)
            state.delivering_tool_result_speech = True
            waiting_chunk, state = self._emit_waiting_chunk(state)
            return waiting_chunk, state

    def _emit_waiting_chunk(
        self, state: LLMAgentVoiceStreamingState
    ) -> Tuple[AssistantMessage, LLMAgentVoiceStreamingState]:
        """Emit an empty chunk while waiting for tool results."""
        state.time_since_last_talk += 1
        chunk = AssistantMessage(
            role="assistant",
            content=None,
            timestamp=get_now(),
            cost=0.0,
            usage=None,
            raw_data=None,
            chunk_id=0,
            is_final_chunk=True,
            contains_speech=False,
        )
        return chunk, state

    def _generate_full_duplex_voice_message(
        self, message: ValidAgentInputMessage, state: LLMAgentVoiceStreamingState
    ) -> Tuple[AssistantMessage, LLMAgentVoiceStreamingState]:
        """
        Generate a message using tick-based history for LLM context, with voice support.

        This method linearizes the tick history to build the LLM context,
        and handles audio transcription for voice input.

        Args:
            message: The incoming message to respond to (may be audio).
            state: The current streaming state with tick history.

        Returns:
            A tuple of the assistant message and updated state.
        """
        # Handle audio transcription if present
        if isinstance(message, UserMessage) and message.is_audio:
            message = self.transcribe_voice(message)
            message.is_audio = False

        # Build LLM context from linearized ticks
        linearized_messages = state.get_linearized_messages(
            strategy=LinearizationStrategy.CONTAINMENT_AWARE,
            include_pending_input=True,
        )

        # Build full message list with system messages
        messages = state.system_messages + linearized_messages

        # Generate response
        assistant_message = generate(
            model=self.llm,
            tools=self.tools,
            messages=messages,
            call_name="streaming_agent_response",
            **self.llm_args,
        )

        my_str = ""
        for message in linearized_messages:
            my_str += f"{message.role}: {message.content}\n"

        logger.info(
            f"AGENT:\nSent to LLM:\n{my_str}\nReceived from LLM:\n{assistant_message.content}\n\n\n"
        )

        return assistant_message, state
