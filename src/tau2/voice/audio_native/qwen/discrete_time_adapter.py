"""Discrete-time audio native adapter for Qwen Omni Flash Realtime API.

This adapter provides a tick-based interface for Qwen Realtime API, designed
for discrete-time simulation where audio time is the primary clock.

Key features:
- Tick-based interface via run_tick()
- Audio format conversion (telephony ↔ Qwen's PCM16)
- Audio capping: max bytes_per_tick of agent audio per tick
- Audio buffering: excess agent audio carries to next tick
- Proportional transcript: text distributed based on audio played
- Interruption handling via VAD speech_started events

Audio format notes:
- Telephony: 8kHz μ-law (8000 bytes/sec)
- Qwen input: 16kHz PCM16 (32000 bytes/sec)
- Qwen output: 24kHz PCM16 (48000 bytes/sec)

Usage:
    adapter = DiscreteTimeQwenAdapter(
        tick_duration_ms=1000,
        send_audio_instant=True,
    )
    adapter.connect(system_prompt, tools, vad_config)

    for tick in range(max_ticks):
        result = adapter.run_tick(user_audio_bytes, tick_number=tick)
        # result.get_played_agent_audio() - capped agent audio (telephony format)
        # result.proportional_transcript - text for this tick
        # result.tool_calls - function calls

    adapter.disconnect()

Reference: https://www.alibabacloud.com/help/en/model-studio/realtime
"""

import asyncio
import base64
import json
import threading
from typing import Any, List, Optional, Tuple

from loguru import logger

from tau2.config import DEFAULT_TELEPHONY_RATE
from tau2.data_model.audio import TELEPHONY_AUDIO_FORMAT
from tau2.data_model.message import ToolCall
from tau2.environment.tool import Tool
from tau2.voice.audio_native.adapter import DiscreteTimeAdapter
from tau2.voice.audio_native.qwen.audio_utils import (
    StreamingQwenConverter,
    calculate_telephony_bytes_per_tick,
)
from tau2.voice.audio_native.qwen.events import (
    QwenAudioDeltaEvent,
    QwenAudioDoneEvent,
    QwenAudioTranscriptDeltaEvent,
    QwenErrorEvent,
    QwenFunctionCallArgumentsDoneEvent,
    QwenInputAudioTranscriptionCompletedEvent,
    QwenResponseDoneEvent,
    QwenSpeechStartedEvent,
    QwenTimeoutEvent,
)
from tau2.voice.audio_native.qwen.provider import (
    QwenRealtimeProvider,
    QwenVADConfig,
)
from tau2.voice.audio_native.tick_result import TickResult, UtteranceTranscript

# Telephony format constants
TELEPHONY_BYTES_PER_SECOND = DEFAULT_TELEPHONY_RATE  # 8000 bytes/sec for μ-law
TELEPHONY_ULAW_SILENCE = b"\x7f"


