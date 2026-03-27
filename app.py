"""No-Regression Test Status Dashboard — Streamlit app.

Presentation layer only. All business logic lives in services/ and main.py.
"""

import streamlit as st
import plotly.graph_objects as go

from config.settings import get_status_map
from main import fetch_from_link
from models.types import PlanData, RunData, StatusCounts

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QA Dashboard — No Regression",
    page_icon="🧪",
    layout="wide",
)

# ── Custom CSS (dark-mode) ──────────────────────────────────────────────────
st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        background: #1e1e2e;
        border: 1px solid #3a3a5c;
        border-radius: 12px;
        padding: 16px 20px;
    }
    div[data-testid="stMetric"] label {
        font-size: 0.85rem;
        color: #a0a0b8 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 700;
        color: #ffffff !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
        color: #8be9fd !important;
    }
    .section-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #e0e0ef;
        border-bottom: 2px solid #5B6ABF;
        padding-bottom: 4px;
        margin-top: 1.5rem;
        margin-bottom: 0.8rem;
    }
    .section-header a { color: #8be9fd; }
    footer { visibility: hidden; }
    section[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Credentials from Streamlit secrets ──────────────────────────────────────
tr_url = st.secrets["testrail"]["url"]
tr_user = st.secrets["testrail"]["user"]
tr_key = st.secrets["testrail"]["api_key"]

# ── Status helpers ──────────────────────────────────────────────────────────
_STATUS_MAP = get_status_map()
STATUS_COLORS = {v["label"]: v["color"] for v in _STATUS_MAP.values()}
STATUS_ORDER = ["Passed", "Failed", "Blocked", "Retest", "Untested"]


def _color(label: str) -> str:
    return STATUS_COLORS.get(label, "#999")


# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/test-passed.png", width=64)
    st.title("QA Dashboard")
    st.caption("Real-time No-Regression status from TestRail")
    st.markdown("---")
    st.subheader("Test Run / Plan Links")

    link_1 = st.text_input(
        "Link 1 (Manual or first run)",
        placeholder="https://…/plans/view/12345",
    )
    link_2 = st.text_input(
        "Link 2 (Automation or second run) — optional",
        placeholder="https://…/plans/view/67890",
    )
    fetch_btn = st.button("🔄  Fetch Status", use_container_width=True, type="primary")


# ── Rendering helpers ───────────────────────────────────────────────────────

def _progress_bar(pct: float, color: str = "#5B6ABF") -> str:
    return (
        f'<div style="background:#2a2a3d;border-radius:8px;height:22px;width:100%;overflow:hidden;margin:4px 0;">'
        f'<div style="background:{color};height:100%;width:{pct:.1f}%;border-radius:8px;'
        f'display:flex;align-items:center;justify-content:center;'
        f'color:white;font-size:0.75rem;font-weight:600;min-width:40px;">'
        f'{pct:.1f}%</div></div>'
    )


def _counts_to_dist(counts: StatusCounts) -> dict[str, int]:
    """Convert StatusCounts to ordered {label: count} for charts."""
    dist = _STATUS_MAP
    return counts.to_distribution(dist)


def _render_kpi(counts: StatusCounts) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Tests", counts.total)
    c2.metric("Executed", counts.executed)
    c3.metric("Passed", counts.passed)
    c4.metric("Failed", counts.failed)
    c5.metric("Blocked", counts.blocked)


def _render_donut(counts: StatusCounts, title: str) -> None:
    dist = counts.to_distribution(_STATUS_MAP)
    # Sort by STATUS_ORDER, then append custom statuses
    labels, values, colors = [], [], []
    for s in STATUS_ORDER:
        if dist.get(s, 0) > 0:
            labels.append(s)
            values.append(dist[s])
            colors.append(_color(s))
    for s, v in dist.items():
        if s not in STATUS_ORDER and v > 0:
            labels.append(s)
            values.append(v)
            colors.append(_color(s))

    if not values:
        return

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            marker=dict(colors=colors),
            textinfo="label+percent",
            textposition="outside",
            hovertemplate="<b>%{label}</b><br>Count: %{value}<br>%{percent}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#e0e0ef")),
        showlegend=False,
        margin=dict(t=60, b=20, l=20, r=20),
        height=340,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0ef"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_section(data: PlanData | RunData, label: str) -> None:
    """Render a full section for a plan or run."""
    name = data.name
    url = data.url

    if url:
        st.markdown(
            f'<p class="section-header">{label}: <a href="{url}" target="_blank">{name}</a></p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f'<p class="section-header">{label}: {name}</p>', unsafe_allow_html=True)

    _render_kpi(data.counts)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Completion** (executed / total)")
        st.markdown(_progress_bar(data.counts.progress, "#5B6ABF"), unsafe_allow_html=True)
    with col_b:
        st.markdown("**Pass Rate** (passed / executed)")
        st.markdown(_progress_bar(data.counts.pass_rate, "#4CAF50"), unsafe_allow_html=True)

    _render_donut(data.counts, f"Status Distribution — {name}")

    # Run-level breakdown for plans
    if isinstance(data, PlanData) and data.runs:
        st.markdown('<p class="section-header">Run Breakdown</p>', unsafe_allow_html=True)
        for run in data.runs:
            run_label = run.name or f"Run #{run.id}"
            pr = run.counts.pass_rate
            with st.expander(f"{run_label}  —  {run.counts.passed}/{run.counts.total} passed ({pr:.1f}%)"):
                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("Total", run.counts.total)
                rc2.metric("Passed", run.counts.passed)
                rc3.metric("Failed", run.counts.failed)
                rc4.metric("Blocked", run.counts.blocked)
                st.markdown(_progress_bar(run.counts.progress, "#5B6ABF"), unsafe_allow_html=True)
                if run.url:
                    st.markdown(f"[Open in TestRail]({run.url})")


def _render_comparison(d1: PlanData | RunData, d2: PlanData | RunData) -> None:
    """Side-by-side comparison with automation coverage analysis."""
    st.markdown('<p class="section-header">Comparison</p>', unsafe_allow_html=True)

    c1, c2 = d1.counts, d2.counts

    # Bar chart
    vals1 = [c1.passed, c1.failed, c1.blocked, c1.retest, c1.untested]
    vals2 = [c2.passed, c2.failed, c2.blocked, c2.retest, c2.untested]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=d1.name or "Run 1", x=STATUS_ORDER, y=vals1,
        marker_color="#5B6ABF", text=vals1, textposition="auto",
    ))
    fig.add_trace(go.Bar(
        name=d2.name or "Run 2", x=STATUS_ORDER, y=vals2,
        marker_color="#E87461", text=vals2, textposition="auto",
    ))
    fig.update_layout(
        barmode="group", title=dict(text="Status Comparison", font=dict(color="#e0e0ef")),
        height=380, margin=dict(t=60, b=40, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0ef"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Coverage analysis
    st.markdown('<p class="section-header">Automation Coverage Analysis</p>', unsafe_allow_html=True)

    total_combined = c1.total + c2.total
    ca, cb, cc = st.columns(3)
    ca.metric("Combined Test Cases", total_combined)
    cb.metric("Automation Executed", f"{c2.executed} / {c2.total}", f"{c2.progress:.1f}%")
    cc.metric("Manual Executed", f"{c1.executed} / {c1.total}", f"{c1.progress:.1f}%")

    auto_share = (c2.total / total_combined * 100) if total_combined else 0
    st.markdown("**Automation share of total test coverage**")
    st.markdown(_progress_bar(auto_share, "#E87461"), unsafe_allow_html=True)

    total_exec = c1.executed + c2.executed
    total_pass = c1.passed + c2.passed
    combined_pr = (total_pass / total_exec * 100) if total_exec else 0
    st.markdown("**Combined pass rate (all executed)**")
    st.markdown(_progress_bar(combined_pr, "#4CAF50"), unsafe_allow_html=True)

    # Comparison table
    st.table({
        "Metric": ["Total Tests", "Executed", "Passed", "Failed", "Blocked", "Retest",
                    "Completion %", "Pass Rate %"],
        d1.name or "Run 1": [
            c1.total, c1.executed, c1.passed, c1.failed, c1.blocked, c1.retest,
            f"{c1.progress:.1f}%", f"{c1.pass_rate:.1f}%",
        ],
        d2.name or "Run 2": [
            c2.total, c2.executed, c2.passed, c2.failed, c2.blocked, c2.retest,
            f"{c2.progress:.1f}%", f"{c2.pass_rate:.1f}%",
        ],
    })


# ── Main ─────────────────────────────────────────────────────────────────────
st.markdown("## 🧪 No-Regression Test Status Dashboard")

if fetch_btn:
    if not link_1:
        st.warning("Please provide at least one TestRail run/plan link.")
        st.stop()

    try:
        with st.spinner("Fetching data from TestRail…"):
            d1 = fetch_from_link(link_1.strip(), tr_url, tr_user, tr_key)
            d2 = fetch_from_link(link_2.strip(), tr_url, tr_user, tr_key) if link_2.strip() else None
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        st.stop()

    st.session_state["data1"] = d1
    st.session_state["data2"] = d2

# Render from session state
data1 = st.session_state.get("data1")
data2 = st.session_state.get("data2")

if data1 is None:
    st.info("👈 Enter at least one TestRail run/plan link in the sidebar, then click **Fetch Status**.")
else:
    if data2:
        tab1, tab2, tab3 = st.tabs(["📋 Run 1", "📋 Run 2", "📊 Comparison"])
        with tab1:
            _render_section(data1, "Run 1")
        with tab2:
            _render_section(data2, "Run 2")
        with tab3:
            _render_comparison(data1, data2)
    else:
        _render_section(data1, "Run")
