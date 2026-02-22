"""
Single-agent generator for one-act funny plays.

Unlike the multi-agent PlayWritingSession, this uses a single comedy-focused
agent that produces the complete play in one shot (with auto-continuation if
the model hits the token ceiling).

The agent's stage directions are written in a sardonic narrator voice — funny
commentary that accompanies every movement, entrance, and bad decision on stage.
"""

import os
from typing import Generator

import anthropic
from dotenv import load_dotenv

from prompts.registry import PromptRegistry

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 64000
MAX_CONTINUATIONS = 4

_MONOLOGUE_SYSTEM = """CRITICAL LANGUAGE RULE: Your entire output MUST be in {language} only.
Do NOT translate into English. Do NOT switch languages. Every word you speak
must be in {language}. This overrides all other instructions.

You are a seasoned stand-up comedian preparing a one-person show.
You will be given a short play script and must rewrite it as a single
natural spoken-word performance — the kind you'd hear from a comedian
doing a tight two-minute bit on stage."""

_MONOLOGUE_PROMPT = """Rewrite this {language} play as a natural spoken {language} comedian's monologue.

RULES:
- OUTPUT LANGUAGE: Every single word of your output must be in {language}.
  Do NOT translate to English. If the script is in Hindi, output in Hindi.
  If the script is in Bengali, output in Bengali.
- You perform ALL characters yourself; signal switches naturally in {language}
  (e.g. "और वो बोली...", "तो मैंने कहा...", "और फिर — सुनो —" for Hindi).
- Weave stage directions in as smooth first-person asides — drop formal notation,
  just speak it conversationally in {language}.
- Add light connective tissue where needed. Keep it sparse; don't over-explain.
- Preserve EVERY joke, punchline, and beat exactly as written. No new content.
- Output ONLY the spoken monologue text. No character labels, no parentheses,
  no stage direction markers, no titles. Just the words the comedian says.
- Target ~220 spoken words — tight, punchy, under 2 minutes.

PLAY SCRIPT:
{script}"""


class FunnyPlayDirectorLoop:
    """
    Wraps FunnyPlayGenerator with a critique-and-revise loop.

    The comedy playwright writes an initial draft; a harsh comedy director
    critiques it; the playwright rewrites — repeated `critique_rounds` times.

    Usage:
        gen = FunnyPlayDirectorLoop(theme="...", language="Hindi (हिंदी)", critique_rounds=2)
        for event in gen.run_streaming():
            handle(event)
        gen.save_script("funny_play.txt")

    Event types emitted:
        chunk            — initial draft incremental text
        warning          — continuation notice from initial draft
        initial_done     — {"type": "initial_done", "text": full_draft}
        director_start   — {"type": "director_start", "round": n, "total": N}
        director_chunk   — {"type": "director_chunk", "text": str}
        director_done    — {"type": "director_done", "round": n, "critique": str}
        revision_start   — {"type": "revision_start", "round": n}
        revision_chunk   — {"type": "revision_chunk", "text": str}
        revision_done    — {"type": "revision_done", "round": n, "text": revised}
        final_done       — {"type": "final_done", "text": final_script}
        error            — {"type": "error", "text": str}
    """

    def __init__(self, theme: str, language: str = "English", critique_rounds: int = 2):
        self.theme = theme
        self.language = language
        self.critique_rounds = critique_rounds
        self.final_script: str = ""
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # ── Public API ────────────────────────────────────────────────────────────

    def run_streaming(self) -> Generator[dict, None, None]:
        """Stream all events for the full director-critique loop."""
        # 1. Generate initial draft via FunnyPlayGenerator
        inner = FunnyPlayGenerator(theme=self.theme, language=self.language)
        inner._client = self._client  # reuse connection

        current_script = ""
        try:
            for event in inner.run_streaming():
                if event["type"] == "done":
                    current_script = event["text"]
                    yield {"type": "initial_done", "text": current_script}
                else:
                    yield event  # forward chunk / warning / error
        except Exception as exc:
            yield {"type": "error", "text": f"Initial generation error: {exc}"}
            return

        if not current_script:
            yield {"type": "error", "text": "Initial draft was empty — cannot start critique loop."}
            return

        # 2. Critique-and-revise rounds
        for n in range(1, self.critique_rounds + 1):
            yield {"type": "director_start", "round": n, "total": self.critique_rounds}

            try:
                critique, _ = yield from self._stream_director(current_script)
            except Exception as exc:
                yield {"type": "error", "text": f"Director error (round {n}): {exc}"}
                return

            yield {"type": "director_done", "round": n, "critique": critique}
            yield {"type": "revision_start", "round": n}

            try:
                revised, _ = yield from self._stream_revision(current_script, critique)
            except Exception as exc:
                yield {"type": "error", "text": f"Revision error (round {n}): {exc}"}
                return

            yield {"type": "revision_done", "round": n, "text": revised}
            current_script = revised

        self.final_script = current_script
        yield {"type": "final_done", "text": current_script}

    def save_script(self, path: str = "funny_play.txt") -> None:
        """Write the final script to disk."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.final_script)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _stream_director(self, script: str) -> Generator[dict, None, tuple]:
        """Stream a director critique. Yields director_chunk events. Returns (text, stop_reason)."""
        system = PromptRegistry.get("funny_play_director_system", language=self.language)
        user_message = PromptRegistry.get("funny_play_director_critique", script=script)

        full_text = ""
        stop_reason = "end_turn"
        with self._client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield {"type": "director_chunk", "text": text}
            stop_reason = stream.get_final_message().stop_reason

        return full_text, stop_reason

    def _stream_revision(self, script: str, critique: str) -> Generator[dict, None, tuple]:
        """Stream a playwright revision. Yields revision_chunk events. Returns (text, stop_reason)."""
        system = PromptRegistry.get("funny_play_system", language=self.language)
        user_message = PromptRegistry.get(
            "funny_play_revise",
            critique=critique,
            script=script,
            language=self.language,
        )

        full_text = ""
        stop_reason = "end_turn"
        with self._client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield {"type": "revision_chunk", "text": text}
            stop_reason = stream.get_final_message().stop_reason

        return full_text, stop_reason


def rewrite_as_comedian_monologue(script_text: str, language: str = "English") -> str:
    """
    Use Claude to rewrite a flat play script as a natural performer's monologue.

    The output is plain prose — the exact words the comedian speaks, with
    natural character-switch phrasing and comedic connective tissue already
    baked in.  Feed this directly to TTS.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_MONOLOGUE_SYSTEM.format(language=language),
        messages=[{
            "role": "user",
            "content": _MONOLOGUE_PROMPT.format(script=script_text, language=language),
        }],
    )
    return response.content[0].text.strip()


