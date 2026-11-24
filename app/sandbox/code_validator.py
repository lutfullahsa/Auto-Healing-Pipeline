import ast
from typing import Tuple

class CodeSecurityValidator:
    """
    Static analyzer for Python code to detect forbidden imports, dunder attributes, 
    and forbidden function calls.
    """
    
    FORBIDDEN_MODULES = {
        'os', 'sys', 'subprocess', 'shutil', 'socket', 
        'requests', 'urllib', 'http'
    }
    
    FORBIDDEN_FUNCTIONS = {
        'eval', 'exec', 'compile', '__import__', 'open'
    }

    def validate_ast(self, python_code: str) -> Tuple[bool, str]:
        """
        Parses python code and checks for security violations.
        Returns (is_safe: bool, message: str)
        """
        try:
            tree = ast.parse(python_code)
        except SyntaxError as e:
            return False, f"Syntax Error: {e}"

        for node in ast.walk(tree):
            # Check for imports
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split('.')[0] in self.FORBIDDEN_MODULES:
                            return False, f"Güvenlik ihlali: Yasaklı modül import edildi: {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split('.')[0] in self.FORBIDDEN_MODULES:
                        return False, f"Güvenlik ihlali: Yasaklı modül import edildi: {node.module}"

            # Check for dunder attributes (potential sandbox escape)
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("__"):
                    return False, f"Güvenlik ihlali: Dunder attribute erişimi tespit edildi: {node.attr}"

            # Check for function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_FUNCTIONS:
                        return False, f"Güvenlik ihlali: Yasaklı fonksiyon çağrıldı: {node.func.id}"
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in self.FORBIDDEN_FUNCTIONS:
                        return False, f"Güvenlik ihlali: Yasaklı fonksiyon çağrıldı: {node.func.attr}"

        return True, "OK"

