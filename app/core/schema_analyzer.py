import pandas as pd
from typing import Any

class SchemaAnalyzer:
    """
    Pandas DataFrame şeması ile beklenen şemayı karşılaştıran analiz motoru.
    """
    
    def analyze_dataframe(self, df: pd.DataFrame, expected_schema: dict[str, str]) -> dict[str, Any]:
        actual_columns = set(df.columns)
        expected_columns = set(expected_schema.keys())
        
        missing_columns = list(expected_columns - actual_columns)
        new_columns = list(actual_columns - expected_columns)
        type_mismatches = {}
        
        common_columns = actual_columns.intersection(expected_columns)
        
        for col in common_columns:
            expected_type = str(expected_schema[col]).strip().lower()
            actual_type = str(df[col].dtype).strip().lower()

            if actual_type != expected_type:
                type_mismatches[col] = {
                    "expected": expected_type,
                    "actual": actual_type
                }
        
        return {
            "has_diff": len(missing_columns) > 0 or len(new_columns) > 0 or len(type_mismatches) > 0,
            "missing_columns": missing_columns,
            "new_columns": new_columns,
            "type_mismatches": type_mismatches
        }
