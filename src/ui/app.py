"""Streamlit UI for the AI Data Analyst Agent.

Connects to the FastAPI backend for all data operations.
Provides an interactive interface for all 3 capabilities.
"""

import json
import time
import uuid

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests

# API configuration
API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="AI Data Analyst Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown(
    """
<style>
    .main-header { font-size: 2.5rem; font-weight: bold; color: #1f77b4; }
    .sub-header { font-size: 1.2rem; color: #666; margin-bottom: 2rem; }
    .metric-card { background: #f0f2f6; padding: 1rem; border-radius: 0.5rem; }
    .insight-high { border-left: 4px solid #ff4b4b; padding-left: 1rem; }
    .insight-medium { border-left: 4px solid #ffa421; padding-left: 1rem; }
    .insight-info { border-left: 4px solid #00cc96; padding-left: 1rem; }
</style>
""",
    unsafe_allow_html=True,
)


def api_get(endpoint: str):
    """Make GET request to API."""
    try:
        response = requests.get(f"{API_BASE}{endpoint}", timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


def api_post(endpoint: str, data: dict):
    """Make POST request to API."""
    try:
        response = requests.post(f"{API_BASE}{endpoint}", json=data, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


# Sidebar
with st.sidebar:
    st.markdown("<div class='main-header'>🤖 AI Analyst</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sub-header'>Natural Language Data Analysis</div>",
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # Audience selector
    audience = st.selectbox(
        "Audience",
        ["executive", "manager", "analyst", "engineer"],
        help="Who is this analysis for?",
    )

    st.markdown("---")

    # Schema info
    with st.expander("📋 Database Schema"):
        schema_data = api_get("/schema")
        if schema_data:
            st.markdown("**Tables:**")
            for table in schema_data.get("tables", []):
                st.text(f"  • {table}")

            st.markdown("**Metrics:**")
            for metric in schema_data.get("metrics", []):
                st.text(f"  • {metric}")

            st.markdown("**Dimensions:**")
            for dim in schema_data.get("dimensions", []):
                st.text(f"  • {dim}")

    # Feedback stats
    with st.expander("📊 System Stats"):
        stats = api_get("/feedback/stats")
        if stats:
            st.metric("Total Queries", stats.get("total_queries", 0))
            st.metric("Success Rate", f"{stats.get('success_rate', 0) * 100:.1f}%")

    st.markdown("---")

    # Upload Data
    st.markdown("### 📁 Upload Data")

    uploaded = st.file_uploader(
        "Upload CSV, Excel, Parquet, or JSON", type=["csv", "xlsx", "parquet", "json"]
    )

    if uploaded:
        with st.spinner("Processing..."):
            files = {"file": (uploaded.name, uploaded.getvalue())}
            try:
                response = requests.post(f"{API_BASE}/upload", files=files, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    st.success(f"✅ Loaded {data['table_name']} ({data['rows']} rows)")
                    # Refresh schema after upload
                    st.rerun()
                else:
                    st.error(f"❌ Failed: {response.text}")
            except Exception as e:
                st.error(f"Error: {e}")


# Main content
st.markdown(
    "<div class='main-header'>AI Data Analyst Agent</div>", unsafe_allow_html=True
)
st.markdown(
    "<div class='sub-header'>Ask questions about your data in plain English</div>",
    unsafe_allow_html=True,
)

# Query input
user_query = st.text_input(
    "What would you like to know?",
    placeholder="e.g., Show me total revenue by region, or Why are North region sales declining?",
    key="query_input",
)

if user_query:
    query_id = str(uuid.uuid4())

    with st.status("🔄 Analyzing...", expanded=True) as status:
        start_time = time.time()

        # Call API
        response = api_post(
            "/query",
            {
                "query": user_query,
                "audience": audience,
            },
        )

        if not response:
            status.update(label="❌ Analysis Failed", state="error")
            st.stop()

        route = response.get("route", "UNKNOWN")
        status.update(label=f"✅ Analysis Complete ({route})", state="complete")

        # Display results
        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown("### 📈 Results")

            # Data table
            data = response.get("data", [])
            if data:
                df = pd.DataFrame(data)
                st.dataframe(df, use_container_width=True)

                # CSV export
                csv = df.to_csv(index=False)
                st.download_button(
                    "📥 Download CSV",
                    csv,
                    f"analysis_{query_id[:8]}.csv",
                    "text/csv",
                    key=f"csv_{query_id}",
                )

        with col2:
            st.markdown("### ℹ️ Query Info")
            st.code(response.get("sql", ""), language="sql")
            st.metric("Rows", response.get("rows_returned", 0))
            st.metric("Time", f"{response.get('execution_time_ms', 0):.0f}ms")

            if response.get("warnings"):
                st.warning(response["warnings"])

        # Visualization (if applicable)
        if route == "VISUALIZATION" and response.get("visualization"):
            st.markdown("---")
            st.markdown("### 📊 Visualization")
            viz_data = response["visualization"]
            if viz_data.get("figure_json"):
                fig = go.Figure(json.loads(viz_data["figure_json"]))
                st.plotly_chart(fig, use_container_width=True)
            elif response.get("visualization_error"):
                st.error(f"Visualization error: {response['visualization_error']}")

        # Analysis insights (if applicable)
        if route == "ANALYSIS":
            st.markdown("---")
            st.markdown("### 💡 Insights")

            insights = response.get("insights", [])
            for insight in insights:
                severity = insight.get("severity", "info")
                css_class = f"insight-{severity}"
                st.markdown(
                    f"<div class='{css_class}'>"
                    f"<strong>{insight.get('title', '')}</strong><br/>"
                    f"{insight.get('description', '')}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # Narrative
            st.markdown("### 📝 Executive Summary")
            st.markdown(response.get("formatted", response.get("narrative", "")))

        # Feedback
        st.markdown("---")
        st.markdown("### 👍 Was this helpful?")

        feedback_col1, feedback_col2, feedback_col3 = st.columns(3)

        with feedback_col1:
            if st.button("👍 Good", key=f"good_{query_id}"):
                api_post(
                    "/feedback",
                    {
                        "query_id": query_id,
                        "user_query": user_query,
                        "sql": response.get("sql", ""),
                        "route": route,
                        "success": True,
                        "user_rating": 5,
                    },
                )
                st.success("Thanks for your feedback!")

        with feedback_col2:
            if st.button("👎 Needs Improvement", key=f"bad_{query_id}"):
                api_post(
                    "/feedback",
                    {
                        "query_id": query_id,
                        "user_query": user_query,
                        "sql": response.get("sql", ""),
                        "route": route,
                        "success": True,
                        "user_rating": 2,
                    },
                )
                st.info("Thanks! We'll use this to improve.")

        with feedback_col3:
            comment = st.text_input("Comment (optional)", key=f"comment_{query_id}")
            if comment and st.button("Submit", key=f"submit_comment_{query_id}"):
                api_post(
                    "/feedback",
                    {
                        "query_id": query_id,
                        "user_query": user_query,
                        "sql": response.get("sql", ""),
                        "route": route,
                        "success": True,
                        "user_comment": comment,
                    },
                )


# Dashboard builder section
st.markdown("---")
st.markdown("### 🎯 Quick Dashboards")

with st.expander("Create Dashboard"):
    schema_data = api_get("/schema")
    if schema_data:
        metric_choice = st.selectbox("Metric", schema_data.get("metrics", []))
        dimension_choice = st.selectbox("Dimension", schema_data.get("dimensions", []))

        if st.button("Create Dashboard"):
            dashboard = api_post(
                "/dashboard/create",
                {
                    "metric": metric_choice,
                    "dimension": dimension_choice,
                },
            )
            if dashboard:
                st.success(f"Created: {dashboard['title']}")
                for chart in dashboard.get("charts", []):
                    st.markdown(f"- **{chart['title']}** ({chart['type']})")

st.markdown("---")
st.caption(
    "AI Data Analyst Agent v2.0 — Built with Semantic Layer + Multi-Agent Insights"
)