class DiscreteTimeQwenAdapter(DiscreteTimeAdapter):
    """Adapter for discrete-time full-duplex simulation with Qwen Realtime API.

    Implements DiscreteTimeAdapter for Qwen Omni Flash Realtime API.

    This adapter runs an async event loop in a background thread to communicate
    with the Qwen API, while exposing a synchronous interface for the agent
    and orchestrator.

    Audio conversion is handled automatically:
    - Input: telephony (8kHz μ-law) → Qwen (16kHz PCM16)
    - Output: Qwen (24kHz PCM16) → telephony (8kHz μ-law)

    Attributes:
        tick_duration_ms: Duration of each tick in milliseconds.
        bytes_per_tick: Audio bytes per tick in telephony format (8kHz μ-law).
        send_audio_instant: If True, send audio in one call per tick.
        provider: Optional provider instance. Created lazily if not provided.
        fast_forward_mode: If True, exit tick early when we have enough audio.
    """

    def __init__(
        self,
        tick_duration_ms: int,
        send_audio_instant: bool = True,
        provider: Optional[QwenRealtimeProvider] = None,
        voice: str = "Cherry",
        fast_forward_mode: bool = False,
    ):
        """Initialize the discrete-time Qwen adapter.

        Args:
            tick_duration_ms: Duration of each tick in milliseconds. Must be > 0.
            send_audio_instant: If True, send audio in one call (discrete-time mode).
            provider: Optional provider instance. Created lazily if not provided.
            voice: Voice to use. Default: Cherry.
            fast_forward_mode: If True, exit tick early when we have enough audio.
        """
        if tick_duration_ms <= 0:
            raise ValueError(f"tick_duration_ms must be > 0, got {tick_duration_ms}")

        self.tick_duration_ms = tick_duration_ms
        self.send_audio_instant = send_audio_instant
        self.fast_forward_mode = fast_forward_mode
        self.voice = voice

        # Audio format - we expose telephony format externally
        self.audio_format = TELEPHONY_AUDIO_FORMAT
        self.bytes_per_tick = calculate_telephony_bytes_per_tick(tick_duration_ms)

        # Audio converter for telephony ↔ Qwen format
        self._audio_converter = StreamingQwenConverter()

        # Provider - created lazily if not provided
        self._provider = provider
        self._owns_provider = provider is None

        # Async event loop management
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connected = False

        # Tick state
        self._tick_count = 0
        self._cumulative_user_audio_ms = 0

        # Buffered audio and transcripts (stored in TELEPHONY format)
        self._buffered_agent_audio: List[Tuple[bytes, Optional[str]]] = []
        self._utterance_transcripts: dict[str, UtteranceTranscript] = {}
        self._current_item_id: Optional[str] = None
        self._skip_item_id: Optional[str] = None

        # Tool result queue (for sending tool results in next tick)
        self._pending_tool_results: List[Tuple[str, str, bool]] = []

    @property
    def provider(self) -> QwenRealtimeProvider:
        """Get the provider, creating it if needed."""
        if self._provider is None:
            self._provider = QwenRealtimeProvider(voice=self.voice)
        return self._provider

    @property
    def is_connected(self) -> bool:
        """Check if connected to the API."""
        return self._connected and self._loop is not None

    def connect(
        self,
        system_prompt: str,
        tools: List[Tool],
        vad_config: Any = None,
        modality: str = "audio",
    ) -> None:
        """Connect to the Qwen API and configure the session.

        Args:
            system_prompt: System prompt for the agent.
            tools: List of tools the agent can use.
            vad_config: VAD configuration. Defaults to server VAD.
            modality: "audio" for audio in/out, "text" for text only.
        """
        if self._connected:
            logger.warning("Already connected, disconnecting first")
            self.disconnect()

        # Default VAD config
        if vad_config is None:
            vad_config = QwenVADConfig()

        # Store config for async initialization
        self._connect_config = {
            "system_prompt": system_prompt,
            "tools": tools,
            "vad_config": vad_config,
            "modality": modality,
        }

        # Start background thread with event loop
        self._start_background_loop()

        # Connect and configure in background loop
        future = asyncio.run_coroutine_threadsafe(
            self._async_connect(**self._connect_config),
            self._loop,
        )

        # Wait for connection with timeout
        try:
            future.result(timeout=30.0)
            self._connected = True
            logger.info(
                f"DiscreteTimeQwenAdapter connected to Qwen API "
                f"(tick={self.tick_duration_ms}ms, bytes_per_tick={self.bytes_per_tick})"
            )
        except Exception as e:
            logger.error(f"DiscreteTimeQwenAdapter failed to connect: {e}")
            self._stop_background_loop()
            raise RuntimeError(f"Failed to connect to Qwen API: {e}") from e

    async def _async_connect(
        self,
        system_prompt: str,
        tools: List[Tool],
        vad_config: QwenVADConfig,
        modality: str,
    ) -> None:
        """Async connection and configuration."""
        await self.provider.connect()
        await self.provider.configure_session(
            system_prompt=system_prompt,
            tools=tools,
            vad_config=vad_config,
            modality=modality,
        )

    def disconnect(self) -> None:
        """Disconnect from the API and clean up resources."""
        if not self._connected:
            return

        # Disconnect in background loop
        if self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(
                self._async_disconnect(),
                self._loop,
            )
            try:
                future.result(timeout=5.0)
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")

        # Stop background loop
        self._stop_background_loop()
        self._connected = False
        self._tick_count = 0
        self._cumulative_user_audio_ms = 0
        self._buffered_agent_audio.clear()
        self._utterance_transcripts.clear()
        self._audio_converter.reset()
        logger.info("DiscreteTimeQwenAdapter disconnected")

    async def _async_disconnect(self) -> None:
        """Async disconnection."""
        if self._owns_provider and self._provider is not None:
            await self.provider.disconnect()

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
        import time

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

    def run_tick(
        self, user_audio: bytes, tick_number: Optional[int] = None
    ) -> TickResult:
        """Run one tick of the simulation.

        Args:
            user_audio: User audio bytes in telephony format (8kHz μ-law).
            tick_number: Optional tick number for logging.

        Returns:
            TickResult with audio in telephony format (8kHz μ-law).
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Qwen API. Call connect() first.")

        if tick_number is None:
            tick_number = self._tick_count
        self._tick_count = tick_number + 1

        # Run tick in background loop
        future = asyncio.run_coroutine_threadsafe(
            self._async_run_tick(user_audio, tick_number),
            self._loop,
        )

        # Wait for result
        try:
            result = future.result(timeout=self.tick_duration_ms / 1000 + 30.0)
            return result
        except Exception as e:
            logger.error(f"Error in run_tick (tick={tick_number}): {e}")
            raise

    async def _async_run_tick(self, user_audio: bytes, tick_number: int) -> TickResult:
        """Async tick execution."""
        # Send any pending tool results first
        for call_id, result_str, request_response in self._pending_tool_results:
            await self.provider.send_tool_result(call_id, result_str, request_response)
        self._pending_tool_results.clear()

        # Calculate timing
        tick_start = asyncio.get_running_loop().time()

        # Create tick result
        result = TickResult(
            tick_number=tick_number,
            audio_sent_bytes=len(user_audio),
            audio_sent_duration_ms=(len(user_audio) / TELEPHONY_BYTES_PER_SECOND)
            * 1000,
            user_audio_data=user_audio,
            cumulative_user_audio_at_tick_start_ms=self._cumulative_user_audio_ms,
            bytes_per_tick=self.bytes_per_tick,
            bytes_per_second=TELEPHONY_BYTES_PER_SECOND,
            silence_byte=TELEPHONY_ULAW_SILENCE,
        )

        # Add any buffered agent audio from previous tick (already in telephony format)
        for chunk_data, item_id in self._buffered_agent_audio:
            result.agent_audio_chunks.append((chunk_data, item_id))
        self._buffered_agent_audio.clear()

        # Carry over skip state from previous tick
        result.skip_item_id = self._skip_item_id

        # Convert telephony audio to Qwen format and send
        if len(user_audio) > 0:
            qwen_audio = self._audio_converter.convert_input(user_audio)
            await self.provider.send_audio(qwen_audio)

        # Receive events for tick duration
        elapsed_so_far = asyncio.get_running_loop().time() - tick_start
        remaining_duration = max(0.01, (self.tick_duration_ms / 1000) - elapsed_so_far)

        events = await self.provider.receive_events_for_duration(remaining_duration)

        # Process all received events
        for event in events:
            await self._process_event(result, event)

        # Record simulation timing
        result.tick_sim_duration_ms = result.audio_sent_duration_ms

        # Move excess agent audio to buffer for next tick
        self._buffer_excess_audio(result)

        # Calculate proportional transcript
        result.proportional_transcript = self._get_proportional_transcript(result)

        # Update skip state for next tick
        self._skip_item_id = result.skip_item_id

        # Update cumulative user audio tracking
        self._cumulative_user_audio_ms += int(result.audio_sent_duration_ms)

        logger.info(f"Tick {tick_number} completed:\n{result.summary()}")

        return result

    async def _process_event(self, result: TickResult, event: Any) -> None:
        """Process a Qwen event."""
        result.events.append(event)

        if isinstance(event, QwenAudioDeltaEvent):
            item_id = event.item_id or self._current_item_id

            # Skip audio from truncated item
            if result.skip_item_id is not None and item_id == result.skip_item_id:
                # Decode, convert, and count discarded bytes
                if event.delta:
                    qwen_audio = base64.b64decode(event.delta)
                    telephony_audio = self._audio_converter.convert_output(qwen_audio)
                    result.truncated_audio_bytes += len(telephony_audio)
                return

            # Decode base64 and convert from Qwen format (24kHz PCM16) to telephony (8kHz μ-law)
            if event.delta:
                qwen_audio = base64.b64decode(event.delta)
                telephony_audio = self._audio_converter.convert_output(qwen_audio)

                if telephony_audio:
                    result.agent_audio_chunks.append((telephony_audio, item_id))

                # Track for transcript distribution (using telephony bytes)
                if item_id:
                    self._current_item_id = item_id
                    if item_id not in self._utterance_transcripts:
                        self._utterance_transcripts[item_id] = UtteranceTranscript(
                            item_id=item_id
                        )
                    self._utterance_transcripts[item_id].add_audio(len(telephony_audio))

        elif isinstance(event, QwenAudioTranscriptDeltaEvent):
            item_id = event.item_id or self._current_item_id
            if item_id and event.delta:
                if item_id not in self._utterance_transcripts:
                    self._utterance_transcripts[item_id] = UtteranceTranscript(
                        item_id=item_id
                    )
                self._utterance_transcripts[item_id].add_transcript(event.delta)

        elif isinstance(event, QwenSpeechStartedEvent):
            logger.debug("Speech started - interruption detected")
            # Clear buffered audio
            if self._buffered_agent_audio:
                buffered_bytes = sum(len(c[0]) for c in self._buffered_agent_audio)
                result.truncated_audio_bytes += buffered_bytes
                self._buffered_agent_audio.clear()

            # Reset audio converter state on interruption
            self._audio_converter.reset()

            # Mark truncation
            result.was_truncated = True
            result.skip_item_id = self._current_item_id

        elif isinstance(event, QwenFunctionCallArgumentsDoneEvent):
            # Parse arguments
            try:
                arguments = json.loads(event.arguments) if event.arguments else {}
            except json.JSONDecodeError:
                arguments = {}

            tool_call = ToolCall(
                id=event.call_id or "",
                name=event.name or "",
                arguments=arguments,
            )
            result.tool_calls.append(tool_call)
            logger.debug(f"Tool call detected: {event.name}({event.call_id})")

        elif isinstance(event, QwenInputAudioTranscriptionCompletedEvent):
            logger.debug(f"Input transcription: {event.transcript}")

        elif isinstance(event, QwenResponseDoneEvent):
            logger.debug("Response done (turn complete)")

        elif isinstance(event, QwenAudioDoneEvent):
            logger.debug(f"Audio done for item {event.item_id}")

        elif isinstance(event, QwenErrorEvent):
            logger.error(f"Qwen error: {event.message}")

        elif isinstance(event, QwenTimeoutEvent):
            # Normal timeout, continue
            pass

        else:
            logger.debug(f"Event {type(event).__name__} received")

    def _buffer_excess_audio(self, result: TickResult) -> None:
        """Move agent audio exceeding tick cap to buffer for next tick."""
        # If interrupted, don't buffer - discard excess
        if result.was_truncated:
            total_bytes = 0
            keep_chunks: List[Tuple[bytes, Optional[str]]] = []
            discarded_bytes = 0

            for chunk in result.agent_audio_chunks:
                chunk_data, item_id = chunk
                if total_bytes + len(chunk_data) <= self.bytes_per_tick:
                    keep_chunks.append(chunk)
                    total_bytes += len(chunk_data)
                else:
                    space_left = self.bytes_per_tick - total_bytes
                    if space_left > 0:
                        keep_chunks.append((chunk_data[:space_left], item_id))
                        discarded_bytes += len(chunk_data) - space_left
                    else:
                        discarded_bytes += len(chunk_data)
                    total_bytes = self.bytes_per_tick

            result.agent_audio_chunks = keep_chunks
            result.truncated_audio_bytes += discarded_bytes
            self._buffered_agent_audio = []
            return

        # Normal case: buffer excess for next tick
        total_bytes = 0
        keep_chunks: List[Tuple[bytes, Optional[str]]] = []
        buffer_chunks: List[Tuple[bytes, Optional[str]]] = []

        for chunk in result.agent_audio_chunks:
            chunk_data, item_id = chunk
            if total_bytes + len(chunk_data) <= self.bytes_per_tick:
                keep_chunks.append(chunk)
                total_bytes += len(chunk_data)
            else:
                space_left = self.bytes_per_tick - total_bytes
                if space_left > 0:
                    keep_chunks.append((chunk_data[:space_left], item_id))
                    buffer_chunks.append((chunk_data[space_left:], item_id))
                else:
                    buffer_chunks.append(chunk)
                total_bytes = self.bytes_per_tick

        result.agent_audio_chunks = keep_chunks
        self._buffered_agent_audio = buffer_chunks

    def _get_proportional_transcript(self, result: TickResult) -> str:
        """Get proportional transcript for the audio played this tick."""
        if not result.agent_audio_chunks:
            return ""

        # Group audio bytes by item_id
        audio_by_item: dict[str, int] = {}
        for chunk_data, item_id in result.agent_audio_chunks:
            if item_id:
                audio_by_item[item_id] = audio_by_item.get(item_id, 0) + len(chunk_data)

        # Get proportional transcript for each utterance
        transcript_parts = []
        for item_id, audio_bytes in audio_by_item.items():
            if item_id in self._utterance_transcripts:
                ut = self._utterance_transcripts[item_id]
                text = ut.get_transcript_for_audio(audio_bytes)
                if text:
                    transcript_parts.append(text)

        return " ".join(transcript_parts)

    def send_tool_result(
        self,
        call_id: str,
        result: str,
        request_response: bool = True,
        is_error: bool = False,
    ) -> None:
        """Queue a tool result to be sent in the next tick.

        Args:
            call_id: The tool call ID.
            result: The tool result as a string.
            request_response: If True, request a response after sending.
            is_error: If True, the tool call failed. Currently unused by Qwen.
        """
        self._pending_tool_results.append((call_id, result, request_response))
        logger.debug(f"Queued tool result for call_id={call_id}")

    def clear_buffers(self) -> None:
        """Clear all internal audio and transcript buffers."""
        self._buffered_agent_audio.clear()
        self._utterance_transcripts.clear()
        self._pending_tool_results.clear()
        self._skip_item_id = None
        self._audio_converter.reset()
