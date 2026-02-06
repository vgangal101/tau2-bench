"""Discrete-time adapter for LiveKit-based cascaded voice pipeline.

This adapter is a THIN WRAPPER that bridges the event-driven CascadedVoiceProvider
to the tick-based DiscreteTimeAdapter interface used by the simulation framework.

Responsibilities of this adapter (glue code only):
- Convert tick-based audio chunks to streaming format for provider
- Buffer provider audio output to tick boundaries
- Map provider events to TickResult
- Manage timing synchronization between ticks and async events

All core pipeline logic (STT, LLM, TTS, turn-taking, interruption handling)
lives in provider.py (CascadedVoiceProvider).

Usage:
    adapter = LiveKitCascadedAdapter(
        tick_duration_ms=1000,
        cascaded_config=CASCADED_CONFIGS["openai-thinking"],
    )
    adapter.connect(system_prompt, tools, vad_config, modality="audio")

    for tick in range(max_ticks):
        result = adapter.run_tick(user_audio_bytes, tick_number=tick)

    adapter.disconnect()
"""

import asyncio
import threading
import time
from typing import Any, List, Optional, Tuple

from loguru import logger
from pydantic import BaseModel

from tau2.data_model.audio import TELEPHONY_AUDIO_FORMAT, AudioFormat
from tau2.data_model.message import ToolCall
from tau2.environment.tool import Tool
from tau2.voice.audio_native.adapter import DiscreteTimeAdapter
from tau2.voice.audio_native.livekit.audio_utils import StreamingLiveKitConverter
from tau2.voice.audio_native.livekit.config import CascadedConfig, DeepgramTTSConfig
from tau2.voice.audio_native.livekit.provider import (
    CascadedEvent,
    CascadedEventType,
    CascadedVoiceProvider,
    TurnTakingConfig,
)
from tau2.voice.audio_native.tick_result import TickResult


class LiveKitVADConfig(BaseModel):
    """VAD configuration for LiveKit cascaded adapter.

    VAD is handled by Deepgram's integrated VAD in the STT component.
    This config is for interface compatibility with other adapters.
    """

    pass


