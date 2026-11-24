import logging
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.database_models import Tenant, Pipeline, PipelineVersion, ExecutionLog, HealEvent
from app.agent.patch_generator import AIPatchGenerator
from app.sandbox.docker_runner import DockerSandboxRunner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SelfHealingOrchestrator:
    def __init__(self, max_retries: int = 3):
        self.patch_generator = AIPatchGenerator()
        self.sandbox_runner = DockerSandboxRunner()
        self.max_retries = max_retries

    def heal_execution_error(self, db: Session, execution_log_id: UUID, tenant_id: UUID) -> HealEvent:
        # 1. Fetch records
        log = db.query(ExecutionLog).filter(
            ExecutionLog.id == execution_log_id, 
            ExecutionLog.tenant_id == tenant_id
        ).first()
        if not log:
            raise ValueError(f"ExecutionLog {execution_log_id} for tenant {tenant_id} not found.")

        pipeline = db.query(Pipeline).filter(Pipeline.id == log.pipeline_id).first()
        old_version = db.query(PipelineVersion).filter(PipelineVersion.id == log.version_id).first()
        tenant = db.query(Tenant).filter(Tenant.id == log.tenant_id).first()

        if not pipeline.auto_heal_enabled:
            raise PermissionError("Auto-healing is disabled for this pipeline.")

        # 2. Update pipeline status
        pipeline.status = "HEALING"
        db.commit()

        previous_sandbox_error = None
        total_prompt_tokens = 0
        total_completion_tokens = 0
        
        for attempt in range(self.max_retries):
            logger.info(f"Attempt {attempt + 1} for execution log {execution_log_id}")

            # 3. Generate patch
            proposal = self.patch_generator.generate_patch(
                broken_code=old_version.python_code,
                expected_schema=old_version.expected_schema,
                error_traceback=log.error_traceback,
                schema_diff=log.detected_schema_diff,
                sample_rows=log.sample_corrupted_rows,
                language=tenant.preferred_language,
                previous_sandbox_error=previous_sandbox_error
            )
            
            total_prompt_tokens += proposal.prompt_tokens
            total_completion_tokens += proposal.completion_tokens

            # 4. Test in sandbox
            sandbox_result = self.sandbox_runner.run_etl_test(
                python_code=proposal.fixed_code,
                sample_rows=log.sample_corrupted_rows or [],
                expected_schema=old_version.expected_schema
            )

            if sandbox_result.passed:
                # Success: Create new version
                max_ver = db.query(func.max(PipelineVersion.version_number)).filter(
                    PipelineVersion.pipeline_id == pipeline.id
                ).scalar()
                
                new_version = PipelineVersion(
                    pipeline_id=pipeline.id,
                    tenant_id=pipeline.tenant_id,
                    version_number=(max_ver or 0) + 1,
                    python_code=proposal.fixed_code,
                    expected_schema=old_version.expected_schema,
                    created_by="AI_AGENT",
                    heal_reason=proposal.heal_reason,
                    sandbox_verified=True
                )
                db.add(new_version)
                db.flush() # Needed for ID

                pipeline.active_version_id = new_version.id
                pipeline.status = "IDLE"
                log.status = "HEALED"
                
                heal_event = HealEvent(
                    execution_log_id=log.id,
                    tenant_id=log.tenant_id,
                    old_version_id=old_version.id,
                    new_version_id=new_version.id,
                    llm_model_used=proposal.llm_model,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    sandbox_test_passed=True,
                    sandbox_output="OK"
                )
                db.add(heal_event)
                db.commit()
                return heal_event

            else:
                previous_sandbox_error = sandbox_result.output
                logger.warning(f"Attempt {attempt + 1} failed: {previous_sandbox_error}")

        # If all retries failed
        pipeline.status = "FAILED"
        heal_event = HealEvent(
            execution_log_id=log.id,
            tenant_id=log.tenant_id,
            old_version_id=old_version.id,
            new_version_id=None,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            sandbox_test_passed=False,
            sandbox_output=previous_sandbox_error
        )
        db.add(heal_event)
        db.commit()
        return heal_event
