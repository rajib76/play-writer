"""
Generate a single WAV audio file from a list of ScriptSegment objects using
OpenAI's TTS API (tts-1 model).

Voice assignment:
  NARRATOR_VOICE    = "fable"   — stage directions, headings, descriptions
  CHARACTER_VOICES  = cycle of ["alloy", "echo", "onyx", "nova", "shimmer"]
                      — one voice per character in order of first appearance

Audio stitching is done with Python's built-in `wave` module — no ffmpeg needed.
Silence is inserted between segments:
  - 300 ms after dialogue
  - 800 ms after headings
"""

import io
import os
import re
import wave
import struct
from itertools import cycle
from typing import Dict, Generator, List

import openai

from backend.script_parser import ScriptSegment

# ── Voice constants ────────────────────────────────────────────────────────────

NARRATOR_VOICE = "fable"
CHARACTER_VOICES = ["alloy", "echo", "onyx", "nova", "shimmer"]
COMEDIAN_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

TTS_MODEL = "tts-1"
TTS_RESPONSE_FORMAT = "wav"

# OpenAI tts-1 accepts up to 4 096 chars; stay safely under
_OPENAI_MAX_CHARS = 4000

# Silence durations in milliseconds
_SILENCE_AFTER_DIALOGUE_MS = 300
_SILENCE_AFTER_HEADING_MS = 800
_SILENCE_DEFAULT_MS = 300


class AudioGenerator:
    """
    Generates an audio play from parsed ScriptSegment objects.

    Usage:
        gen = AudioGenerator()
        for event in gen.generate_audio_play(segments):
            if event["type"] == "audio_progress":
                update_progress(event["current"], event["total"])
            elif event["type"] == "audio_done":
                wav_bytes = event["wav_bytes"]
                voice_map = event["voice_map"]
    """

    def __init__(self):
        self._client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._character_voice_map: Dict[str, str] = {}
        self._voice_cycle = cycle(CHARACTER_VOICES)

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_audio_play(
        self, segments: List[ScriptSegment]
    ) -> Generator[dict, None, None]:
        """
        Yield progress events and, as the final event, the combined WAV bytes.

        Yielded event shapes:
          {"type": "audio_progress", "current": int, "total": int, "speaker": str}
          {"type": "audio_done",     "wav_bytes": bytes, "voice_map": dict}
          {"type": "audio_error",    "text": str}
        """
        total = len(segments)
        all_frames: List[bytes] = []
        sample_rate = 24000  # OpenAI TTS WAV output is 24 kHz, 16-bit, mono
        n_channels = 1
        sampwidth = 2  # 16-bit = 2 bytes

        for idx, segment in enumerate(segments, start=1):
            yield {
                "type": "audio_progress",
                "current": idx,
                "total": total,
                "speaker": segment.speaker,
            }

            voice = self._get_voice(segment)

            try:
                wav_bytes = self._synthesise(segment.text, voice)
            except Exception as exc:
                yield {"type": "audio_error", "text": f"TTS error on segment {idx}: {exc}"}
                return

            frames = self._extract_frames(wav_bytes)
            all_frames.extend(frames)

            # Append silence between segments
            silence_ms = (
                _SILENCE_AFTER_HEADING_MS
                if segment.segment_type == "heading"
                else _SILENCE_AFTER_DIALOGUE_MS
            )
            all_frames.append(
                self._make_silence(silence_ms, sample_rate, n_channels, sampwidth)
            )

        # Stitch into one WAV
        combined_wav = self._combine_frames(
            all_frames, sample_rate, n_channels, sampwidth
        )

        yield {
            "type": "audio_done",
            "wav_bytes": combined_wav,
            "voice_map": dict(self._character_voice_map),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_voice(self, segment: ScriptSegment) -> str:
        """Return the TTS voice for this segment."""
        if segment.speaker == "NARRATOR":
            return NARRATOR_VOICE
        if segment.speaker not in self._character_voice_map:
            self._character_voice_map[segment.speaker] = next(self._voice_cycle)
        return self._character_voice_map[segment.speaker]

    def _synthesise(self, text: str, voice: str) -> bytes:
        """Call OpenAI TTS and return raw WAV bytes."""
        response = self._client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
            response_format=TTS_RESPONSE_FORMAT,
        )
        return response.content

    @staticmethod
    def _extract_frames(wav_bytes: bytes) -> List[bytes]:
        """Read raw PCM frames from a WAV byte-string."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
        return [frames]

    @staticmethod
    def _make_silence(
        duration_ms: int, sample_rate: int, n_channels: int, sampwidth: int
    ) -> bytes:
        """Generate *duration_ms* milliseconds of silent PCM frames."""
        n_samples = int(sample_rate * duration_ms / 1000) * n_channels
        return struct.pack(f"<{n_samples}h", *([0] * n_samples))

    @staticmethod
    def _combine_frames(
        frame_chunks: List[bytes],
        sample_rate: int,
        n_channels: int,
        sampwidth: int,
    ) -> bytes:
        """Concatenate all frame chunks into a single WAV byte-string."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(sample_rate)
            for chunk in frame_chunks:
                wf.writeframes(chunk)
        return buf.getvalue()


# ── Comedian (single-voice) audio ─────────────────────────────────────────────

def generate_comedian_audio(
    text: str, voice: str
) -> Generator[dict, None, None]:
    """
    Generate a single-voice WAV for a comedian performing the entire play.

    The text should already be a flat monologue (use build_comedian_script).
    No character-voice switching — one performer, start to finish.

    Yields the same event shapes as AudioGenerator.generate_audio_play:
      {"type": "audio_progress", "current": int, "total": int, "speaker": str}
      {"type": "audio_done",     "wav_bytes": bytes, "voice_map": dict}
      {"type": "audio_error",    "text": str}
    """
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    chunks = _split_text(text, _OPENAI_MAX_CHARS)
    total = len(chunks)
    sample_rate, n_channels, sampwidth = 24000, 1, 2
    all_frames: List[bytes] = []

    for i, chunk in enumerate(chunks, 1):
        yield {"type": "audio_progress", "current": i, "total": total, "speaker": "COMEDIAN"}
        try:
            response = client.audio.speech.create(
                model=TTS_MODEL, voice=voice,
                input=chunk, response_format=TTS_RESPONSE_FORMAT,
            )
        except Exception as exc:
            yield {"type": "audio_error", "text": f"OpenAI TTS error: {exc}"}
            return
        with wave.open(io.BytesIO(response.content), "rb") as wf:
            all_frames.append(wf.readframes(wf.getnframes()))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        for frames in all_frames:
            wf.writeframes(frames)

    yield {"type": "audio_done", "wav_bytes": buf.getvalue(), "voice_map": {"COMEDIAN": voice}}


def _split_text(text: str, max_chars: int) -> List[str]:
    """Split *text* at sentence boundaries to stay under *max_chars*."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            current = sentence[:max_chars] if len(sentence) > max_chars else sentence
    if current:
        chunks.append(current)
    return chunks or [text]
