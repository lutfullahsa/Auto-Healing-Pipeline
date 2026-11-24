import traceback
import pandas as pd
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.database_models import ExecutionLog
from app.core.pii_masker import PIIMasker
from app.core.schema_analyzer import SchemaAnalyzer

class ErrorCaptureEngine:
    def __init__(self):
        self.pii_masker = PIIMasker()
        self.schema_analyzer = SchemaAnalyzer()

    def capture_and_mask(self, error_text: str) -> str:
        return self.pii_masker.mask_text(error_text)

    def capture_and_log(
        self, 
        db: Session, 
        tenant_id: UUID, 
        pipeline_id: UUID, 
        version_id: UUID, 
        exception: Exception, 
        df: pd.DataFrame, 
        expected_schema: dict, 
        duration_ms: int
    ) -> ExecutionLog:
        # PII Masking of error
        masked_error = self.pii_masker.mask_text(str(exception))
        
        # Analyze Schema Difference
        diff = self.schema_analyzer.analyze_dataframe(df, expected_schema)
        sample_rows = self.pii_masker.mask_records(
            df.head(5).to_dict(orient="records")
        )
        
        # Create Log
        log = ExecutionLog(
            pipeline_id=pipeline_id,
            version_id=version_id,
            tenant_id=tenant_id,
            status="FAILED",
            error_traceback=masked_error,
            detected_schema_diff=diff,
            sample_corrupted_rows=sample_rows,
            execution_duration_ms=duration_ms
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

