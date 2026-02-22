"""
Generate a single WAV audio file from ScriptSegment objects using the
Sarvam AI TTS API (bulbul:v3 model, 30+ Indian-language speakers).

API endpoint : POST https://api.sarvam.ai/text-to-speech
Auth header  : api-subscription-key
Response     : {"audios": ["<base64-wav>", ...]}

Voice strategy:
  Narrator — user-chosen voice (default: "Kabir")
  Characters — auto-assigned from CHARACTER_POOL, cycling M/F to give variety
               in order of first appearance

Text limit: bulbul:v3 accepts up to 2,500 characters per call.
Long segments are split at sentence boundaries and the resulting WAV chunks
are concatenated before silence is appended.
"""

import base64
import io
import os
import re
import struct
import wave
from itertools import cycle
from typing import Dict, Generator, List

import requests

from backend.script_parser import ScriptSegment

# ── API constants ──────────────────────────────────────────────────────────────

_API_URL = "https://api.sarvam.ai/text-to-speech"
_MODEL = "bulbul:v3"
_MAX_CHARS = 2400          # Stay safely under the 2 500-char limit
_SAMPLE_RATE = 24000
_N_CHANNELS = 1
_SAMPWIDTH = 2             # 16-bit PCM

# ── Language code mapping ──────────────────────────────────────────────────────

LANGUAGE_CODES: Dict[str, str] = {
    "English":          "en-IN",
    "Hindi (हिंदी)":    "hi-IN",
    "Bengali (বাংলা)":  "bn-IN",
}

# ── Speaker catalogue (bulbul:v3) ──────────────────────────────────────────────
# Keys are LOWERCASE — that is exactly what the Sarvam API expects in the
# "speaker" field.  Display names are produced via name.title() in the UI.

SPEAKERS: Dict[str, str] = {
    # Male (26)
    "shubh":    "M", "aditya":   "M", "rahul":    "M", "rohan":    "M",
    "amit":     "M", "dev":      "M", "ratan":    "M", "varun":    "M",
    "manan":    "M", "sumit":    "M", "kabir":    "M", "aayan":    "M",
    "ashutosh": "M", "advait":   "M", "anand":    "M", "tarun":    "M",
    "sunny":    "M", "mani":     "M", "gokul":    "M", "vijay":    "M",
    "mohit":    "M", "rehan":    "M", "soham":    "M", "abhilash": "M",
    "karun":    "M", "hitesh":   "M",
    # Female (20)
    "ritu":     "F", "priya":    "F", "neha":     "F", "pooja":    "F",
    "simran":   "F", "kavya":    "F", "ishita":   "F", "shreya":   "F",
    "roopa":    "F", "amelia":   "F", "sophia":   "F", "tanya":    "F",
    "shruti":   "F", "suhani":   "F", "kavitha":  "F", "rupali":   "F",
    "anushka":  "F", "manisha":  "F", "vidya":    "F", "arya":     "F",
}

NARRATOR_DEFAULT = "kabir"

# Character auto-assignment pool — alternating F/M for natural variety
_CHARACTER_POOL = [
    "priya", "aditya", "neha", "rahul", "simran", "dev",
    "pooja", "varun",  "kavya", "rohan",
]

# Silence durations (ms)
_SILENCE_DIALOGUE_MS = 300
_SILENCE_HEADING_MS  = 800


