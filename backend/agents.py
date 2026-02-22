"""
Agent orchestration — the core business logic.

Two agents collaborate:
  1. StoryWriter  — drafts story, characters, scenes, dialogue
  2. Director     — critiques and refines; produces the final script

The discussion is bounded by MAX_ROUNDS to keep compute costs predictable.
Each round:
    Writer speaks → Director responds
After all rounds the Director is prompted to produce the final polished script.
"""

import os
from typing import Generator, List, Dict

import anthropic
from dotenv import load_dotenv

from models.play import PlaySession
from prompts.registry import PromptRegistry

# Load API key from .env
load_dotenv()

# Model to use for both agents
MODEL = "claude-sonnet-4-6"

# Token budgets — kept as named constants so they're easy to tune.
# Discussion rounds: enough for a solid draft or critique without being excessive.
# Final script: maximum the model supports per single API call.
MAX_TOKENS_ROUND = 64000
MAX_TOKENS_FINAL = 64000   # hard ceiling for claude-sonnet-4-6

# How many continuation calls we allow when the final script hits the token ceiling.
# Each continuation picks up exactly where the previous response ended.
# Set to 0 to disable continuation (not recommended).
MAX_CONTINUATIONS = 4


class PlayWritingSession:
    """
    Orchestrates the multi-agent play-writing discussion.

    Usage:
        session = PlayWritingSession(genre="Comedy", theme="...", tone="...", max_rounds=5)
        for event in session.run_streaming():
            # event is a dict describing what just happened
            handle(event)
        session.save_script("play_script.txt")
    """

    def __init__(self, genre: str, theme: str, tone: str, max_rounds: int = 5,
                 language: str = "English"):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.play = PlaySession(genre=genre, theme=theme, tone=tone, max_rounds=max_rounds)
        self.language = language

        # Each agent has its own running message history so context accumulates
        self._writer_messages: List[Dict] = []
        self._director_messages: List[Dict] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def run_streaming(self) -> Generator[dict, None, None]:
        """
        Run the discussion and yield progress events.

        Yielded event shapes:
          {"type": "round_start",    "round": int, "max": int}
          {"type": "writer_chunk",   "text": str}
          {"type": "writer_done",    "text": str, "round": int}
          {"type": "director_chunk", "text": str}
          {"type": "director_done",  "text": str, "round": int}
          {"type": "final_done",     "text": str}
          {"type": "warning",        "text": str}   # emitted if a response was truncated
          {"type": "error",          "text": str}
        """
        max_rounds = self.play.max_rounds

        for round_num in range(1, max_rounds + 1):
            yield {"type": "round_start", "round": round_num, "max": max_rounds}

            # ── Writer turn ──────────────────────────────────────────────────
            writer_prompt = self._build_writer_prompt(round_num)
            writer_text = ""
            try:
                writer_text, stop_reason = yield from self._stream_agent_events(
                    system=PromptRegistry.get("story_writer_system"),
                    messages=self._writer_messages,
                    user_message=writer_prompt,
                    max_tokens=MAX_TOKENS_ROUND,
                    event_type="writer_chunk",
                )
                if stop_reason == "max_tokens":
                    yield {"type": "warning",
                           "text": f"Round {round_num} Writer response was truncated — "
                                   "consider reducing rounds so each round stays focused."}
            except Exception as exc:
                yield {"type": "error", "text": f"Writer error: {exc}"}
                return

            # Append writer's turn to both histories so each agent sees context
            self._append_message(self._writer_messages, "user", writer_prompt)
            self._append_message(self._writer_messages, "assistant", writer_text)
            # Director sees writer output as a "user" message
            self._append_message(self._director_messages, "user", writer_text)

            yield {"type": "writer_done", "text": writer_text, "round": round_num}

            # ── Director turn ────────────────────────────────────────────────
            director_prompt = self._build_director_prompt(round_num, writer_text)
            director_text = ""
            try:
                director_text, stop_reason = yield from self._stream_agent_events(
                    system=PromptRegistry.get("director_system"),
                    messages=self._director_messages,
                    user_message=director_prompt,
                    max_tokens=MAX_TOKENS_ROUND,
                    event_type="director_chunk",
                )
                if stop_reason == "max_tokens":
                    yield {"type": "warning",
                           "text": f"Round {round_num} Director response was truncated."}
            except Exception as exc:
                yield {"type": "error", "text": f"Director error: {exc}"}
                return

            # Append director's turn to both histories
            self._append_message(self._director_messages, "assistant", director_text)
            # Writer sees director's feedback as a "user" message next round
            self._append_message(self._writer_messages, "user",
                                 f"[Director's feedback]\n{director_text}")

            self.play.add_round(round_num, writer_text, director_text)
            yield {"type": "director_done", "text": director_text, "round": round_num}

        # ── Final script (Director synthesises everything) ───────────────────
        # Uses MAX_TOKENS_FINAL per call AND continues automatically if the
        # model hits the token ceiling, so the play is never cut off.
        final_prompt = PromptRegistry.get("director_final_round", language=self.language)
        try:
            final_text = yield from self._stream_with_continuation(
                system=PromptRegistry.get("director_system"),
                base_messages=self._director_messages,
                user_message=final_prompt,
                event_type="director_chunk",
            )
        except Exception as exc:
            yield {"type": "error", "text": f"Final script error: {exc}"}
            return

        self.play.final_script = final_text
        yield {"type": "final_done", "text": final_text}

    def save_script(self, path: str = "play_script.txt") -> None:
        """Write the final play script to disk."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.play.final_script)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_writer_prompt(self, round_num: int) -> str:
        """Compose the instruction the Writer receives at the start of each round."""
        if round_num == 1:
            # First turn: kick things off with the pitch
            return PromptRegistry.get(
                "story_writer_opening",
                genre=self.play.genre,
                theme=self.play.theme,
                tone=self.play.tone,
                language=self.language,
            )
        # Subsequent turns: continue developing based on director's last note
        return (
            f"Round {round_num} of {self.play.max_rounds}. "
            "The Director has given you feedback above. "
            "Revise and expand the script, incorporating their best suggestions. "
            "Be creative and specific — write actual dialogue and stage directions. "
            f"Remember: write entirely in {self.language}."
        )

    def _build_director_prompt(self, round_num: int, writer_text: str) -> str:
        """Compose the instruction the Director receives after the Writer speaks."""
        if round_num == self.play.max_rounds:
            # Last round handled separately as final_script step
            pass
        return (
            f"[Round {round_num} of {self.play.max_rounds}]\n\n"
            "Here is the Writer's latest draft:\n\n"
            f"{writer_text}\n\n"
            "Give your directorial critique: what works brilliantly, what needs fixing, "
            "and concrete rewrite suggestions. Be specific and demanding. "
            f"All your suggestions and any rewritten lines must be in {self.language}."
        )

    def _stream_agent_events(
        self,
        system: str,
        messages: List[Dict],
        user_message: str,
        max_tokens: int,
        event_type: str,
    ) -> Generator[dict, None, tuple]:
        """
        Stream ONE API call, yield UI chunk events, return (full_text, stop_reason).

        stop_reason == "end_turn"    → response is complete
        stop_reason == "max_tokens" → response was cut off; caller should continue
        """
        call_messages = messages + [{"role": "user", "content": user_message}]
        full_text = ""

        with self.client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=call_messages,
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield {"type": event_type, "text": text}

            stop_reason = stream.get_final_message().stop_reason

        return full_text, stop_reason

    def _stream_with_continuation(
        self,
        system: str,
        base_messages: List[Dict],
        user_message: str,
        event_type: str,
    ) -> Generator[dict, None, str]:
        """
        Stream an agent response with automatic continuation.

        If the model hits the token ceiling (stop_reason == "max_tokens") we
        immediately make another call, passing the partial response as an
        assistant turn and asking the model to keep writing.  We repeat up to
        MAX_CONTINUATIONS times, then stop (yielding a warning if still incomplete).

        Returns the complete accumulated text.
        """
        # Working copy of the message history — we extend it as we continue.
        messages = list(base_messages)
        accumulated = ""

        for attempt in range(MAX_CONTINUATIONS + 1):
            chunk, stop_reason = yield from self._stream_agent_events(
                system=system,
                messages=messages,
                user_message=user_message,
                max_tokens=MAX_TOKENS_FINAL,
                event_type=event_type,
            )
            accumulated += chunk

            if stop_reason != "max_tokens":
                # Model finished naturally — we're done.
                break

            if attempt == MAX_CONTINUATIONS:
                # Exhausted continuation budget.
                yield {
                    "type": "warning",
                    "text": (
                        f"The play script is very long and reached the continuation "
                        f"limit ({MAX_CONTINUATIONS}). The script may be slightly "
                        "incomplete at the very end. Consider reducing rounds."
                    ),
                }
                break

            # ── Continue: feed partial response back, ask model to proceed ──
            # Add the user prompt and the partial assistant response to history.
            messages = messages + [
                {"role": "user",      "content": user_message},
                {"role": "assistant", "content": accumulated},
            ]
            # New user prompt asks the model to resume exactly where it stopped.
            user_message = (
                "Continue writing the play script exactly from where you stopped. "
                "Do NOT repeat anything already written. "
                "Pick up mid-sentence if needed and carry on to the end."
            )
            yield {
                "type": "warning",
                "text": f"Script is long — fetching continuation {attempt + 1} of {MAX_CONTINUATIONS}…",
            }

        return accumulated

    @staticmethod
    def _append_message(history: List[Dict], role: str, content: str) -> None:
        """Append a role/content pair to a message history list."""
        history.append({"role": role, "content": content})
