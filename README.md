# 🎭 Play Writer — AI Collaboration Studio

Two AI agents — a **Story Writer** and a **Director** — collaborate in a bounded
multi-turn discussion to produce an original, entertaining theatrical play script.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────┐
│                     PlayWritingSession                          │
│                                                                 │
│  Round 1 … MAX_ROUNDS                                           │
│  ┌─────────────────┐       ┌──────────────────────────────┐    │
│  │  Story Writer   │──────▶│  Director                    │    │
│  │                 │◀──────│                              │    │
│  │  • Drafts story │  feed │  • Critiques & refines       │    │
│  │  • Characters   │  back │  • Suggests rewrites         │    │
│  │  • Dialogue     │       │  • Final round → full script │    │
│  └─────────────────┘       └──────────────────────────────┘    │
│                                                                 │
│  After MAX_ROUNDS → Director produces final polished script     │
└─────────────────────────────────────────────────────────────────┘
```

**Bounded compute**: the discussion is hard-capped at `MAX_ROUNDS` (default 5).
There is no infinite loop — once the rounds are exhausted the Director synthesises
the final script and the session ends.

---

## Project structure

```
play_writer/
├── .env                  # API key (never commit this)
├── requirements.txt
├── README.md
│
├── prompts/
│   ├── __init__.py
│   └── registry.py       # PromptRegistry — all agent prompts in one place
│
├── models/
│   ├── __init__.py
│   └── play.py           # PlaySession and Round dataclasses
│
├── backend/
│   ├── __init__.py
│   └── agents.py         # PlayWritingSession — orchestrates the two agents
│
└── frontend/
    └── app.py            # Streamlit UI
```

### Key design decisions

| Concern | Approach |
|---|---|
| **Prompts** | All agent system prompts and message templates live in `prompts/registry.py`. Code never contains prompt strings. |
| **Bounded compute** | `MAX_ROUNDS` is a hard cap. The loop runs exactly `max_rounds` iterations — no recursion, no retries. |
| **Streaming** | Both agents stream their output token-by-token so the UI feels live. |
| **Separate histories** | Each agent keeps its own message history so context accumulates correctly without cross-contamination. |

---

## Setup

### 1. Clone / enter the directory

```bash
cd play_writer
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your Anthropic API key

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
```

Get your key at <https://console.anthropic.com>.

---

## Run

### Streamlit UI (recommended)

```bash
streamlit run frontend/app.py
```

Open <http://localhost:8501> in your browser, configure the play in the sidebar,
and click **✍️ Write the Play!**.

The final script is:
- Displayed in the browser
- Saved to `play_script.txt` in the working directory
- Available as a download button

---

## Configuration

| Setting | Where | Default | Notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `.env` | — | Required |
| Model | `backend/agents.py` → `MODEL` | `claude-sonnet-4-6` | Change here to switch models |
| Max rounds | Streamlit sidebar slider | `5` | 2 – 8 |
| Genre / Theme / Tone | Streamlit sidebar | Comedy / default premise | Free-form |

---

## Prompt customisation

All prompts are in **`prompts/registry.py`** inside the `PROMPTS` dict.

To change an agent's persona, edit the relevant key:

| Key | Purpose |
|---|---|
| `story_writer_system` | Story Writer's system prompt |
| `director_system` | Director's system prompt |
| `story_writer_opening` | First message the Writer sends |
| `director_final_round` | Instruction that triggers the final script |

---

## Output

After a successful run you will find `play_script.txt` in the project root.
It contains the Director's final synthesised, performance-ready play script.