class SarvamAudioGenerator:
    """
    Generates an audio play from ScriptSegment objects via Sarvam AI TTS.

    Identical generate_audio_play() interface to AudioGenerator (OpenAI),
    so the frontend can swap providers without any other changes.

    Usage:
        gen = SarvamAudioGenerator(language="Hindi (हिंदी)", narrator_voice="Kabir")
        for event in gen.generate_audio_play(segments):
            ...
    """

    def __init__(
        self,
        language: str = "English",
        narrator_voice: str = NARRATOR_DEFAULT,
    ):
        self._api_key = os.environ["SARVAM_API_KEY"]
        self._lang_code = LANGUAGE_CODES.get(language, "en-IN")
        self._narrator_voice = narrator_voice
        self._character_voice_map: Dict[str, str] = {}
        self._voice_pool = cycle(
            [v for v in _CHARACTER_POOL if v != narrator_voice]
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_audio_play(
        self, segments: List[ScriptSegment]
    ) -> Generator[dict, None, None]:
        """
        Yield progress events then a final audio_done event.

        Yielded shapes (identical to AudioGenerator):
          {"type": "audio_progress", "current": int, "total": int, "speaker": str}
          {"type": "audio_done",     "wav_bytes": bytes, "voice_map": dict}
          {"type": "audio_error",    "text": str}
        """
        total = len(segments)
        all_frames: List[bytes] = []

        for idx, segment in enumerate(segments, start=1):
            yield {
                "type": "audio_progress",
                "current": idx,
                "total": total,
                "speaker": segment.speaker,
            }

            voice = self._get_voice(segment)

            try:
                frames = self._synthesise_segment(segment.text, voice)
            except Exception as exc:
                yield {"type": "audio_error", "text": f"Sarvam TTS error on segment {idx}: {exc}"}
                return

            all_frames.extend(frames)

            silence_ms = (
                _SILENCE_HEADING_MS
                if segment.segment_type == "heading"
                else _SILENCE_DIALOGUE_MS
            )
            all_frames.append(
                _make_silence(silence_ms, _SAMPLE_RATE, _N_CHANNELS, _SAMPWIDTH)
            )

        combined = _combine_frames(all_frames, _SAMPLE_RATE, _N_CHANNELS, _SAMPWIDTH)
        yield {
            "type": "audio_done",
            "wav_bytes": combined,
            "voice_map": dict(self._character_voice_map),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_voice(self, segment: ScriptSegment) -> str:
        if segment.speaker == "NARRATOR":
            return self._narrator_voice
        if segment.speaker not in self._character_voice_map:
            self._character_voice_map[segment.speaker] = next(self._voice_pool)
        return self._character_voice_map[segment.speaker]

    def _synthesise_segment(self, text: str, voice: str) -> List[bytes]:
        """
        Synthesise one segment (splitting into chunks if > MAX_CHARS) and
        return a list of raw PCM frame byte-strings.
        """
        frames = []
        for chunk in _chunk_text(text, _MAX_CHARS):
            wav_bytes = self._api_call(chunk, voice)
            frames.extend(_extract_frames(wav_bytes))
        return frames

    def _api_call(self, text: str, speaker: str) -> bytes:
        """POST to Sarvam TTS, return raw WAV bytes."""
        response = requests.post(
            _API_URL,
            headers={
                "api-subscription-key": self._api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "target_language_code": self._lang_code,
                "speaker": speaker,
                "model": _MODEL,
                "output_audio_codec": "wav",
                "speech_sample_rate": _SAMPLE_RATE,
                "enable_preprocessing": True,
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Sarvam API error {response.status_code}: {response.text[:200]}"
            )
        audios = response.json().get("audios", [])
        if not audios:
            raise RuntimeError("Sarvam API returned no audio data.")
        return base64.b64decode(audios[0])


# ── WAV utilities (module-level, shared with the stitching logic) ─────────────

def _chunk_text(text: str, max_chars: int) -> List[str]:
    """Split *text* into chunks under *max_chars* at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    # Split at sentence-ending punctuation (Latin + Devanagari danda)
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    chunks: List[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            if len(sentence) > max_chars:
                # Hard-split oversized sentence
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i : i + max_chars])
                current = ""
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks or [text]


def _extract_frames(wav_bytes: bytes) -> List[bytes]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return [wf.readframes(wf.getnframes())]


def _make_silence(
    duration_ms: int, sample_rate: int, n_channels: int, sampwidth: int
) -> bytes:
    n_samples = int(sample_rate * duration_ms / 1000) * n_channels
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


def _combine_frames(
    chunks: List[bytes], sample_rate: int, n_channels: int, sampwidth: int
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        for chunk in chunks:
            wf.writeframes(chunk)
    return buf.getvalue()


def generate_comedian_audio(
    text: str,
    voice: str,
    language: str = "English",
) -> Generator[dict, None, None]:
    """
    Single-voice comedian audio via Sarvam TTS.

    One performer delivers the entire play with no character-voice switching.
    Text must already be a rewritten comedian monologue.

    pace=0.9      — slightly slower than default for comedic timing
    temperature=0.85 — more expressive prosody than the default 0.6

    Yields the same event shapes as SarvamAudioGenerator.generate_audio_play.
    """
    api_key = os.environ["SARVAM_API_KEY"]
    lang_code = LANGUAGE_CODES.get(language, "en-IN")
    chunks = _chunk_text(text, _MAX_CHARS)
    total = len(chunks)
    all_frames: List[bytes] = []

    for i, chunk in enumerate(chunks, 1):
        yield {"type": "audio_progress", "current": i, "total": total, "speaker": "COMEDIAN"}
        try:
            response = requests.post(
                _API_URL,
                headers={
                    "api-subscription-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": chunk,
                    "target_language_code": lang_code,
                    "speaker": voice,
                    "model": _MODEL,
                    "output_audio_codec": "wav",
                    "speech_sample_rate": _SAMPLE_RATE,
                    "enable_preprocessing": True,
                    "pace": 0.9,
                    "temperature": 0.85,
                },
                timeout=30,
            )
        except Exception as exc:
            yield {"type": "audio_error", "text": f"Sarvam TTS error: {exc}"}
            return

        if response.status_code != 200:
            yield {
                "type": "audio_error",
                "text": f"Sarvam API error {response.status_code}: {response.text[:200]}",
            }
            return

        audios = response.json().get("audios", [])
        if not audios:
            yield {"type": "audio_error", "text": "Sarvam API returned no audio data."}
            return

        all_frames.extend(_extract_frames(base64.b64decode(audios[0])))

    combined = _combine_frames(all_frames, _SAMPLE_RATE, _N_CHANNELS, _SAMPWIDTH)
    yield {"type": "audio_done", "wav_bytes": combined, "voice_map": {"COMEDIAN": voice}}
