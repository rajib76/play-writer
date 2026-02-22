"""
Parse a markdown-formatted play script into an ordered list of ScriptSegment objects.

Markdown conventions expected from the Director agent:
  **CHARACTER:**  or  **CHARACTER:** dialogue  → dialogue segment
  *(stage direction)*                           → direction segment (NARRATOR)
  # ACT ONE / ## SCENE ONE                      → heading segment (NARRATOR)
  Other non-empty lines                         → narrator description (NARRATOR)
"""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class ScriptSegment:
    speaker: str        # Character name or "NARRATOR"
    text: str           # The text to be spoken
    segment_type: str   # "dialogue" | "direction" | "heading"


# ── Regex patterns ─────────────────────────────────────────────────────────────

# Dialogue: ALL-CAPS (or mixed caps with spaces/hyphens/apostrophes/dots) followed
# by a colon and the spoken text.
_RE_DIALOGUE = re.compile(r"^([A-Z][A-Z\s\-\'\.]+):\s+(.+)$")

# Stage direction: text wrapped in parentheses (after stripping markdown)
_RE_DIRECTION = re.compile(r"^\((.+)\)$")

# Heading keywords
_RE_HEADING = re.compile(r"^(ACT|SCENE|PROLOGUE|EPILOGUE)\b", re.IGNORECASE)


def _strip_markdown(line: str) -> str:
    """Remove common markdown decoration: *, _, #, ` characters."""
    # Remove headers
    line = re.sub(r"^#+\s*", "", line)
    # Remove bold/italic markers and backticks
    line = re.sub(r"[*_`]", "", line)
    return line.strip()


def parse_script(script_text: str) -> List[ScriptSegment]:
    """
    Parse *script_text* (a markdown play script) into an ordered list of
    ScriptSegment objects ready for TTS synthesis.

    Empty lines and lines that collapse to nothing after stripping are skipped.
    """
    segments: List[ScriptSegment] = []

    for raw_line in script_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        clean = _strip_markdown(stripped)
        if not clean:
            continue

        # ── 1. Dialogue ───────────────────────────────────────────────────────
        m = _RE_DIALOGUE.match(clean)
        if m:
            speaker = m.group(1).strip()
            text = m.group(2).strip()
            if text:
                segments.append(ScriptSegment(
                    speaker=speaker,
                    text=text,
                    segment_type="dialogue",
                ))
            continue

        # ── 2. Stage direction (parenthesised) ────────────────────────────────
        m = _RE_DIRECTION.match(clean)
        if m:
            segments.append(ScriptSegment(
                speaker="NARRATOR",
                text=m.group(1).strip(),
                segment_type="direction",
            ))
            continue

        # ── 3. Heading ────────────────────────────────────────────────────────
        if _RE_HEADING.match(clean):
            segments.append(ScriptSegment(
                speaker="NARRATOR",
                text=clean,
                segment_type="heading",
            ))
            continue

        # ── 4. Narrator description (any other non-empty line) ────────────────
        segments.append(ScriptSegment(
            speaker="NARRATOR",
            text=clean,
            segment_type="direction",
        ))

    return segments


def build_comedian_script(segments: List[ScriptSegment]) -> str:
    """
    Flatten all segments into a single continuous monologue for one-comedian delivery.

    Rules:
    - Headings (ACT / SCENE) are skipped entirely — too formal for a 2-min micro-play.
    - Stage directions flow inline as natural comedic asides (parentheses already
      stripped by parse_script, so the text reads as plain commentary).
    - Character names are dropped — the comedian just performs the lines directly.

    The result is fed to a single TTS voice that performs the whole play.
    """
    parts = []
    for seg in segments:
        if seg.segment_type == "heading":
            continue
        parts.append(seg.text)
    return " ".join(parts)
