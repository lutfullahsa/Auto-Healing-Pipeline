from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Any
from pydantic import BaseModel
from contextlib import asynccontextmanager
import pandas as pd

from app.database import engine, get_db
from app.models.database_models import Base, Tenant, Pipeline, PipelineVersion, ExecutionLog, HealEvent
from app.agent.self_healer import SelfHealingOrchestrator
from app.sandbox.docker_runner import DockerSandboxRunner
from app.core.error_capture import ErrorCaptureEngine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown

app = FastAPI(
    title="AutoHeal Pipeline API",
    description="Multi-Tenant Autonomous ETL & Schema Self-Healing SaaS Platform",
    lifespan=lifespan
)

# Pydantic Schemas
class TenantCreate(BaseModel):
    company_name: str
    preferred_language: str = "TR"
    subscription_tier: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "company_name": "ACME Holding",
                "preferred_language": "TR",
                "subscription_tier": "ENTERPRISE"
            }
        }
    }

class PipelineCreate(BaseModel):
    tenant_id: UUID
    name: str
    python_code: str
    expected_schema: dict[str, str]

    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "name": "E-Commerce Financial Transformation",
                "python_code": "import pandas as pd\n\ndef transform(df: pd.DataFrame) -> pd.DataFrame:\n    df['net_amount'] = df['amount'].astype(float) * 1.20\n    return df",
                "expected_schema": {
                    "net_amount": "float64"
                }
            }
        }
    }

class ExecuteRequest(BaseModel):
    tenant_id: UUID
    rows: list[dict[str, Any]]

    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "rows": [
                    {
                        "amount": "1.500,00 TL",
                        "tutar": "1.500,00 TL",
                        "tckn": "12345678901",
                        "email": "ahmet@ornek.com"
                    }
                ]
            }
        }
    }

# Endpoints
@app.get("/health")
def health_check():
    return {"status": "online"}

@app.post("/api/v1/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(tenant: TenantCreate, db: Session = Depends(get_db)):
    db_tenant = Tenant(**tenant.model_dump())
    db.add(db_tenant)
    db.commit()
    db.refresh(db_tenant)
    return db_tenant

@app.post("/api/v1/pipelines", status_code=status.HTTP_201_CREATED)
def create_pipeline(pipeline_req: PipelineCreate, db: Session = Depends(get_db)):
    # 1. Create Pipeline
    db_pipeline = Pipeline(
        tenant_id=pipeline_req.tenant_id,
        name=pipeline_req.name,
        status="IDLE"
    )
    db.add(db_pipeline)
    db.flush() # Get ID
    
    # 2. Create Initial Version
    version = PipelineVersion(
        pipeline_id=db_pipeline.id,
        tenant_id=pipeline_req.tenant_id,
        version_number=1,
        python_code=pipeline_req.python_code,
        expected_schema=pipeline_req.expected_schema,
        created_by="USER",
        sandbox_verified=True
    )
    db.add(version)
    db.flush()
    
    db_pipeline.active_version_id = version.id
    db.commit()
    return db_pipeline

@app.post("/api/v1/pipelines/{pipeline_id}/execute")
def execute_pipeline(pipeline_id: UUID, req: ExecuteRequest, db: Session = Depends(get_db)):
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id, Pipeline.tenant_id == req.tenant_id).first()
    if not pipeline or not pipeline.active_version_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    version = db.query(PipelineVersion).filter(PipelineVersion.id == pipeline.active_version_id).first()
    
    runner = DockerSandboxRunner()
    result = runner.run_etl_test(version.python_code, req.rows, version.expected_schema)
    
    if result.passed:
        log = ExecutionLog(pipeline_id=pipeline.id, version_id=version.id, tenant_id=req.tenant_id, status="SUCCESS")
        db.add(log)
        db.commit()
        return {"status": "SUCCESS", "execution_id": log.id}
    else:
        # Capture error and attempt healing
        df = pd.DataFrame(req.rows)
        error_engine = ErrorCaptureEngine()
        log = error_engine.capture_and_log(
            db=db, 
            tenant_id=req.tenant_id, 
            pipeline_id=pipeline.id, 
            version_id=version.id, 
            exception=RuntimeError(result.output), 
            df=df, 
            expected_schema=version.expected_schema, 
            duration_ms=result.execution_time_ms
        )
        
        if pipeline.auto_heal_enabled:
            healer = SelfHealingOrchestrator()
            heal_event = healer.heal_execution_error(db, log.id, req.tenant_id)
            return {
                "status": "HEALING_TRIGGERED", 
                "heal_event_id": heal_event.id,
                "sandbox_test_passed": heal_event.sandbox_test_passed,
                "new_version_id": heal_event.new_version_id
            }
            
        return {"status": "FAILED", "error": result.output}

@app.get("/api/v1/pipelines/{pipeline_id}/heal-events")
def list_heal_events(pipeline_id: UUID, tenant_id: UUID, db: Session = Depends(get_db)):
    events = db.query(HealEvent).join(ExecutionLog, HealEvent.execution_log_id == ExecutionLog.id).filter(
        ExecutionLog.pipeline_id == pipeline_id,
        HealEvent.tenant_id == tenant_id
    ).all()
    return events

@app.post("/api/v1/demo/setup", status_code=status.HTTP_201_CREATED)
def demo_setup(db: Session = Depends(get_db)):
    """
    1-Click Demo Setup: Automatically provisions a sample tenant and a fragile ETL pipeline (v1)
    so you can immediately test autonomous PII masking, AI patching, and Docker sandbox verification.
    """
    db_tenant = Tenant(
        company_name="Demo Company",
        preferred_language="EN",
        subscription_tier="ENTERPRISE"
    )
    db.add(db_tenant)
    db.flush()

    db_pipeline = Pipeline(
        tenant_id=db_tenant.id,
        name="Demo ETL Pipeline",
        status="IDLE"
    )
    db.add(db_pipeline)
    db.flush()

    python_code = (
        "import pandas as pd\n\n"
        "def transform(df: pd.DataFrame) -> pd.DataFrame:\n"
        "    df['net_amount'] = df['amount'].astype(float) * 1.20\n"
        "    return df"
    )

    version = PipelineVersion(
        pipeline_id=db_pipeline.id,
        tenant_id=db_tenant.id,
        version_number=1,
        python_code=python_code,
        expected_schema={"net_amount": "float64"},
        created_by="USER",
        sandbox_verified=True
    )
    db.add(version)
    db.flush()

    db_pipeline.active_version_id = version.id
    db.commit()

    return {
        "tenant_id": db_tenant.id,
        "pipeline_id": db_pipeline.id,
        "message": "Demo environment ready"
    }