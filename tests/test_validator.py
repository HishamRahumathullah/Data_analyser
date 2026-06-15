import unittest
from src.safety.validator import SQLSafetyValidator

class TestSQLSafetyValidator(unittest.TestCase):
    def setUp(self):
        self.allowed_tables = {"sales", "customers"}
        self.validator = SQLSafetyValidator(allowed_tables=self.allowed_tables)

    def test_safe_query(self):
        query = "SELECT * FROM sales WHERE amount > 100"
        result = self.validator.validate(query)
        self.assertTrue(result['safe'])
        self.assertIn("sales", result['tables'])

    def test_unauthorized_table(self):
        query = "SELECT * FROM salaries"
        result = self.validator.validate(query)
        self.assertFalse(result['safe'])
        self.assertIn("Unauthorized table: salaries", result['errors'])

    def test_forbidden_operation(self):
        query = "DROP TABLE sales"
        result = self.validator.validate(query)
        self.assertFalse(result['safe'])
        self.assertIn("Forbidden operation: DROP", result['errors'])

    def test_multiple_statements(self):
        query = "SELECT * FROM sales; DROP TABLE customers;"
        result = self.validator.validate(query)
        self.assertFalse(result['safe'])
        self.assertIn("Forbidden operation: DROP", result['errors'])

    def test_read_only_insert(self):
        query = "INSERT INTO sales (amount) VALUES (100)"
        result = self.validator.validate(query)
        self.assertFalse(result['safe'])
        self.assertIn("Forbidden operation: INSERT", result['errors'])

if __name__ == '__main__':
    unittest.main()
