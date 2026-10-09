import ast
from pathlib import Path
import unittest


class ApiContractTests(unittest.TestCase):
    def test_audit_response_keeps_structured_results_field(self):
        source = Path(__file__).resolve().parents[1] / "backend/app/schemas.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        response = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AuditResponse")
        fields = {node.target.id for node in response.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
        self.assertIn("audit_results", fields)

    def test_audit_response_exposes_compatible_lifecycle(self):
        source = Path(__file__).resolve().parents[1] / "backend/app/schemas.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        response = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AuditResponse")
        fields = {node.target.id for node in response.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
        self.assertIn("audit_lifecycle", fields)
