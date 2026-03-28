"""No-Regression Test Status Dashboard — Streamlit app.

Select a Business Unit → see baseline coverage, active regression status,
and detailed run breakdown, all fetched live from TestRail.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from config.settings import get_status_map, load_config
from main import get_regression_dashboard, fetch_from_link
from models.types import PlanData, RunData


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_dashboard(bu: str, url: str, user: str, key: str) -> dict:
    """Cache dashboard results for 1 hour (baseline rarely changes)."""
    return get_regression_dashboard(bu, url, user, key)

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QA Dashboard — No Regression",
    page_icon="🧪",
    layout="wide",
)

# ── Custom CSS (dark-mode) ──────────────────────────────────────────────────
st.markdown("""
<style>
div[data-testid="stMetric"] {
    background: #1e1e2e; border: 1px solid #3a3a5c;
    border-radius: 12px; padding: 16px 20px;
}
div[data-testid="stMetric"] label {
    font-size: 0.85rem; color: #a0a0b8 !important;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.8rem; font-weight: 700; color: #ffffff !important;
}
.section-header {
    font-size: 1.1rem; font-weight: 600; color: #e0e0ef;
    border-bottom: 2px solid #5B6ABF;
    padding-bottom: 4px; margin-top: 1.5rem; margin-bottom: 0.8rem;
}
.section-header a { color: #8be9fd; text-decoration: none; }
.section-header a:hover { text-decoration: underline; }
.badge {
    display: inline-block; padding: 3px 12px; border-radius: 12px;
    font-weight: 600; font-size: 0.8rem; margin-right: 6px;
}
.badge-active { background: #27ae60; color: white; }
.badge-completed { background: #555; color: #ccc; }
.badge-regression { background: #e74c3c; color: white; }
.badge-smoke { background: #f39c12; color: white; }
.badge-other { background: #3498db; color: white; }
.badge-none { background: #444; color: #888; }
footer { visibility: hidden; }
section[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)

# ── Credentials ─────────────────────────────────────────────────────────────
TR_URL = st.secrets["testrail"]["url"]
TR_USER = st.secrets["testrail"]["user"]
TR_KEY = st.secrets["testrail"]["api_key"]

# ── Status helpers ──────────────────────────────────────────────────────────
_SMAP = get_status_map()
_SCOLORS = {v["label"]: v["color"] for v in _SMAP.values()}
_SORDER = ["Passed", "Failed", "Blocked", "Retest", "Untested"]


def _color(label: str) -> str:
    return _SCOLORS.get(label, "#999")


# ── Sidebar ─────────────────────────────────────────────────────────────────
cfg = load_config()
bu_names = list(cfg["business_units"].keys())

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/test-passed.png", width=64)
    st.title("QA Dashboard")
    st.caption("Real-time No-Regression status from TestRail")
    st.markdown("---")

    selected_bu = st.selectbox("Business Unit", bu_names, index=0)

    st.markdown("---")
    mode = st.radio(
        "Mode",
        ["Auto-discover", "Manual link"],
        index=0,
        help="Auto-discover finds recent regression/smoke plans automatically.",
    )

    manual_link = ""
    manual_link_2 = ""
    if mode == "Manual link":
        manual_link = st.text_input("Link 1 (Plan or Run)", placeholder="https://…/plans/view/12345")
        manual_link_2 = st.text_input("Link 2 — optional", placeholder="https://…/plans/view/67890")

    fetch_btn = st.button("🔄  Load Dashboard", use_container_width=True, type="primary")


# ── Rendering helpers ───────────────────────────────────────────────────────

def _bar(pct: float, color: str = "#5B6ABF") -> str:
    """Render an HTML progress bar."""
    return (
        f'<div style="background:#2a2a3d;border-radius:8px;height:24px;width:100%;'
        f'overflow:hidden;margin:4px 0;">'
        f'<div style="background:{color};height:100%;width:{max(pct, 0):.1f}%;border-radius:8px;'
        f'display:flex;align-items:center;justify-content:center;'
        f'color:white;font-size:0.75rem;font-weight:600;min-width:44px;">'
        f'{pct:.1f}%</div></div>'
    )


def _donut(labels: list, values: list, colors: list, title: str, h: int = 300) -> None:
    if not values or sum(values) == 0:
        return
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.55,
        marker=dict(colors=colors),
        textinfo="label+percent", textposition="outside",
        hovertemplate="<b>%{label}</b><br>Count: %{value}<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#e0e0ef")),
        showlegend=False, margin=dict(t=50, b=10, l=10, r=10), height=h,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0ef"),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Render: Coverage ────────────────────────────────────────────────────────

def render_coverage(cov: dict) -> None:
    st.markdown('<p class="section-header">Baseline Coverage</p>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Cases", f"{cov['total']:,}")
    c2.metric("Regression Cases", f"{cov['regression']:,}")
    c3.metric("Automated", f"{cov['automated_total']:,}")
    c4.metric("Automation %", f"{cov['coverage_pct']:.1f}%")

    bd = cov.get("automation_breakdown", {})
    if any(bd.values()):
        st.markdown("**Automation Breakdown**")
        b1, b2, b3 = st.columns(3)
        b1.metric("Java", bd.get("java", 0))
        b2.metric("Testim Desktop", bd.get("testim_desktop", 0))
        b3.metric("Testim Mobile", bd.get("testim_mobile", 0))

    bl = cov.get("automation_backlog", {})
    if bl and bl.get("total", 0) > 0:
        st.markdown('<p class="section-header">Automation Backlog</p>', unsafe_allow_html=True)
        st.caption("Cases marked as *Ready to be automated*")
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Total Backlog", f"{bl.get('total', 0):,}")
        l2.metric("Java", bl.get("java", 0))
        l3.metric("Testim Desktop", bl.get("testim_desktop", 0))
        l4.metric("Testim Mobile", bl.get("testim_mobile", 0))

    auto = cov["automated_total"]
    manual = cov["total"] - auto
    if cov["total"] > 0:
        _donut(["Automated", "Manual"], [auto, manual], ["#5B6ABF", "#9E9E9E"],
               "Automation vs Manual", 260)


# ── Render: Plans overview ──────────────────────────────────────────────────

def render_plans(plans: list[dict], country_names: dict) -> None:
    if not plans:
        st.info("No regression or smoke plans found in the configured timeframe.")
        return

    st.markdown('<p class="section-header">Recent Plans</p>', unsafe_allow_html=True)

    for plan in plans:
        ptype = plan.get("plan_type", "other")
        badge_cls = {"regression": "badge-regression", "smoke": "badge-smoke"}.get(ptype, "badge-other")
        status_cls = "badge-active" if plan.get("is_active") else "badge-completed"

        st.markdown(
            f'<span class="badge {badge_cls}">{ptype.upper()}</span>'
            f'<span class="badge {status_cls}">{"ACTIVE" if plan.get("is_active") else "COMPLETED"}</span>'
            f' &nbsp; <a href="{plan["url"]}" target="_blank" '
            f'style="color:#8be9fd;font-weight:600;font-size:1rem;">{plan["name"]}</a>',
            unsafe_allow_html=True,
        )

        # Plan-level KPI row
        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
        pc1.metric("Total", plan["total"])
        pc2.metric("Passed", plan["passed"])
        pc3.metric("Failed", plan["failed"])
        pc4.metric("Blocked", plan["blocked"])
        pc5.metric("Progress", f"{plan['progress']:.1f}%")

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Completion**")
            st.markdown(_bar(plan["progress"], "#5B6ABF"), unsafe_allow_html=True)
        with col_b:
            st.markdown("**Pass Rate**")
            pr = plan["pass_rate"]
            c = "#4CAF50" if pr >= 80 else "#FF9800" if pr >= 50 else "#F44336"
            st.markdown(_bar(pr, c), unsafe_allow_html=True)

        # Runs inside this plan
        runs = plan.get("runs", [])
        if runs:
            _render_plan_runs(runs, country_names)

        st.markdown("---")


def _render_plan_runs(runs: list[dict], country_names: dict) -> None:
    """Render individual runs inside a plan as expandable rows."""
    for run in runs:
        country_label = country_names.get(run["country"], run["country"])
        platform = run["platform"].title()
        rtype = run["run_type"].title()
        status = run["status"]

        # Build summary line
        status_icon = "🟢" if status == "active" else "✅"
        pct = run["progress"]
        pr = run["pass_rate"]

        summary = (
            f"{status_icon} **{run['name']}** — "
            f"{country_label} · {platform} · {rtype} — "
            f"{run['passed']}/{run['total']} passed ({pr:.0f}%)"
        )

        with st.expander(summary):
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            mc1.metric("Total", run["total"])
            mc2.metric("Passed", run["passed"])
            mc3.metric("Failed", run["failed"])
            mc4.metric("Blocked", run["blocked"])
            mc5.metric("Retest", run["retest"])
            mc6.metric("Untested", run["untested"])

            ca, cb = st.columns(2)
            with ca:
                st.markdown("**Completion**")
                st.markdown(_bar(pct, "#5B6ABF"), unsafe_allow_html=True)
            with cb:
                st.markdown("**Pass Rate**")
                c = "#4CAF50" if pr >= 80 else "#FF9800" if pr >= 50 else "#F44336"
                st.markdown(_bar(pr, c), unsafe_allow_html=True)

            st.markdown(f"[Open in TestRail]({run['url']})")


# ── Render: Manual link mode ────────────────────────────────────────────────

def render_manual(data: PlanData | RunData, label: str) -> None:
    url = data.url
    name = data.name

    if url:
        st.markdown(
            f'<p class="section-header">{label}: '
            f'<a href="{url}" target="_blank">{name}</a></p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f'<p class="section-header">{label}: {name}</p>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", data.counts.total)
    c2.metric("Executed", data.counts.executed)
    c3.metric("Passed", data.counts.passed)
    c4.metric("Failed", data.counts.failed)
    c5.metric("Blocked", data.counts.blocked)

    ca, cb = st.columns(2)
    with ca:
        st.markdown("**Completion**")
        st.markdown(_bar(data.counts.progress, "#5B6ABF"), unsafe_allow_html=True)
    with cb:
        st.markdown("**Pass Rate**")
        st.markdown(_bar(data.counts.pass_rate, "#4CAF50"), unsafe_allow_html=True)

    # Donut
    dist = data.counts.to_distribution(_SMAP)
    labels, values, colors = [], [], []
    for s in _SORDER:
        if dist.get(s, 0) > 0:
            labels.append(s); values.append(dist[s]); colors.append(_color(s))
    for s, v in dist.items():
        if s not in _SORDER and v > 0:
            labels.append(s); values.append(v); colors.append(_color(s))
    _donut(labels, values, colors, f"Status Distribution — {name}")

    # Run breakdown for plans
    if isinstance(data, PlanData) and data.runs:
        st.markdown('<p class="section-header">Run Breakdown</p>', unsafe_allow_html=True)
        for run in data.runs:
            pr = run.counts.pass_rate
            with st.expander(f"{run.name} — {run.counts.passed}/{run.counts.total} passed ({pr:.0f}%)"):
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Total", run.counts.total)
                r2.metric("Passed", run.counts.passed)
                r3.metric("Failed", run.counts.failed)
                r4.metric("Blocked", run.counts.blocked)
                st.markdown(_bar(run.counts.progress, "#5B6ABF"), unsafe_allow_html=True)
                if run.url:
                    st.markdown(f"[Open in TestRail]({run.url})")


def render_comparison(d1: PlanData | RunData, d2: PlanData | RunData) -> None:
    st.markdown('<p class="section-header">Comparison</p>', unsafe_allow_html=True)
    c1, c2 = d1.counts, d2.counts

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=d1.name or "Run 1", x=_SORDER,
        y=[c1.passed, c1.failed, c1.blocked, c1.retest, c1.untested],
        marker_color="#5B6ABF", textposition="auto",
    ))
    fig.add_trace(go.Bar(
        name=d2.name or "Run 2", x=_SORDER,
        y=[c2.passed, c2.failed, c2.blocked, c2.retest, c2.untested],
        marker_color="#E87461", textposition="auto",
    ))
    fig.update_layout(
        barmode="group", title=dict(text="Status Comparison", font=dict(color="#e0e0ef")),
        height=380, margin=dict(t=60, b=40, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0ef"),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.table({
        "Metric": ["Total", "Executed", "Passed", "Failed", "Blocked",
                    "Completion %", "Pass Rate %"],
        d1.name or "Run 1": [c1.total, c1.executed, c1.passed, c1.failed, c1.blocked,
                              f"{c1.progress:.1f}%", f"{c1.pass_rate:.1f}%"],
        d2.name or "Run 2": [c2.total, c2.executed, c2.passed, c2.failed, c2.blocked,
                              f"{c2.progress:.1f}%", f"{c2.pass_rate:.1f}%"],
    })


# ── Main ─────────────────────────────────────────────────────────────────────

st.markdown("## 🧪 No-Regression Test Status Dashboard")

if fetch_btn:
    if mode == "Auto-discover":
        try:
            with st.spinner(f"Fetching data for **{selected_bu}**… this may take a minute."):
                result = get_regression_dashboard(selected_bu, TR_URL, TR_USER, TR_KEY)
            st.session_state["dashboard"] = result
            st.session_state["mode"] = "auto"
            st.session_state.pop("manual_data", None)
        except Exception as e:
            st.error(f"Error: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()
    else:
        if not manual_link:
            st.warning("Provide at least one TestRail link.")
            st.stop()
        bu_cfg = cfg["business_units"].get(selected_bu, {})
        bu_code = bu_cfg.get("bu_code", "")
        known_countries = list(bu_cfg.get("countries", {}).keys())
        try:
            with st.spinner("Fetching…"):
                d1 = fetch_from_link(manual_link.strip(), TR_URL, TR_USER, TR_KEY,
                                     bu_code=bu_code, known_countries=known_countries)
                d2 = (
                    fetch_from_link(manual_link_2.strip(), TR_URL, TR_USER, TR_KEY,
                                    bu_code=bu_code, known_countries=known_countries)
                    if manual_link_2.strip() else None
                )
            st.session_state["manual_data"] = (d1, d2)
            st.session_state["mode"] = "manual"
            st.session_state.pop("dashboard", None)
        except Exception as e:
            st.error(f"Error: {e}")
            st.stop()

# ── Render ───────────────────────────────────────────────────────────────────
current_mode = st.session_state.get("mode")

if current_mode == "auto":
    dashboard = st.session_state.get("dashboard")
    if dashboard:
        bu = dashboard["business_unit"]
        active = dashboard["active_regression"]

        if active:
            st.markdown(
                f'**{bu}** &nbsp; <span class="badge badge-active">REGRESSION ACTIVE</span>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'**{bu}** &nbsp; <span class="badge badge-none">NO ACTIVE REGRESSION</span>',
                unsafe_allow_html=True)

        tab_cov, tab_plans = st.tabs(["📊 Coverage", "🏃 Plans & Runs"])
        with tab_cov:
            render_coverage(dashboard["coverage"])
        with tab_plans:
            render_plans(dashboard["plans"], dashboard.get("country_names", {}))

elif current_mode == "manual":
    manual = st.session_state.get("manual_data")
    if manual:
        d1, d2 = manual
        if d2:
            t1, t2, t3 = st.tabs(["📋 Run 1", "📋 Run 2", "📊 Comparison"])
            with t1:
                render_manual(d1, "Run 1")
            with t2:
                render_manual(d2, "Run 2")
            with t3:
                render_comparison(d1, d2)
        else:
            render_manual(d1, "Run")

else:
    st.info(
        "👈 Select a **Business Unit** and click **Load Dashboard** to see "
        "coverage and regression status.\n\n"
        "Or switch to **Manual link** to analyze a specific plan/run."
    )
