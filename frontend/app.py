"""
Streamlit frontend for the Play Writer application.

Two modes (tabs):
  🤝 AI Collaboration — Story Writer + Director agents, multi-round discussion
  😂 One-Act Funny Play — single comedy agent, sardonic narrator stage directions

Audio section supports two TTS providers:
  • OpenAI TTS  — 6 voices (alloy, echo, fable, onyx, nova, shimmer)
  • Sarvam AI   — 30+ voices (bulbul:v3), ideal for English / Hindi / Bengali
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Play Writer AI",
    page_icon="🎭",
    layout="wide",
)

st.title("🎭 Play Writer — AI Studio")
st.caption(
    "Two AI agents collaborate on full plays — or let one comedy agent write "
    "a hilariously narrated one-act.  Listen back with OpenAI or Sarvam AI voices."
)


# ── Shared helpers ────────────────────────────────────────────────────────────

_OPENAI_COMEDIAN_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


def render_comedian_audio_section(
    script_key: str,
    audio_key: str,
    voice_map_key: str,
    language_key: str,
) -> None:
    """
    Audio section for the One-Act Funny Play tab.

    A single comedian voice performs the entire play — no narrator/character split.
    Stage directions and dialogue are flattened into one continuous monologue and
    sent to TTS as one unified performance.
    """
    st.divider()
    st.subheader("🎤 Comedian Audio")
    st.caption(
        "One voice performs the entire play — stage directions become natural asides, "
        "character lines are performed directly. No narrator switching."
    )

    language = st.session_state.get(language_key, "English")

    provider = st.radio(
        "TTS Provider",
        ["OpenAI TTS", "Sarvam AI"],
        horizontal=True,
        key=f"comedian_provider_{audio_key}",
        help="OpenAI TTS — 6 voices. Sarvam AI — 30+ Indian-language voices (bulbul:v3).",
    )

    if provider == "Sarvam AI":
        from backend.sarvam_audio_generator import SPEAKERS, LANGUAGE_CODES
        has_key = bool(os.environ.get("SARVAM_API_KEY"))
        voice_options = sorted(
            f"{name.title()} ({'♂' if g == 'M' else '♀'})" for name, g in SPEAKERS.items()
        )
        comedian_choice = st.selectbox(
            "Comedian Voice",
            voice_options,
            key=f"comedian_voice_{audio_key}",
            help="This single voice performs every word of the play.",
        )
        comedian_voice = comedian_choice.split(" (")[0].lower()
        lang_code = LANGUAGE_CODES.get(language, "en-IN")
        st.caption(f"Language: **{language}** → `{lang_code}`")
        if not has_key:
            st.warning("SARVAM_API_KEY not set in .env — Sarvam TTS is disabled.")
    else:
        has_key = bool(os.environ.get("OPENAI_API_KEY"))
        comedian_voice = st.selectbox(
            "Comedian Voice",
            _OPENAI_COMEDIAN_VOICES,
            index=_OPENAI_COMEDIAN_VOICES.index("onyx"),
            key=f"comedian_voice_{audio_key}",
            help="This single voice performs every word of the play.",
        )
        if not has_key:
            st.warning("OPENAI_API_KEY not set in .env — OpenAI TTS is disabled.")

    # Show previously generated audio
    if st.session_state.get(audio_key) and st.session_state.get(voice_map_key):
        cached_voice = st.session_state[voice_map_key].get("COMEDIAN", comedian_voice)
        st.markdown(f"**Performed by:** {cached_voice}")
        st.audio(st.session_state[audio_key], format="audio/wav")
        st.download_button(
            label="⬇️ Download Audio (WAV)",
            data=st.session_state[audio_key],
            file_name="comedian_audio.wav",
            mime="audio/wav",
            key=f"dl_{audio_key}",
        )
        st.markdown("---")

    generate_btn = st.button(
        "🎤 Generate Comedian Audio",
        type="primary",
        disabled=not has_key,
        key=f"gen_comedian_{audio_key}",
    )

    if generate_btn and has_key:
        from backend.script_parser import parse_script, build_comedian_script
        from backend.funny_play_generator import rewrite_as_comedian_monologue

        # Step 1: flatten the script (strips character names, drops headings)
        segments = parse_script(st.session_state[script_key])
        flat_text = build_comedian_script(segments)

        if not flat_text.strip():
            st.error("Could not extract any text from the script.")
            return

        # Step 2: Claude rewrites it as a natural spoken monologue
        rewrite_status = st.empty()
        rewrite_status.info("Adapting script for comedian delivery…")
        try:
            comedian_text = rewrite_as_comedian_monologue(st.session_state[script_key], language=language)
        except Exception as exc:
            rewrite_status.empty()
            st.error(f"Script adaptation failed: {exc}")
            return
        rewrite_status.empty()

        audio_progress = st.progress(0, text="Preparing comedian audio…")
        audio_status = st.empty()
        wav_bytes = None
        voice_map = {}

        if provider == "Sarvam AI":
            from backend.sarvam_audio_generator import generate_comedian_audio
            gen = generate_comedian_audio(comedian_text, comedian_voice, language)
        else:
            from backend.audio_generator import generate_comedian_audio
            gen = generate_comedian_audio(comedian_text, comedian_voice)

        for event in gen:
            if event["type"] == "audio_progress":
                cur, total = event["current"], event["total"]
                audio_progress.progress(
                    int(cur / total * 100),
                    text=f"Synthesising… ({cur}/{total})",
                )
                audio_status.info("Generating comedian audio…")
            elif event["type"] == "audio_done":
                wav_bytes = event["wav_bytes"]
                voice_map = event["voice_map"]
            elif event["type"] == "audio_error":
                st.error(event["text"])
                return

        if wav_bytes:
            audio_progress.progress(100, text="Audio ready!")
            audio_status.success(f"Performance by **{comedian_voice}** is ready!")
            st.session_state[audio_key] = wav_bytes
            st.session_state[voice_map_key] = voice_map

            st.markdown(f"**Performed by:** {comedian_voice}")
            st.audio(wav_bytes, format="audio/wav")
            st.download_button(
                label="⬇️ Download Audio (WAV)",
                data=wav_bytes,
                file_name="comedian_audio.wav",
                mime="audio/wav",
                key=f"dl_new_{audio_key}",
            )


def _show_voice_map(voice_map: dict, narrator_label: str) -> None:
    """Render a table of character → voice assignments."""
    st.markdown("**Voice assignments:**")
    rows = [{"Character": k, "Voice": v} for k, v in voice_map.items()]
    rows.append({"Character": "NARRATOR", "Voice": narrator_label})
    st.table(rows)


def _run_audio_generation(
    script_key: str,
    audio_key: str,
    voice_map_key: str,
    provider: str,
    language: str,
    narrator_voice: str,
) -> None:
    """Run the TTS pipeline and update session state."""
    from backend.script_parser import parse_script

    segments = parse_script(st.session_state[script_key])
    if not segments:
        st.error("Could not parse any segments from the script.")
        return

    audio_progress = st.progress(0, text="Preparing audio…")
    audio_status = st.empty()

    if provider == "Sarvam AI":
        from backend.sarvam_audio_generator import SarvamAudioGenerator
        generator = SarvamAudioGenerator(language=language, narrator_voice=narrator_voice)
    else:
        from backend.audio_generator import AudioGenerator
        generator = AudioGenerator()

    wav_bytes = None
    voice_map = {}

    for event in generator.generate_audio_play(segments):
        if event["type"] == "audio_progress":
            cur, total, speaker = event["current"], event["total"], event["speaker"]
            audio_progress.progress(
                int(cur / total * 100),
                text=f"Synthesising {speaker} ({cur}/{total})…",
            )
            audio_status.info(f"Processing segment {cur} of {total}: **{speaker}**")
        elif event["type"] == "audio_done":
            wav_bytes = event["wav_bytes"]
            voice_map = event["voice_map"]
        elif event["type"] == "audio_error":
            st.error(event["text"])
            return

    if wav_bytes:
        audio_progress.progress(100, text="Audio ready!")
        audio_status.success("Audio play generated!")
        st.session_state[audio_key] = wav_bytes
        st.session_state[voice_map_key] = voice_map
        st.session_state[f"{audio_key}_narrator_label"] = narrator_voice


def render_audio_section(
    script_key: str,
    audio_key: str,
    voice_map_key: str,
    language_key: str,
) -> None:
    """
    Render the full audio play section for a given script.

    script_key    : session_state key holding the final script text
    audio_key     : session_state key for cached WAV bytes
    voice_map_key : session_state key for the character→voice dict
    language_key  : session_state key for the play language string
    """
    st.divider()
    st.subheader("🎙️ Audio Play")

    language = st.session_state.get(language_key, "English")

    # ── Provider selector ─────────────────────────────────────────────────────
    provider = st.radio(
        "TTS Provider",
        ["OpenAI TTS", "Sarvam AI"],
        horizontal=True,
        key=f"provider_{audio_key}",
        help="OpenAI TTS uses English-focused voices. Sarvam AI (bulbul:v3) has 30+ voices optimised for Indian languages.",
    )

    # ── Provider-specific config ──────────────────────────────────────────────
    narrator_voice: str
    has_key: bool

    if provider == "Sarvam AI":
        from backend.sarvam_audio_generator import SPEAKERS, NARRATOR_DEFAULT, LANGUAGE_CODES

        openai_key = os.environ.get("SARVAM_API_KEY")
        has_key = bool(openai_key)

        # Build labelled option list: "Kabir (♂)", "Priya (♀)", …
        voice_options = sorted(
            f"{name.title()} ({'♂' if g == 'M' else '♀'})" for name, g in SPEAKERS.items()
        )
        default_gender = SPEAKERS.get(NARRATOR_DEFAULT, "M")
        default_label = f"{NARRATOR_DEFAULT.title()} ({'♂' if default_gender == 'M' else '♀'})"
        default_idx = next(
            (i for i, v in enumerate(voice_options) if v == default_label), 0
        )

        narrator_choice = st.selectbox(
            "Narrator Voice",
            voice_options,
            index=default_idx,
            key=f"sarvam_narrator_{audio_key}",
            help="Used for all stage directions and scene headings. Characters are auto-assigned alternating male/female voices.",
        )
        narrator_voice = narrator_choice.split(" (")[0].lower()

        lang_code = LANGUAGE_CODES.get(language, "en-IN")
        st.caption(
            f"Language: **{language}** → `{lang_code}`  |  "
            "Characters auto-assigned alternating ♂/♀ voices from bulbul:v3."
        )

        if not has_key:
            st.warning("SARVAM_API_KEY not set in .env — Sarvam TTS is disabled.")

    else:  # OpenAI TTS
        openai_key = os.environ.get("OPENAI_API_KEY")
        has_key = bool(openai_key)
        narrator_voice = "fable"
        st.caption(
            "Narrator uses **fable**. Characters are auto-assigned from: "
            "alloy, echo, onyx, nova, shimmer."
        )
        if not has_key:
            st.warning("OPENAI_API_KEY not set in .env — OpenAI TTS is disabled.")

    # ── Show previously generated audio (same tab session) ───────────────────
    if st.session_state.get(audio_key) and st.session_state.get(voice_map_key):
        st.markdown("---")
        _show_voice_map(
            st.session_state[voice_map_key],
            narrator_label=st.session_state.get(f"{audio_key}_narrator_label", narrator_voice),
        )
        st.audio(st.session_state[audio_key], format="audio/wav")
        st.download_button(
            label="⬇️ Download Audio (WAV)",
            data=st.session_state[audio_key],
            file_name="play_audio.wav",
            mime="audio/wav",
            key=f"dl_{audio_key}",
        )
        st.markdown("---")

    # ── Generate button ───────────────────────────────────────────────────────
    generate_btn = st.button(
        "🎙️ Generate Audio Play",
        type="primary",
        disabled=not has_key,
        key=f"gen_audio_{audio_key}",
    )

    if generate_btn and has_key:
        _run_audio_generation(
            script_key=script_key,
            audio_key=audio_key,
            voice_map_key=voice_map_key,
            provider=provider,
            language=language,
            narrator_voice=narrator_voice,
        )
        # Show freshly generated audio
        if st.session_state.get(audio_key):
            _show_voice_map(
                st.session_state[voice_map_key],
                narrator_label=st.session_state.get(f"{audio_key}_narrator_label", narrator_voice),
            )
            st.audio(st.session_state[audio_key], format="audio/wav")
            st.download_button(
                label="⬇️ Download Audio (WAV)",
                data=st.session_state[audio_key],
                file_name="play_audio.wav",
                mime="audio/wav",
                key=f"dl_new_{audio_key}",
            )


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_collab, tab_funny = st.tabs(["🤝 AI Collaboration Play", "😂 One-Act Funny Play"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — AI Collaboration
# ══════════════════════════════════════════════════════════════════════════════

with tab_collab:
    with st.sidebar:
        st.header("🤝 Collaboration Play")

        genre = st.selectbox(
            "Genre",
            ["Comedy", "Drama", "Thriller", "Romance", "Sci-Fi", "Fantasy", "Mystery"],
            index=0,
        )
        theme_collab = st.text_area(
            "Theme / Premise",
            value="A sentient coffee machine falls in love with a barista who wants to quit their job",
            height=100,
            key="theme_collab",
        )
        tone = st.selectbox(
            "Tone",
            ["Satirical and absurd", "Heartfelt and sincere", "Dark and suspenseful",
             "Light and whimsical", "Bittersweet"],
            index=0,
        )
        max_rounds = st.slider(
            "Discussion Rounds",
            min_value=2, max_value=8, value=5,
            help="How many back-and-forth rounds the agents have.",
        )
        language_collab = st.selectbox(
            "Language",
            ["English", "Hindi (हिंदी)", "Bengali (বাংলা)"],
            index=0,
            key="language_collab",
            help="All dialogue, directions, and headings will be written in this language.",
        )
        st.divider()
        start_btn = st.button("✍️ Write the Play!", type="primary", use_container_width=True)

    # ── Main ──────────────────────────────────────────────────────────────────
    if start_btn:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.error("ANTHROPIC_API_KEY not found. Please set it in your .env file.")
            st.stop()

        st.session_state["collab_script"] = None
        st.session_state["collab_audio"] = None
        st.session_state["collab_voice_map"] = None

        progress_bar = st.progress(0, text="Starting discussion…")
        status_text = st.empty()
        st.divider()
        discussion_area = st.container()
        st.divider()
        final_area = st.container()

        from backend.agents import PlayWritingSession
        session = PlayWritingSession(
            genre=genre, theme=theme_collab, tone=tone,
            max_rounds=max_rounds, language=language_collab,
        )

        current_round = 0
        writer_buf = ""
        director_buf = ""
        in_final = False
        round_containers: dict = {}
        final_script_box = None

        def get_round_container(rn: int):
            if rn not in round_containers:
                with discussion_area:
                    exp = st.expander(f"Round {rn} of {max_rounds}", expanded=(rn == max_rounds))
                    cols = exp.columns(2)
                    round_containers[rn] = {
                        "writer_col":   cols[0],
                        "director_col": cols[1],
                        "writer_box":   cols[0].empty(),
                        "director_box": cols[1].empty(),
                    }
            return round_containers[rn]

        for event in session.run_streaming():
            etype = event["type"]

            if etype == "round_start":
                current_round = event["round"]
                writer_buf = director_buf = ""
                progress_bar.progress(
                    int((current_round - 1) / max_rounds * 100),
                    text=f"Round {current_round} / {max_rounds}",
                )
                status_text.info(f"Round {current_round}: Story Writer is drafting…")
                rc = get_round_container(current_round)
                rc["writer_col"].markdown("**✍️ Story Writer**")
                rc["director_col"].markdown("**🎬 Director**")

            elif etype == "writer_chunk":
                writer_buf += event["text"]
                get_round_container(current_round)["writer_box"].markdown(writer_buf + "▌")

            elif etype == "writer_done":
                get_round_container(current_round)["writer_box"].markdown(writer_buf)
                status_text.info(f"Round {current_round}: Director is reviewing…")

            elif etype == "director_chunk":
                director_buf += event["text"]
                if not in_final:
                    get_round_container(current_round)["director_box"].markdown(director_buf + "▌")
                else:
                    final_script_box.markdown(director_buf + "▌")

            elif etype == "director_done":
                get_round_container(current_round)["director_box"].markdown(director_buf)
                progress_bar.progress(
                    int(current_round / max_rounds * 100),
                    text=f"Completed round {current_round}",
                )

            elif etype == "final_done":
                in_final = True
                progress_bar.progress(100, text="Script complete!")
                status_text.success("The play is ready!")
                with final_area:
                    st.subheader("🎭 Final Play Script")
                    final_script_box = st.empty()
                    final_script_box.markdown(event["text"])
                session.save_script("play_script.txt")
                st.success("Script saved to **play_script.txt**")
                st.download_button(
                    label="⬇️ Download Script",
                    data=event["text"],
                    file_name="play_script.txt",
                    mime="text/plain",
                )
                st.session_state["collab_script"] = event["text"]
                st.session_state["collab_language"] = language_collab
                st.session_state["collab_audio"] = None
                st.session_state["collab_voice_map"] = None

            elif etype == "warning":
                st.warning(event["text"])
            elif etype == "error":
                st.error(event["text"])
                break

    elif not st.session_state.get("collab_script"):
        st.info("Configure your play in the sidebar, then click **✍️ Write the Play!**")
        st.markdown("""
