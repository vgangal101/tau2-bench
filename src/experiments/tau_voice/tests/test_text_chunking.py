"""
Tests for text chunking functionality in TextChunkingMixin.

TextChunkingMixin was moved from tau2.agent.base.streaming to
experiments/tau_voice/utils/text_chunking.py. These tests verify:
1. Chunking is done correctly (right number of chunks, proper chunk properties)
2. Chunking and merging are inverse operations
"""

import pytest

from experiments.tau_voice.utils.text_chunking import TextChunkingMixin
from tau2.data_model.message import UserMessage

# ============================================================================
# Text Chunking Tests
# ============================================================================


class TestTextChunking:
    """Tests for TextChunkingMixin."""

    @pytest.fixture
    def text_chunker_chars(self):
        """Create a text chunker that chunks by characters."""

        class SimpleTextChunker(TextChunkingMixin):
            """Minimal implementation for testing."""

            def _next_turn_taking_action(self, state):
                return "generate_message"

            def _should_respond_to_chunk(self, incoming_chunk, state):
                return True

            def speech_detection(self, incoming_chunk):
                return True

            def _perform_turn_taking_action(self, state, action):
                return None, state

        return SimpleTextChunker(chunk_by="chars", chunk_size=10)

    @pytest.fixture
    def text_chunker_words(self):
        """Create a text chunker that chunks by words."""

        class SimpleTextChunker(TextChunkingMixin):
            """Minimal implementation for testing."""

            def _next_turn_taking_action(self, state):
                return "generate_message"

            def _should_respond_to_chunk(self, incoming_chunk, state):
                return True

            def speech_detection(self, incoming_chunk):
                return True

            def _perform_turn_taking_action(self, state, action):
                return None, state

        return SimpleTextChunker(chunk_by="words", chunk_size=3)

    def test_text_chunking_correct_number_of_chunks_chars(self, text_chunker_chars):
        """Test that text chunking by chars produces the correct number of chunks."""
        message = UserMessage(role="user", content="Hello, this is a test message!")
        chunks = text_chunker_chars._create_chunk_messages(message)

        # 30 characters / 10 per chunk = 3 chunks
        expected_chunks = 3
        assert len(chunks) == expected_chunks

    def test_text_chunking_correct_number_of_chunks_words(self, text_chunker_words):
        """Test that text chunking by words produces the correct number of chunks."""
        message = UserMessage(
            role="user", content="one two three four five six seven eight"
        )
        chunks = text_chunker_words._create_chunk_messages(message)

        # 8 words / 3 words per chunk = 3 chunks
        expected_chunks = 3
        assert len(chunks) == expected_chunks

    def test_text_chunks_have_correct_metadata(self, text_chunker_chars):
        """Test that chunks have correct chunk_id and is_final_chunk metadata."""
        message = UserMessage(role="user", content="Hello, this is a test!", cost=0.01)
        chunks = text_chunker_chars._create_chunk_messages(message)

        # Check chunk IDs are sequential
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == i
            assert chunk.is_final_chunk == (i == len(chunks) - 1)

    def test_text_chunks_preserve_cost_in_first_chunk_only(self, text_chunker_chars):
        """Test that cost/usage metadata is only in the first chunk."""
        message = UserMessage(
            role="user",
            content="Hello, this is a test!",
            cost=0.01,
            usage={"tokens": 10},
        )
        chunks = text_chunker_chars._create_chunk_messages(message)

        # First chunk should have cost and usage
        assert chunks[0].cost == 0.01
        assert chunks[0].usage == {"tokens": 10}

        # Other chunks should have zero cost and None usage
        for chunk in chunks[1:]:
            assert chunk.cost == 0.0
            assert chunk.usage is None

    def test_text_chunking_and_merging_are_inverse_chars(self, text_chunker_chars):
        """Test that chunking then merging recovers message content.

        Note: Text merge directly concatenates chunks without adding separators.
        For char-chunking, this means the original content is exactly recovered.
        """
        original_content = "ABCDEFGHIJ" * 5  # 50 characters, chunks into 5 pieces of 10
        message = UserMessage(role="user", content=original_content)

        # Chunk the message
        chunks = text_chunker_chars._create_chunk_messages(message)

        # Merge the chunks back
        merged = UserMessage.merge_chunks(chunks)

        # Text merge directly concatenates - original content is exactly recovered
        assert merged.content == original_content
        assert merged.role == message.role

    def test_text_chunking_and_merging_are_inverse_words(self, text_chunker_words):
        """Test that chunking then merging recovers the original message content."""
        original_content = "one two three four five six seven eight nine ten"
        message = UserMessage(role="user", content=original_content)

        # Chunk the message
        chunks = text_chunker_words._create_chunk_messages(message)

        # Merge the chunks back
        merged = UserMessage.merge_chunks(chunks)

        # Check that merged content matches original
        assert merged.content == original_content
        assert merged.role == message.role

    def test_text_chunking_empty_message(self, text_chunker_chars):
        """Test chunking an empty message."""
        message = UserMessage(role="user", content="")
        chunks = text_chunker_chars._create_chunk_messages(message)

        # _chunk_by_chars returns empty list for empty string, which is valid
        # (no chunks for no content)
        assert len(chunks) == 0

    def test_text_chunking_short_message(self, text_chunker_chars):
        """Test chunking a message shorter than chunk_size."""
        message = UserMessage(role="user", content="Hi")
        chunks = text_chunker_chars._create_chunk_messages(message)

        # Should produce one chunk
        assert len(chunks) == 1
        assert chunks[0].content == "Hi"
        assert chunks[0].is_final_chunk is True
