import streamlit as st
import pandas as pd
from src.db.manager import DBManager
from src.safety.validator import SQLSafetyValidator
from src.agent.llm_client import LLMClient
from src.agent.planner import Planner
from src.agent.coder import Coder
from src.agent.router import Router
from src.agent.sandbox import Sandbox
from src.agent.rag import SimpleRAG

# Initialize components
@st.cache_resource
def init_components():
    db = DBManager()
    llm_client = LLMClient(provider="mock") # Change to 'ollama' or 'vllm' for real use
    planner = Planner(llm_client)
    coder = Coder(llm_client)
    router = Router(llm_client)
    sandbox = Sandbox()
    rag = SimpleRAG()

    # Initialize RAG with schema and sample documentation
    schema = db.get_schema()
    rag.add_documents([
        {"source": "schema", "content": schema},
        {"source": "business_logic", "content": "The 'North' region includes NY, NJ, and CT."},
        {"source": "business_logic", "content": "Enterprise customers are those with more than 500 employees."}
    ])

    allowed_tables = set(db.get_table_names())
    validator = SQLSafetyValidator(allowed_tables=allowed_tables)

    return db, planner, coder, router, sandbox, validator, rag

db, planner, coder, router, sandbox, validator, rag = init_components()

st.set_page_config(page_title="AI Data Analyst Agent", layout="wide")

st.title("🤖 AI Data Analyst Agent")
st.markdown("---")

# Sidebar - Schema Info
with st.sidebar:
    st.header("Database Schema")
    st.text(db.get_schema())

# Main Interface
user_query = st.text_input("Ask a question about your data:", placeholder="e.g., Show me the total sales by region")

if user_query:
    with st.status("Analyzing...", expanded=True) as status:
        # 1. Routing
        st.write("Routing query...")
        route = router.route(user_query)
        st.write(f"Routed to: {route}")

        # 2. RAG Context Retrieval
        st.write("Retrieving context...")
        context = rag.get_context(user_query)
        with st.expander("Show Context"):
            st.text(context)

        # 3. Planning
        st.write("Generating plan...")
        plan = planner.generate_plan(user_query, context)
        st.expander("Show Plan").write(plan)

        # 3. Execution
        if route == "DATA_QUERY" or route == "VISUALIZATION":
            st.write("Generating SQL...")
            sql = coder.generate_sql(user_query, plan, schema)
            st.code(sql, language="sql")

            # Safety Check
            st.write("Validating SQL safety...")
            validation_result = validator.validate(sql)

            if validation_result['safe']:
                st.write("Executing query...")
                try:
                    df = db.execute_query(sql)
                    st.dataframe(df)

                    if route == "VISUALIZATION":
                        st.write("Generating visualization code...")
                        py_code = coder.generate_python(user_query, df.head().to_string(), plan)
                        st.code(py_code, language="python")

                        st.write("Executing visualization...")
                        result = sandbox.execute_python(py_code, df)
                        if result['success'] and result['figure']:
                            st.plotly_chart(result['figure'])
                        elif not result['success']:
                            st.error(f"Visualization error: {result['error']}")
                except Exception as e:
                    st.error(f"Execution error: {str(e)}")
            else:
                st.error(f"Unsafe SQL detected: {', '.join(validation_result['errors'])}")
        else:
            # General response
            st.write(plan)

        status.update(label="Analysis Complete!", state="complete", expanded=False)

st.markdown("---")
st.caption("AI Data Analyst Agent — June 2026 Edition")
