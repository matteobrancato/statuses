"""No-Regression Test Status Dashboard — Streamlit app."""

import streamlit as st
import plotly.graph_objects as go

from testrail_client import (
    TestRailClient,
    fetch_from_link,
    STATUS_MAP,
)

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QA Dashboard — No Regression",
    page_icon="🧪",
    layout="wide",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Cards — dark mode friendly */
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
    /* Section headers */
    .section-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #e0e0ef;
        border-bottom: 2px solid #5B6ABF;
        padding-bottom: 4px;
        margin-top: 1.5rem;
        margin-bottom: 0.8rem;
    }
    .section-header a {
        color: #8be9fd;
    }
    /* Hide default Streamlit footer */
    footer {visibility: hidden;}
    /* Sidebar styling */
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Read credentials from Streamlit secrets ──────────────────────────────────
tr_url = st.secrets["testrail"]["url"]
tr_user = st.secrets["testrail"]["user"]
tr_key = st.secrets["testrail"]["api_key"]

# ── Sidebar — links ─────────────────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://img.icons8.com/fluency/96/test-passed.png",
        width=64,
    )
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


# ── Helpers ──────────────────────────────────────────────────────────────────
STATUS_COLORS = {s["label"]: s["color"] for s in STATUS_MAP.values()}

# Consistent order for statuses
STATUS_ORDER = ["Passed", "Failed", "Blocked", "Retest", "Untested"]


def _status_color(label: str) -> str:
    return STATUS_COLORS.get(label, "#999")


def render_donut(data: dict, title: str) -> go.Figure:
    """Render a donut chart of status distribution."""
    labels = []
    values = []
    colors = []
    for s in STATUS_ORDER:
        if data["status_counts"].get(s, 0) > 0:
            labels.append(s)
            values.append(data["status_counts"][s])
            colors.append(_status_color(s))
    # Any custom statuses not in STATUS_ORDER
    for s, v in data["status_counts"].items():
        if s not in STATUS_ORDER and v > 0:
            labels.append(s)
            values.append(v)
            colors.append(_status_color(s))

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
        title=dict(text=title, font=dict(size=16)),
        showlegend=False,
        margin=dict(t=60, b=20, l=20, r=20),
        height=340,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_progress_bar(pct: float, color: str = "#5B6ABF") -> str:
    """HTML progress bar."""
    return f"""
    <div style="background:#e8e8e8;border-radius:8px;height:22px;width:100%;overflow:hidden;margin:4px 0;">
      <div style="background:{color};height:100%;width:{pct:.1f}%;border-radius:8px;
                  display:flex;align-items:center;justify-content:center;
                  color:white;font-size:0.75rem;font-weight:600;min-width:40px;">
        {pct:.1f}%
      </div>
    </div>
    """


def render_kpi_row(data: dict):
    """Render the top KPI metrics row."""
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Tests", data["total"])
    c2.metric("Executed", data["executed"])
    c3.metric("Passed", data["passed"])
    c4.metric("Failed", data["failed"])
    c5.metric("Blocked", data["blocked"])


def render_section(data: dict, label: str):
    """Render a full section for a plan/run."""
    name = data.get("name", label)
    url = data.get("url", "")

    if url:
        st.markdown(f'<p class="section-header">{label}: <a href="{url}" target="_blank">{name}</a></p>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p class="section-header">{label}: {name}</p>', unsafe_allow_html=True)

    render_kpi_row(data)

    # Progress bars
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Completion** (executed / total)")
        st.markdown(render_progress_bar(data["completion"], "#5B6ABF"), unsafe_allow_html=True)
    with col_b:
        st.markdown("**Pass Rate** (passed / executed)")
        st.markdown(render_progress_bar(data["pass_rate"], "#4CAF50"), unsafe_allow_html=True)

    # Donut chart
    fig = render_donut(data, f"Status Distribution — {name}")
    st.plotly_chart(fig, use_container_width=True)

    # Run-level breakdown for plans
    if data.get("type") == "plan" and data.get("runs"):
        st.markdown(f'<p class="section-header">Run Breakdown</p>', unsafe_allow_html=True)
        for run in data["runs"]:
            run_url = run.get("url", "")
            run_name = run.get("suite_name") or run.get("name", f"Run #{run['run_id']}")
            link_html = f'<a href="{run_url}" target="_blank">{run_name}</a>' if run_url else run_name

            with st.expander(f"{run_name}  —  {run['passed']}/{run['total']} passed ({run['pass_rate']:.1f}%)"):
                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("Total", run["total"])
                rc2.metric("Passed", run["passed"])
                rc3.metric("Failed", run["failed"])
                rc4.metric("Blocked", run["blocked"])
                st.markdown(render_progress_bar(run["completion"], "#5B6ABF"), unsafe_allow_html=True)
                if run_url:
                    st.markdown(f"[Open in TestRail]({run_url})")


