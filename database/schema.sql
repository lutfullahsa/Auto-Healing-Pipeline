CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_name VARCHAR(255) NOT NULL,
    preferred_language VARCHAR(2) DEFAULT 'TR' CHECK (preferred_language IN ('TR', 'EN')),
    subscription_tier VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pipelines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    source_type VARCHAR(100),
    target_type VARCHAR(100),
    active_version_id UUID,
    auto_heal_enabled BOOLEAN DEFAULT TRUE,
    status VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pipeline_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pipeline_id UUID NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    python_code TEXT NOT NULL,
    expected_schema JSONB,
    created_by VARCHAR(255),
    heal_reason TEXT,
    sandbox_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pipeline_id, version_number)
);

ALTER TABLE pipelines ADD CONSTRAINT fk_active_version 
FOREIGN KEY (active_version_id) REFERENCES pipeline_versions(id) ON DELETE SET NULL;

CREATE TABLE execution_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pipeline_id UUID NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES pipeline_versions(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    status VARCHAR(50),
    rows_processed INTEGER,
    error_traceback TEXT,
    detected_schema_diff JSONB,
    sample_corrupted_rows JSONB,
    execution_duration_ms INTEGER,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE heal_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_log_id UUID NOT NULL REFERENCES execution_logs(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    old_version_id UUID NOT NULL REFERENCES pipeline_versions(id) ON DELETE CASCADE,
    new_version_id UUID REFERENCES pipeline_versions(id) ON DELETE SET NULL,
    llm_model_used VARCHAR(100),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    sandbox_test_passed BOOLEAN DEFAULT FALSE,
    sandbox_output TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pipelines_tenant_id ON pipelines(tenant_id);
CREATE INDEX idx_pipeline_versions_tenant_id ON pipeline_versions(tenant_id);
CREATE INDEX idx_execution_logs_tenant_id ON execution_logs(tenant_id);
CREATE INDEX idx_heal_events_tenant_id ON heal_events(tenant_id);
