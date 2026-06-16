"""AI Copilot — natural-language interface over the analytics (grounded answers)."""
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402
from parksight.copilot import engine  # noqa: E402

st.set_page_config(page_title="ParkSight — Copilot", page_icon="🤖", layout="wide")
lib.inject_css()
if not lib.artifacts_exist():
    lib.no_data_warning()

lib.page_header("🤖 ParkSight Copilot",
                "Ask in plain English — answers are computed from the data, never hallucinated.")

has_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
has_gemini = bool(os.getenv("GOOGLE_API_KEY"))
has_key    = has_claude or has_gemini

if has_claude:
    st.caption("🟢 Claude NL understanding is ON (claude-sonnet-4-6) — questions are parsed by "
               "Claude, then executed on real analytics.")
elif has_gemini:
    st.caption("🟢 Gemini NL understanding is ON (gemini-1.5-flash) — questions are parsed by "
               "Gemini, then executed on real analytics.")
else:
    st.caption("🟡 Running the deterministic engine. Set **ANTHROPIC_API_KEY** or "
               "**GOOGLE_API_KEY** to enable AI free-form NL understanding. "
               "Either way, every number is grounded in the dataset.")

with st.sidebar:
    st.markdown("### 🔑 API Keys *(optional)*")
    st.caption("Set one to unlock AI-powered free-form questions. Both keys are session-only — never stored.")
    anthropic_input = st.text_input("Anthropic API Key", type="password",
                                    placeholder="sk-ant-...",
                                    value=os.getenv("ANTHROPIC_API_KEY", ""))
    gemini_input    = st.text_input("Google Gemini API Key", type="password",
                                    placeholder="AIza...",
                                    value=os.getenv("GOOGLE_API_KEY", ""))
    if anthropic_input:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_input
        has_claude = True; has_key = True
    if gemini_input:
        os.environ["GOOGLE_API_KEY"] = gemini_input
        if not has_claude:
            has_gemini = True; has_key = True

with st.expander("🔒 How this stays safe — the LLM can't hallucinate numbers or run code"):
    st.markdown(
        "ParkSight's copilot is **not** a chatbot wrapper. The chain is strict:\n\n"
        "```\n"
        "natural language\n"
        "   → STRICT ROUTER (Claude or rules) parses to {intent, params}\n"
        "   → GUARDRAIL: intent must be one of 8 whitelisted functions; only typed params survive\n"
        "   → DETERMINISTIC EXECUTION on precomputed analytics (H3 / PCIS / blind-spot lookups)\n"
        "   → human-readable dispatch brief built from the REAL returned numbers\n"
        "```\n"
        "The LLM only **selects an intent** — it never sees the database, writes SQL, or executes "
        "code, so it cannot fabricate a statistic. If Claude is unavailable the rule router takes "
        "over with identical grounding, so the demo never fails.")

st.markdown("**Try:**")
cols = st.columns(3)
for i, q in enumerate(engine.SUGGESTIONS):
    if cols[i % 3].button(q, key=f"sg{i}", use_container_width=True):
        st.session_state["pending"] = q

if "chat" not in st.session_state:
    st.session_state["chat"] = []

for role, content, extra in st.session_state["chat"]:
    with st.chat_message(role):
        st.markdown(content)
        if extra is not None:
            st.dataframe(extra, hide_index=True, use_container_width=True)

prompt = st.chat_input("Ask ParkSight…") or st.session_state.pop("pending", None)
if prompt:
    st.session_state["chat"].append(("user", prompt, None))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Analysing the data…"):
            res = engine.answer(prompt, use_ai=has_key)
        st.markdown(res["text"])
        if res["table"] is not None:
            st.dataframe(res["table"], hide_index=True, use_container_width=True)
        plan = res.get("plan")
        if plan:
            st.caption(f"🔒 parsed by {res.get('parser','router')} → executed "
                       f"`{plan['intent']}({', '.join(f'{k}={v!r}' for k, v in plan['params'].items())})` "
                       f"· engine: {res['engine']}")
        else:
            st.caption(f"engine: {res['engine']}")
    st.session_state["chat"].append(("assistant", res["text"], res["table"]))
