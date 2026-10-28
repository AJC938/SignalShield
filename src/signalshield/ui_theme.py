"""Central presentation styling for the Streamlit SignalShield interface."""
from __future__ import annotations

import base64

import streamlit as st


_CONNECTION_PATTERN = """<svg xmlns='http://www.w3.org/2000/svg' width='720' height='420' viewBox='0 0 720 420'>
<g fill='none' stroke='#087E8B' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' opacity='.30'>
<path d='M8 58h94l36-36h88l32 32h82l34-34h86l34 34h92l34-34h96'/>
<path d='M10 138h70l34 34h82l36-36h104l28 28h82l36-36h100l30 30h94'/>
<path d='M24 230h100l30-30h92l36 38h78l38-38h104l34 34h84l34-34h72'/>
<path d='M4 332h96l34-34h80l34 34h92l38-38h80l34 34h90l36-36h98'/>
<path d='M224 22v50l38 38v26M470 20v48l-32 32v36M160 200v36M400 222v-42M272 332v-54M590 166v48'/>
</g>
<g fill='#087E8B' opacity='.4'>
<circle cx='102' cy='58' r='3'/><circle cx='226' cy='22' r='3'/><circle cx='340' cy='54' r='3'/><circle cx='502' cy='20' r='3'/><circle cx='650' cy='54' r='3'/>
<circle cx='80' cy='138' r='3'/><circle cx='196' cy='172' r='3'/><circle cx='336' cy='136' r='3'/><circle cx='510' cy='128' r='3'/><circle cx='656' cy='168' r='3'/>
<circle cx='124' cy='230' r='3'/><circle cx='246' cy='200' r='3'/><circle cx='424' cy='200' r='3'/><circle cx='610' cy='234' r='3'/>
<circle cx='100' cy='332' r='3'/><circle cx='214' cy='298' r='3'/><circle cx='346' cy='332' r='3'/><circle cx='538' cy='328' r='3'/><circle cx='686' cy='296' r='3'/>
</g></svg>"""


def apply_ui_theme() -> None:
    """Apply a signal-network motif and larger, readable typography."""
    pattern = base64.b64encode(_CONNECTION_PATTERN.encode("utf-8")).decode("ascii")
    st.markdown(
        f"""<style>
        .stApp {{
            background-color: #F5F7FA;
            background-image:
                radial-gradient(ellipse at 50% 0%, rgba(8,126,139,.08), transparent 42%),
                url("data:image/svg+xml;base64,{pattern}");
            background-position: center, right 2rem top 7rem;
            background-size: auto, min(58vw, 720px) auto;
            background-repeat: no-repeat, repeat-y;
            background-attachment: fixed;
            font-size: 1.06rem;
        }}
        .stApp h1, .stApp h2, .stApp h3 {{ letter-spacing: -0.018em; color: #172B3A; }}
        .stApp [data-testid="stMarkdownContainer"] p {{ font-size: 1.06rem; line-height: 1.55; }}
        .stApp [data-testid="stWidgetLabel"] p {{ font-size: 1.02rem; }}
        .stApp input, .stApp textarea, .stApp button {{ font-size: 1.02rem; }}
        .signalshield-hero {{ text-align: center; padding: .35rem 0 .8rem; }}
        .signalshield-hero h1 {{ font-size: clamp(2.45rem, 5vw, 3.5rem); margin: 0; }}
        .signalshield-hero p {{ font-size: 1.18rem; margin: .35rem 0 0; color: #526575; }}
        .signal-flow {{ text-align: center; color: #087E8B; font-size: 1.05rem; font-weight: 700; letter-spacing: .07em; }}
        .signal-core {{ text-align: center; padding: .45rem 0 .1rem; }}
        .signal-core svg {{ width: 100%; max-width: 280px; height: auto; }}
        .stApp input[type="radio"] {{ accent-color: #087E8B; }}
        @media (max-width: 640px) {{
            .stApp {{ background-position: center, right top 8rem; background-size: auto, 100vw auto; }}
            .signalshield-hero p {{ font-size: 1rem; }}
        }}
        </style>""",
        unsafe_allow_html=True,
    )