def render_comparison(data1: dict, data2: dict):
    """Side-by-side comparison and automation coverage analysis."""
    st.markdown('<p class="section-header">Comparison</p>', unsafe_allow_html=True)

    # Side-by-side bar chart
    categories = STATUS_ORDER
    vals1 = [data1["status_counts"].get(c, 0) for c in categories]
    vals2 = [data2["status_counts"].get(c, 0) for c in categories]
    colors1 = [_status_color(c) for c in categories]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name=data1.get("name", "Run 1"),
            x=categories,
            y=vals1,
            marker_color="#5B6ABF",
            text=vals1,
            textposition="auto",
        )
    )
    fig.add_trace(
        go.Bar(
            name=data2.get("name", "Run 2"),
            x=categories,
            y=vals2,
            marker_color="#E87461",
            text=vals2,
            textposition="auto",
        )
    )
    fig.update_layout(
        barmode="group",
        title="Status Comparison",
        height=380,
        margin=dict(t=60, b=40, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Coverage analysis
    st.markdown('<p class="section-header">Automation Coverage Analysis</p>', unsafe_allow_html=True)

    total_combined = data1["total"] + data2["total"]
    auto_executed = data2["executed"]
    manual_executed = data1["executed"]
    auto_passed = data2["passed"]
    manual_passed = data1["passed"]

    ca, cb, cc = st.columns(3)
    ca.metric(
        "Combined Test Cases",
        total_combined,
    )
    cb.metric(
        "Automation Executed",
        f"{auto_executed} / {data2['total']}",
        f"{data2['completion']:.1f}%",
    )
    cc.metric(
        "Manual Executed",
        f"{manual_executed} / {data1['total']}",
        f"{data1['completion']:.1f}%",
    )

    # Coverage gauge
    if data1["total"] > 0:
        automation_coverage = (data2["total"] / (data1["total"] + data2["total"])) * 100
    else:
        automation_coverage = 0

    st.markdown("**Automation share of total test coverage**")
    st.markdown(render_progress_bar(automation_coverage, "#E87461"), unsafe_allow_html=True)

    st.markdown("**Combined pass rate (all executed)**")
    total_exec = auto_executed + manual_executed
    total_pass = auto_passed + manual_passed
    combined_pass_rate = (total_pass / total_exec * 100) if total_exec > 0 else 0
    st.markdown(render_progress_bar(combined_pass_rate, "#4CAF50"), unsafe_allow_html=True)

    # Comparison table
    comp_data = {
        "Metric": ["Total Tests", "Executed", "Passed", "Failed", "Blocked", "Retest", "Completion %", "Pass Rate %"],
        data1.get("name", "Run 1"): [
            data1["total"], data1["executed"], data1["passed"], data1["failed"],
            data1["blocked"], data1["retest"], f'{data1["completion"]:.1f}%', f'{data1["pass_rate"]:.1f}%',
        ],
        data2.get("name", "Run 2"): [
            data2["total"], data2["executed"], data2["passed"], data2["failed"],
            data2["blocked"], data2["retest"], f'{data2["completion"]:.1f}%', f'{data2["pass_rate"]:.1f}%',
        ],
    }
    st.table(comp_data)


# ── Main ─────────────────────────────────────────────────────────────────────
st.markdown("## 🧪 No-Regression Test Status Dashboard")

if fetch_btn:
    if not link_1:
        st.warning("Please provide at least one TestRail run/plan link.")
        st.stop()

    client = TestRailClient(tr_url.rstrip("/"), tr_user, tr_key)

    try:
        with st.spinner("Fetching data from TestRail…"):
            data1 = fetch_from_link(client, link_1.strip())
            data2 = fetch_from_link(client, link_2.strip()) if link_2.strip() else None
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        st.stop()

    # Store in session so it persists across reruns
    st.session_state["data1"] = data1
    st.session_state["data2"] = data2

# Render from session state
data1 = st.session_state.get("data1")
data2 = st.session_state.get("data2")

if data1 is None:
    st.info("👈 Enter at least one TestRail run/plan link in the sidebar, then click **Fetch Status**.")
else:
    if data2:
        tab1, tab2, tab3 = st.tabs(["📋 Run 1", "📋 Run 2", "📊 Comparison"])
        with tab1:
            render_section(data1, "Run 1")
        with tab2:
            render_section(data2, "Run 2")
        with tab3:
            render_comparison(data1, data2)
    else:
        render_section(data1, "Run")