### How it works

1. **Story Writer** receives your genre, theme, and tone and drafts the opening scene.
2. **Director** critiques the draft — praising what works, demanding improvements.
3. They alternate for the number of rounds you choose (**bounded compute** — no runaway loops).
4. After the last round the Director synthesises everything into a polished final script.

---
*Powered by Claude — claude-sonnet-4-6*
""")

    if st.session_state.get("collab_script"):
        render_audio_section(
            "collab_script", "collab_audio", "collab_voice_map", "collab_language"
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — One-Act Funny Play
# ══════════════════════════════════════════════════════════════════════════════

with tab_funny:
    st.markdown("""
### 😂 One-Act Funny Play Generator

A single comedy agent writes a **complete one-act play** from your theme.
The stage directions are narrated in a **sardonic, over-dramatic voice** —
think David Attenborough, but the wildlife are people making terrible choices.
""")

    funny_theme = st.text_area(
        "Theme / Premise",
        value="A group of office workers realise their new AI assistant has been secretly running the company for months",
        height=100,
        key="funny_theme",
        help="Give the comedy agent a starting premise — the funnier the seed, the wilder the play.",
    )

    language_funny = st.selectbox(
        "Language",
        ["English", "Hindi (हिंदी)", "Bengali (বাংলা)"],
        index=0,
        key="language_funny",
        help="The entire play — including sardonic narrator directions — will be written in this language.",
    )

    critique_rounds = st.slider(
        "Director Critique Rounds",
        min_value=0, max_value=5, value=2,
        key="funny_critique_rounds",
        help="0 = single shot. 1–5 = a harsh comedy director critiques and the playwright revises N times.",
    )

    funny_btn = st.button(
        "🎭 Generate Funny Play",
        type="primary",
        disabled=not bool(os.environ.get("ANTHROPIC_API_KEY")),
        key="funny_btn",
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY not set in .env — play generation is disabled.")

    if funny_btn:
        st.session_state["funny_script"] = None
        st.session_state["funny_audio"] = None
        st.session_state["funny_voice_map"] = None

        st.divider()
        funny_status = st.empty()

        if critique_rounds == 0:
            # ── Path A: single-shot generation ───────────────────────────────
            funny_status.info("The comedy agent is writing your play…")
            script_box = st.empty()
            script_buf = ""

            from backend.funny_play_generator import FunnyPlayGenerator
            gen = FunnyPlayGenerator(theme=funny_theme, language=language_funny)

            for event in gen.run_streaming():
                if event["type"] == "chunk":
                    script_buf += event["text"]
                    script_box.markdown(script_buf + "▌")
                elif event["type"] == "warning":
                    st.warning(event["text"])
                elif event["type"] == "done":
                    script_box.markdown(script_buf)
                    funny_status.success("Your funny play is ready!")
                    gen.save_script("funny_play.txt")
                    st.success("Script saved to **funny_play.txt**")
                    st.download_button(
                        label="⬇️ Download Script",
                        data=script_buf,
                        file_name="funny_play.txt",
                        mime="text/plain",
                        key="funny_dl_script",
                    )
                    st.session_state["funny_script"] = script_buf
                    st.session_state["funny_language"] = language_funny
                    st.session_state["funny_audio"] = None
                    st.session_state["funny_voice_map"] = None
                elif event["type"] == "error":
                    st.error(event["text"])
                    break

        else:
            # ── Path B: director critique-and-revise loop ─────────────────────
            funny_status.info("The comedy agent is writing the initial draft…")

            initial_script_area = st.container()
            critique_area = st.container()

            script_box = initial_script_area.empty()
            script_buf = ""
            director_boxes: dict = {}
            director_bufs: dict = {}
            revision_box = None
            revision_buf = ""

            from backend.funny_play_generator import FunnyPlayDirectorLoop
            gen = FunnyPlayDirectorLoop(
                theme=funny_theme,
                language=language_funny,
                critique_rounds=critique_rounds,
            )

            for event in gen.run_streaming():
                etype = event["type"]

                if etype == "chunk":
                    script_buf += event["text"]
                    script_box.markdown(script_buf + "▌")

                elif etype == "initial_done":
                    script_box.markdown(script_buf)
                    funny_status.info("Draft ready! Director reviewing…")

                elif etype == "director_start":
                    n, total = event["round"], event["total"]
                    with critique_area:
                        exp = st.expander(
                            f"🎬 Director Critique — Round {n} of {total}",
                            expanded=True,
                        )
                        director_boxes[n] = exp.empty()
                    director_bufs[n] = ""

                elif etype == "director_chunk":
                    n = max(director_boxes.keys())
                    director_bufs[n] += event["text"]
                    director_boxes[n].markdown(director_bufs[n] + "▌")

                elif etype == "director_done":
                    n = event["round"]
                    director_boxes[n].markdown(director_bufs[n])
                    with critique_area:
                        st.markdown(f"**✍️ Revision {n}**")
                    revision_box = critique_area.empty()
                    revision_buf = ""
                    funny_status.info("Playwright revising…")

                elif etype == "revision_chunk":
                    revision_buf += event["text"]
                    if revision_box is not None:
                        revision_box.markdown(revision_buf + "▌")

                elif etype == "revision_done":
                    n = event["round"]
                    if revision_box is not None:
                        revision_box.markdown(event["text"])
                    funny_status.info(f"Revision {n} complete!")

                elif etype == "final_done":
                    funny_status.success("🎭 Final play ready!")
                    gen.save_script("funny_play.txt")
                    st.success("Script saved to **funny_play.txt**")
                    st.download_button(
                        label="⬇️ Download Script",
                        data=event["text"],
                        file_name="funny_play.txt",
                        mime="text/plain",
                        key="funny_dl_script",
                    )
                    st.session_state["funny_script"] = event["text"]
                    st.session_state["funny_language"] = language_funny
                    st.session_state["funny_audio"] = None
                    st.session_state["funny_voice_map"] = None

                elif etype == "warning":
                    st.warning(event["text"])
                elif etype == "error":
                    st.error(event["text"])
                    break

    elif not st.session_state.get("funny_script"):
        st.info("Enter a theme above and click **🎭 Generate Funny Play** to begin.")

    elif st.session_state.get("funny_script") and not funny_btn:
        st.divider()
        st.markdown(st.session_state["funny_script"])

    if st.session_state.get("funny_script"):
        render_comedian_audio_section(
            "funny_script", "funny_audio", "funny_voice_map", "funny_language"
        )
