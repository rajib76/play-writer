"""
Data models for the play-writing session.

Kept intentionally simple — plain dataclasses, no ORM.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Round:
    """
    Represents one exchange in the agent discussion.

    round_number  : 1-based counter
    writer_draft  : what the Story Writer contributed this round
    director_note : what the Director responded with
    """
    round_number: int
    writer_draft: str = ""
    director_note: str = ""


@dataclass
class PlaySession:
    """
    Holds the full state of a single play-writing session.

    genre       : e.g. "Comedy", "Thriller", "Romance"
    theme       : e.g. "Artificial Intelligence taking over a small bakery"
    tone        : e.g. "Satirical and absurd"
    max_rounds  : hard cap on discussion rounds (bounded compute)
    rounds      : ordered list of Round objects
    final_script: the polished play produced at the end
    """
    genre: str
    theme: str
    tone: str
    max_rounds: int = 5
    rounds: List[Round] = field(default_factory=list)
    final_script: str = ""

    def add_round(self, round_number: int, writer_draft: str, director_note: str) -> None:
        """Append a completed exchange to the session history."""
        self.rounds.append(Round(round_number, writer_draft, director_note))

    def summary(self) -> str:
        """Return a brief plain-text summary of the session."""
        lines = [
            f"Genre : {self.genre}",
            f"Theme : {self.theme}",
            f"Tone  : {self.tone}",
            f"Rounds: {len(self.rounds)} / {self.max_rounds}",
        ]
        return "\n".join(lines)
