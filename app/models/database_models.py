from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Tenant(Base):
    __tablename__ = 'tenants'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), nullable=False)
    preferred_language = Column(String(2), default='TR')
    subscription_tier = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Pipeline(Base):
    __tablename__ = 'pipelines'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    source_type = Column(String(100))
    target_type = Column(String(100))
    active_version_id = Column(UUID(as_uuid=True), ForeignKey('pipeline_versions.id', use_alter=True, name="fk_active_version", ondelete="SET NULL"))
    auto_heal_enabled = Column(Boolean, default=True)
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class PipelineVersion(Base):
    __tablename__ = 'pipeline_versions'
    __table_args__ = (UniqueConstraint("pipeline_id", "version_number", name="uq_pipeline_version"),)
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(UUID(as_uuid=True), ForeignKey('pipelines.id', ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    python_code = Column(Text, nullable=False)
    expected_schema = Column(JSONB)
    created_by = Column(String(255))
    heal_reason = Column(Text)
    sandbox_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ExecutionLog(Base):
    __tablename__ = 'execution_logs'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(UUID(as_uuid=True), ForeignKey('pipelines.id', ondelete="CASCADE"), nullable=False)
    version_id = Column(UUID(as_uuid=True), ForeignKey('pipeline_versions.id', ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete="CASCADE"), nullable=False)
    status = Column(String(50))
    rows_processed = Column(Integer)
    error_traceback = Column(Text)
    detected_schema_diff = Column(JSONB)
    sample_corrupted_rows = Column(JSONB)
    execution_duration_ms = Column(Integer)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))

class HealEvent(Base):
    __tablename__ = 'heal_events'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_log_id = Column(UUID(as_uuid=True), ForeignKey('execution_logs.id', ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete="CASCADE"), nullable=False)
    old_version_id = Column(UUID(as_uuid=True), ForeignKey('pipeline_versions.id', ondelete="CASCADE"), nullable=False)
    new_version_id = Column(UUID(as_uuid=True), ForeignKey('pipeline_versions.id', ondelete="SET NULL"), nullable=True)
    llm_model_used = Column(String(100))
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    sandbox_test_passed = Column(Boolean, default=False)
    sandbox_output = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
