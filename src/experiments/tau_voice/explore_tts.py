from tau2.data_model.voice import ElevenLabsTTSConfig, SynthesisConfig
from tau2.voice.synthesis.synthesize import synthesize_voice
from tau2.voice.utils.audio_io import play_audio
from tau2.voice.utils.elevenlabs_utils import tts_elevenlabs


def explore_tts():
    """Explore the TTS capabilities of the voice synthesis pipeline."""
    text = "Hello, how are you?"
    voice_id = "mnHhNJntmsPxJsZvYVM7"
    elevenlabs_config = ElevenLabsTTSConfig(voice_id=voice_id)

    print(elevenlabs_config.model_dump_json(indent=2))
    print(elevenlabs_config.output_audio_format)
    print(elevenlabs_config.output_format_name)
    num_iterations = 3
    for i in range(num_iterations):
        print(f"Iteration {i + 1} of {num_iterations}")
        elevenlabs_audio_data = tts_elevenlabs(text=text, config=elevenlabs_config)
        play_audio(elevenlabs_audio_data)

    config = SynthesisConfig(
        provider_config=ElevenLabsTTSConfig(voice_id=voice_id),
    )

    print(config.model_dump_json(indent=2))

    audio_data = synthesize_voice(
        text=text,
        provider=config.provider,
        provider_config=config.provider_config,
    )
    play_audio(audio_data)


def explore_11labs_tts():
    text = "Hello, how are you?"
    voice_id = "mnHhNJntmsPxJsZvYVM7"
    config = ElevenLabsTTSConfig(voice_id=voice_id)
    audio_data = tts_elevenlabs(text=text, config=config)
    play_audio(audio_data)


if __name__ == "__main__":
    explore_tts()