class FunnyPlayGenerator:
    """
    Generates a complete one-act funny play from a theme string.

    Usage:
        gen = FunnyPlayGenerator(theme="A wizard who is afraid of magic")
        for event in gen.run_streaming():
            if event["type"] == "chunk":
                stream_to_ui(event["text"])
            elif event["type"] == "done":
                final_script = event["text"]
            elif event["type"] == "error":
                show_error(event["text"])
        gen.save_script("funny_play.txt")
    """

    def __init__(self, theme: str, language: str = "English"):
        self.theme = theme
        self.language = language
        self.final_script: str = ""
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # ── Public API ────────────────────────────────────────────────────────────

    def run_streaming(self) -> Generator[dict, None, None]:
        """
        Stream the funny play generation.

        Yielded event shapes:
          {"type": "chunk",   "text": str}   — incremental text
          {"type": "done",    "text": str}   — full completed script
          {"type": "warning", "text": str}   — continuation notice
          {"type": "error",   "text": str}   — fatal error
        """
        system = PromptRegistry.get("funny_play_system", language=self.language)
        user_message = PromptRegistry.get(
            "funny_play_generate", theme=self.theme, language=self.language
        )

        try:
            full_text = yield from self._stream_with_continuation(
                system=system,
                user_message=user_message,
            )
        except Exception as exc:
            yield {"type": "error", "text": f"Generation error: {exc}"}
            return

        self.final_script = full_text
        yield {"type": "done", "text": full_text}

    def save_script(self, path: str = "funny_play.txt") -> None:
        """Write the final script to disk."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.final_script)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _stream_with_continuation(
        self,
        system: str,
        user_message: str,
    ) -> Generator[dict, None, str]:
        """Stream with automatic continuation when the model hits the token limit."""
        messages = [{"role": "user", "content": user_message}]
        accumulated = ""

        for attempt in range(MAX_CONTINUATIONS + 1):
            chunk, stop_reason = yield from self._stream_call(
                system=system,
                messages=messages,
            )
            accumulated += chunk

            if stop_reason != "max_tokens":
                break

            if attempt == MAX_CONTINUATIONS:
                yield {
                    "type": "warning",
                    "text": f"Play is very long — reached continuation limit ({MAX_CONTINUATIONS}). "
                            "The script may be slightly incomplete at the very end.",
                }
                break

            # Feed partial response back and ask to continue
            messages = messages + [
                {"role": "assistant", "content": accumulated},
                {
                    "role": "user",
                    "content": (
                        "Continue writing the play exactly from where you stopped. "
                        "Do NOT repeat anything already written. "
                        "Pick up mid-sentence if needed and carry on to *(Curtain.)*"
                    ),
                },
            ]
            yield {
                "type": "warning",
                "text": f"Play is long — fetching continuation {attempt + 1} of {MAX_CONTINUATIONS}…",
            }

        return accumulated

    def _stream_call(
        self,
        system: str,
        messages: list,
    ) -> Generator[dict, None, tuple]:
        """Make one streaming API call, yielding chunk events. Returns (text, stop_reason)."""
        full_text = ""
        with self._client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield {"type": "chunk", "text": text}
            stop_reason = stream.get_final_message().stop_reason

        return full_text, stop_reason