class LiveKitCascadedAdapter(DiscreteTimeAdapter):
    """Discrete-time adapter wrapping CascadedVoiceProvider.

    This is a thin glue layer that:
    1. Runs the async provider in a background thread
    2. Converts tick-based audio to provider's streaming interface
    3. Buffers provider output to tick boundaries
    4. Maps provider events to TickResult

    All core logic (STT, LLM, TTS, turn-taking) is in CascadedVoiceProvider.

    Attributes:
        tick_duration_ms: Duration of each tick in milliseconds.
        cascaded_config: Configuration for STT, LLM, and TTS components.
        bytes_per_tick: Audio bytes per tick (derived from tick_duration_ms).
        audio_format: External audio format (telephony 8kHz μ-law).
    """

    def __init__(
        self,
        tick_duration_ms: int,
        cascaded_config: Optional[CascadedConfig] = None,
        turn_taking_config: Optional[TurnTakingConfig] = None,
        send_audio_instant: bool = True,
        fast_forward_mode: bool = False,
        audio_format: Optional[AudioFormat] = None,
    ):
        """Initialize the cascaded adapter.

        Args:
            tick_duration_ms: Duration of each tick in milliseconds.
            cascaded_config: Configuration for the cascade. Uses defaults if None.
            turn_taking_config: Turn-taking behavior config. Uses defaults if None.
            send_audio_instant: If True, send audio in one call per tick.
            fast_forward_mode: If True, exit tick early when enough audio is buffered.
            audio_format: External audio format. Defaults to telephony (8kHz μ-law).
        """
        if tick_duration_ms <= 0:
            raise ValueError(f"tick_duration_ms must be > 0, got {tick_duration_ms}")

        self.tick_duration_ms = tick_duration_ms
        self.cascaded_config = cascaded_config or CascadedConfig()
        self.turn_taking_config = turn_taking_config or TurnTakingConfig()
        self.send_audio_instant = send_audio_instant
        self.fast_forward_mode = fast_forward_mode

        # Audio format (external interface)
        self.audio_format = audio_format or TELEPHONY_AUDIO_FORMAT
        self.bytes_per_tick = int(
            self.audio_format.bytes_per_second * tick_duration_ms / 1000
        )

        # Core provider (contains all pipeline logic)
        self._provider: Optional[CascadedVoiceProvider] = None

        # Async event loop management
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connected = False

        # Tick tracking
        self._tick_count = 0
        self._pending_tool_results: List[Tuple[str, str, bool]] = []

        # Audio buffering for tick alignment
        self._audio_buffer: bytes = b""
        self._cumulative_user_audio_ms: int = 0

        # Utterance tracking for TTS audio chunks
        self._utterance_counter: int = 0

        # Audio format conversion (telephony ↔ internal formats)
        # TTS sample rate depends on config (Deepgram=24kHz, ElevenLabs varies)
        tts_sample_rate = 24000  # default
        if isinstance(self.cascaded_config.tts, DeepgramTTSConfig):
            tts_sample_rate = self.cascaded_config.tts.sample_rate
        self._audio_converter = StreamingLiveKitConverter(
            tts_sample_rate=tts_sample_rate
        )

    @property
    def provider(self) -> CascadedVoiceProvider:
        """Get the provider, creating if needed."""
        if self._provider is None:
            self._provider = CascadedVoiceProvider(
                config=self.cascaded_config,
                turn_taking=self.turn_taking_config,
            )
        return self._provider

    @property
    def is_connected(self) -> bool:
        """Check if the adapter is connected."""
        return self._connected and self._loop is not None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def connect(
        self,
        system_prompt: str,
        tools: List[Tool],
        vad_config: Any = None,
        modality: str = "audio",
    ) -> None:
        """Connect and initialize the cascaded pipeline.

        Args:
            system_prompt: System prompt for the LLM.
            tools: List of tools the agent can use.
            vad_config: VAD configuration (for interface compatibility).
            modality: "audio" or "audio_in_text_out".
        """
        if self._connected:
            logger.warning("Already connected, disconnecting first")
            self.disconnect()

        # Start background thread with event loop
        self._start_background_loop()

        # Connect provider
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.provider.connect(system_prompt, tools),
                self._loop,
            )
            future.result(timeout=30.0)
            self._connected = True
            # Reset audio converter state for fresh connection
            self._audio_converter.reset()
            logger.info(
                f"LiveKitCascadedAdapter connected "
                f"(tick={self.tick_duration_ms}ms, bytes_per_tick={self.bytes_per_tick})"
            )
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self._stop_background_loop()
            raise RuntimeError(f"Failed to connect cascaded adapter: {e}") from e

    def disconnect(self) -> None:
        """Disconnect and clean up resources."""
        if not self._connected:
            return

        if self._loop is not None and self._provider is not None:
            future = asyncio.run_coroutine_threadsafe(
                self._provider.disconnect(),
                self._loop,
            )
            try:
                future.result(timeout=5.0)
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")

        self._stop_background_loop()
        self._connected = False
        self._provider = None
        self._tick_count = 0
        self._audio_buffer = b""
        self._audio_converter.reset()
        logger.info("LiveKitCascadedAdapter disconnected")

    def _start_background_loop(self) -> None:
        """Start the background thread with async event loop."""
        if self._loop is not None:
            return

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

        # Wait for loop to be ready
        while self._loop is None:
            time.sleep(0.01)

    def _stop_background_loop(self) -> None:
        """Stop the background thread and event loop."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=2.0)
            self._loop = None
            self._thread = None

    # =========================================================================
    # Tick Processing
    # =========================================================================

    def run_tick(
        self,
        user_audio: bytes,
        tick_number: Optional[int] = None,
    ) -> TickResult:
        """Run one tick of the simulation.

        This method:
        1. Sends user audio to the provider
        2. Collects provider events for the tick duration
        3. Buffers output audio to tick boundaries
        4. Returns TickResult with aligned audio and events

        Args:
            user_audio: User audio bytes for this tick.
            tick_number: Optional tick number for logging.

        Returns:
            TickResult with audio, transcript, and events.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        if tick_number is None:
            tick_number = self._tick_count
        self._tick_count = tick_number + 1

        # Run tick in background loop
        future = asyncio.run_coroutine_threadsafe(
            self._async_run_tick(user_audio, tick_number),
            self._loop,
        )

        try:
            result = future.result(timeout=self.tick_duration_ms / 1000 + 30.0)
            return result
        except Exception as e:
            logger.error(f"Error in run_tick (tick={tick_number}): {e}")
            raise

    async def _async_run_tick(
        self,
        user_audio: bytes,
        tick_number: int,
    ) -> TickResult:
        """Async tick execution.

        Collects events from the provider and maps them to TickResult.
        """
        events: List[CascadedEvent] = []
        tool_calls: List[ToolCall] = []
        agent_audio_chunks: List[Tuple[bytes, Optional[str]]] = []
        vad_events: List[str] = []
        transcript_for_tick = ""

        # Track cumulative audio for timing
        user_audio_duration_ms = (
            len(user_audio) / self.audio_format.bytes_per_second * 1000
        )
        cumulative_at_tick_start = self._cumulative_user_audio_ms
        self._cumulative_user_audio_ms += int(user_audio_duration_ms)

        # Send any pending tool results first
        for call_id, result, _request_response in self._pending_tool_results:
            async for event in self.provider.send_tool_result(call_id, result):
                events.append(event)
                self._handle_event(
                    event, agent_audio_chunks, vad_events, tool_calls
                )
        self._pending_tool_results.clear()

        # Convert user audio from telephony (8kHz μ-law) to STT format (16kHz PCM16)
        stt_audio = self._audio_converter.convert_input(user_audio)

        # Process user audio through provider
        async for event in self.provider.process_audio(stt_audio):
            events.append(event)
            self._handle_event(event, agent_audio_chunks, vad_events, tool_calls)

            # Accumulate transcript
            if event.type == CascadedEventType.LLM_COMPLETED:
                transcript_for_tick = event.text or ""

        # Build TickResult
        result = TickResult(
            tick_number=tick_number,
            audio_sent_bytes=len(user_audio),
            audio_sent_duration_ms=user_audio_duration_ms,
            user_audio_data=user_audio,
            events=events,
            vad_events=vad_events,
            tool_calls=tool_calls,
            agent_audio_chunks=agent_audio_chunks,
            proportional_transcript=transcript_for_tick,
            bytes_per_tick=self.bytes_per_tick,
            bytes_per_second=self.audio_format.bytes_per_second,
            tick_sim_duration_ms=self.tick_duration_ms,
            cumulative_user_audio_at_tick_start_ms=cumulative_at_tick_start,
        )

        logger.debug(f"Tick {tick_number}: {result.summary()}")
        return result

    def _handle_event(
        self,
        event: CascadedEvent,
        agent_audio_chunks: List[Tuple[bytes, Optional[str]]],
        vad_events: List[str],
        tool_calls: List[ToolCall],
    ) -> None:
        """Handle a provider event, updating the output collections.

        Args:
            event: The event to handle.
            agent_audio_chunks: List to append audio chunks to.
            vad_events: List to append VAD event names to.
            tool_calls: List to append tool calls to.
        """
        if event.type == CascadedEventType.TTS_AUDIO:
            audio = event.audio
            if audio:
                # Convert TTS audio from internal format to telephony (8kHz μ-law)
                telephony_audio = self._audio_converter.convert_output(audio)
                utterance_id = f"utt_{self._utterance_counter}"
                agent_audio_chunks.append((telephony_audio, utterance_id))

        elif event.type == CascadedEventType.SPEECH_STARTED:
            vad_events.append("speech_started")

        elif event.type == CascadedEventType.SPEECH_ENDED:
            vad_events.append("speech_stopped")

        elif event.type == CascadedEventType.INTERRUPTED:
            vad_events.append("interrupted")

        elif event.type == CascadedEventType.TOOL_CALL:
            tc = event.tool_call
            if tc:
                tool_calls.append(tc)

        elif event.type == CascadedEventType.TTS_COMPLETED:
            self._utterance_counter += 1

    # =========================================================================
    # Tool Handling
    # =========================================================================

    def send_tool_result(
        self,
        call_id: str,
        result: str,
        request_response: bool = True,
    ) -> None:
        """Queue a tool result to be sent in the next tick.

        Args:
            call_id: The tool call ID.
            result: The tool result as a string.
            request_response: If True, request a response after sending.
        """
        self._pending_tool_results.append((call_id, result, request_response))
        logger.debug(f"Queued tool result for call_id={call_id}")
