# 🎭 Play Writer — AI Studio

Two modes for generating original theatrical plays with Claude:

- **🤝 AI Collaboration** — a Story Writer and Director agent debate and refine a full play across multiple rounds
- **😂 One-Act Funny Play** — a single comedy agent writes a sardonic Instagram-style micro-play, optionally put through a harsh director critique-and-revise loop

---

## How it works

### Tab 1 — AI Collaboration Play

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

The discussion is hard-capped at `MAX_ROUNDS` (2–8, default 5) — no infinite loops.

### Tab 2 — One-Act Funny Play

```
FunnyPlayGenerator
      │
      ▼
 Initial Draft  ──► done (critique_rounds = 0)
      │
      ▼ (critique_rounds 1–5)
 ┌─────────────────────────────────────────────┐
 │  For each round:                            │
 │  Comedy Playwright → draft                  │
 │       ↓                                     │
 │  Harsh Comedy Director → 4–6 bullet notes   │
 │       ↓                                     │
 │  Comedy Playwright → revised script         │
 └─────────────────────────────────────────────┘
      │
      ▼
  Final Script
```

The comedy agent writes micro-plays with a **sardonic narrator voice** — stage directions read like David Attenborough personally appalled by every character's choices. The director critique loop forces sharper punchlines, better cold-opens, and tighter word economy each round.

### Audio generation

Both tabs support TTS playback:

| Provider | Voices | Best for |
|---|---|---|
| **OpenAI TTS** | alloy, echo, fable, onyx, nova, shimmer | English |
| **Sarvam AI** (bulbul:v3) | 30+ voices | Hindi, Bengali, Indian English |

The funny play audio rewrites the script as a **single comedian's monologue** before sending to TTS — stage directions become natural asides, character lines are performed directly.

---

## Project structure

```
play_writer/
├── .env                        # API keys (never commit this)
├── requirements.txt
├── README.md
│
├── prompts/
│   ├── __init__.py
│   └── registry.py             # PromptRegistry — all agent prompts in one place
│
├── models/
│   ├── __init__.py
│   └── play.py                 # PlaySession and Round dataclasses
│
├── backend/
│   ├── __init__.py
│   ├── agents.py               # PlayWritingSession — collaboration orchestrator
│   ├── funny_play_generator.py # FunnyPlayGenerator + FunnyPlayDirectorLoop
│   ├── audio_generator.py      # OpenAI TTS pipeline
│   ├── sarvam_audio_generator.py  # Sarvam AI TTS pipeline
│   └── script_parser.py        # Parses script into speakable segments
│
└── frontend/
    └── app.py                  # Streamlit UI — two tabs
```

### Key design decisions

| Concern | Approach |
|---|---|
| **Prompts** | All system prompts and message templates live in `prompts/registry.py`. No prompt strings in logic code. |
| **Bounded compute** | Both loops have hard caps — `MAX_ROUNDS` for collaboration, `critique_rounds` for the director loop. |
| **Streaming** | All agents stream token-by-token so the UI feels live throughout. |
| **Separate histories** | Each agent keeps its own message list — no cross-contamination of context. |
| **Director loop** | Generator-return pattern (`yield from`) threads critique/revision events through to the UI without blocking. |

---

## Setup

### 1. Clone and enter the directory

```bash
git clone https://github.com/rajib76/play-writer.git
cd play-writer
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API keys

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...     # Required — play generation
OPENAI_API_KEY=sk-...            # Optional — OpenAI TTS audio
SARVAM_API_KEY=...               # Optional — Sarvam AI TTS (Hindi/Bengali)
```

- Anthropic key: <https://console.anthropic.com>
- OpenAI key: <https://platform.openai.com/api-keys>
- Sarvam AI key: <https://www.sarvam.ai>

---

## Run

```bash
streamlit run frontend/app.py
```

Open <http://localhost:8501> in your browser.

---

## Configuration

| Setting | Where | Default | Notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `.env` | — | Required |
| `OPENAI_API_KEY` | `.env` | — | Optional, enables OpenAI TTS |
| `SARVAM_API_KEY` | `.env` | — | Optional, enables Sarvam TTS |
| Collaboration model | `backend/agents.py` → `MODEL` | `claude-sonnet-4-6` | |
| Funny play model | `backend/funny_play_generator.py` → `MODEL` | `claude-sonnet-4-6` | |
| Collaboration rounds | Sidebar slider | `5` | 2–8 |
| Critique rounds | Tab 2 slider | `2` | 0 = single shot, 1–5 = director loop |
| Language | Selectbox (both tabs) | English | English / Hindi / Bengali |

---

## Prompt customisation

All prompts are in **`prompts/registry.py`** inside the `PROMPTS` dict.

| Key | Purpose |
|---|---|
| `story_writer_system` | Story Writer system prompt |
| `director_system` | Director system prompt |
| `story_writer_opening` | Opening message from the Writer |
| `director_final_round` | Triggers the final polished script |
| `funny_play_system` | Comedy playwright system prompt |
| `funny_play_generate` | Initial play generation request |
| `funny_play_director_system` | Harsh comedy director system prompt |
| `funny_play_director_critique` | Director critique request template |
| `funny_play_revise` | Playwright revision request (with director notes) |

---

## Output

| File | Contents |
|---|---|
| `play_script.txt` | Final collaboration play script |
| `funny_play.txt` | Final one-act funny play script (post all critique rounds) |
