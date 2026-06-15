from src.db.manager import DBManager
from src.agent.llm_client import LLMClient
from src.agent.planner import Planner
from src.agent.coder import Coder
from src.agent.router import Router
from src.agent.sandbox import Sandbox
from src.safety.validator import SQLSafetyValidator

def test_e2e():
    print("Starting E2E verification...")

    # 1. Setup
    db = DBManager()
    llm_client = LLMClient(provider="mock")
    planner = Planner(llm_client)
    coder = Coder(llm_client)
    router = Router(llm_client)
    sandbox = Sandbox()
    validator = SQLSafetyValidator(allowed_tables=set(db.get_table_names()))

    user_query = "Show me all sales in the North region"
    print(f"User Query: {user_query}")

    # 2. Route
    route = router.route(user_query)
    print(f"Route: {route}")

    # 3. Plan
    schema = db.get_schema()
    plan = planner.generate_plan(user_query, schema)
    print(f"Plan: {plan}")

    # 4. Code Gen
    sql = coder.generate_sql(user_query, plan, schema)
    print(f"Generated SQL: {sql}")

    # 5. Validate
    validation = validator.validate(sql)
    print(f"SQL Safe: {validation['safe']}")
    assert validation['safe'] == True

    # 6. Execute
    df = db.execute_query(sql)
    print("Query Result:")
    print(df)
    assert len(df) > 0

    print("E2E Verification Successful!")

if __name__ == "__main__":
    test_e2e()
