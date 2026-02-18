"""Abstract base classes for audio native adapters.
DiscreteTimeAdapter: Tick-based pattern for discrete-time simulation.
   - run_tick() as the primary method
   - Audio time is the primary clock
   - Used by DiscreteTimeAudioNativeAgent
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Optional

from tau2.data_model.audio import TELEPHONY_AUDIO_FORMAT, AudioFormat
from tau2.environment.tool import Tool

if TYPE_CHECKING:
    from tau2.voice.audio_native.tick_result import TickResult


class DiscreteTimeAdapter(ABC):
    """Abstract base class for discrete-time audio native adapters.

    This adapter pattern is designed for discrete-time simulation where:
    - Audio time is the primary clock (not wall-clock time)
    - Interaction happens in fixed-duration "ticks"
    - Each tick: send user audio, receive agent audio (capped to tick duration)

    The primary method is run_tick(), which handles one tick of the simulation.

    Attributes:
        tick_duration_ms: Duration of each tick in milliseconds.
        audio_format: Audio format for the external interface (user audio in,
            agent audio out). Defaults to telephony (8kHz μ-law).
        bytes_per_tick: Maximum agent audio bytes per tick, derived from
            tick_duration_ms and audio_format.

    Usage:
        adapter = SomeAdapter(tick_duration_ms=200)
        adapter.connect(system_prompt, tools, vad_config, modality="audio")

        for tick in range(max_ticks):
            result = adapter.run_tick(user_audio_bytes, tick_number=tick)
            # result.get_played_agent_audio() - padded to exactly bytes_per_tick
            # result.agent_audio_data - raw audio (for speech detection)
            # result.proportional_transcript - text for this tick
            # result.events - all API events received

        adapter.disconnect()
    """

    def __init__(
        self,
        tick_duration_ms: int,
        audio_format: Optional[AudioFormat] = None,
    ):
        """Initialize the adapter.

        Args:
            tick_duration_ms: Duration of each tick in milliseconds. Must be > 0.
            audio_format: Audio format for the external interface. Defaults to
                telephony (8kHz μ-law). Subclasses may pass a different format
                if their provider uses a non-telephony external format.

        Raises:
            ValueError: If tick_duration_ms is <= 0.
        """
        if tick_duration_ms <= 0:
            raise ValueError(f"tick_duration_ms must be > 0, got {tick_duration_ms}")

        self.tick_duration_ms = tick_duration_ms
        self.audio_format = audio_format or TELEPHONY_AUDIO_FORMAT
        self.bytes_per_tick = int(
            self.audio_format.bytes_per_second * tick_duration_ms / 1000
        )

    @abstractmethod
    def connect(
        self,
        system_prompt: str,
        tools: List[Tool],
        vad_config: Any,
        modality: str = "audio",
    ) -> None:
        """Connect to the API and configure the session.

        Args:
            system_prompt: System prompt for the agent.
            tools: List of tools the agent can use.
            vad_config: VAD configuration (e.g., OpenAIVADConfig).
            modality: "audio" for full audio, "audio_in_text_out" for audio input only.
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the API and clean up resources."""
        raise NotImplementedError

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the adapter is connected to the API."""
        raise NotImplementedError

    @abstractmethod
    def run_tick(
        self,
        user_audio: bytes,
        tick_number: Optional[int] = None,
    ) -> "TickResult":
        """Run one tick of the simulation.

        This is the primary method for discrete-time interaction.

        Guarantees imposed by tick_duration_ms:
        - Agent audio output is capped to at most bytes_per_tick bytes per
          tick. Any excess is buffered for the next tick.
        - Each tick takes at least tick_duration_ms of wall-clock time to
          maintain real-time pacing. Implementations achieve this either via
          an explicit sleep or by collecting events for the full duration.

        Args:
            user_audio: User audio bytes for this tick (in audio_format encoding).
            tick_number: Optional tick number for logging/tracking.

        Returns:
            TickResult containing:
            - Raw agent audio (agent_audio_data) for speech detection
            - Padded agent audio (get_played_agent_audio()) for playback
            - Proportional transcript for this tick
            - All API events received during the tick
            - Timing and interruption information
        """
        raise NotImplementedError

    @abstractmethod
    def send_tool_result(
        self,
        call_id: str,
        result: str,
        request_response: bool = True,
        is_error: bool = False,
    ) -> None:
        """Queue a tool result to be sent in the next tick.

        Tool results are typically queued and sent at the start of the next
        run_tick() call to maintain proper timing in discrete-time simulation.

        Args:
            call_id: The tool call ID.
            result: The tool result as a string.
            request_response: If True, request a response after sending.
            is_error: If True, the tool call failed and result contains error details.
        """
        raise NotImplementedError
