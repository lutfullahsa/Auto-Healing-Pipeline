import base64
import json
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from uuid import uuid4
from sqlalchemy import func
from app.core.pii_masker import PIIMasker
from app.core.error_capture import ErrorCaptureEngine
from app.sandbox.code_validator import CodeSecurityValidator
from app.core.schema_analyzer import SchemaAnalyzer
from app.agent.self_healer import SelfHealingOrchestrator
from app.agent.patch_generator import AIPatchGenerator, PatchProposal
from app.sandbox.docker_runner import DockerSandboxRunner, SandboxResult
from app.models.database_models import Tenant, Pipeline, PipelineVersion, ExecutionLog, HealEvent

def test_pii_masker_functionality():
    masker = PIIMasker()
    data = "TCKN: 12345678901, Email: test@example.com, Phone: 05551234567, IBAN: TR330006100519786457841326, CC: 4532-1234-5678-9012"
    masked = masker.mask_text(data)
    
    # Assertions based on requirement
    assert "12345678901" not in masked
    assert "test@example.com" not in masked
    assert "05551234567" not in masked
    assert "TR330006100519786457841326" not in masked
    assert "4532-1234-5678-9012" not in masked

def test_error_capture_masks_and_stores_sample_rows():
    engine = ErrorCaptureEngine()
    db = MagicMock()
    tenant_id, pipeline_id, version_id = uuid4(), uuid4(), uuid4()
    df = pd.DataFrame({"email": ["private@example.com"], "password": ["secret"]})

    log = engine.capture_and_log(
        db=db,
        tenant_id=tenant_id,
        pipeline_id=pipeline_id,
        version_id=version_id,
        exception=Exception("failed"),
        df=df,
        expected_schema={"email": "str", "password": "str"},
        duration_ms=10
    )

    assert log.sample_corrupted_rows == [{
        "email": "[MASKED_EMAIL]",
        "password": "[MASKED_SENSITIVE]"
    }]
    db.add.assert_called_once_with(log)

def test_docker_runner_uses_base64_environment_without_host_volume():
    runner = DockerSandboxRunner()
    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b'AUTOHEAL_RESULT:[{"value":1,"extra":"ok"}]\n'

    with patch("app.sandbox.docker_runner.docker.from_env", return_value=client):
        result = runner.run_etl_test(
            python_code="import pandas as pd\ndef transform(df): return df",
            sample_rows=[{"value": 1, "extra": "ok"}],
            expected_schema={"value": "int64"}
        )

    call = client.containers.run.call_args
    payload = json.loads(
        base64.b64decode(call.kwargs["environment"]["PAYLOAD_B64"])
    )
    assert payload["python_code"] == "import pandas as pd\ndef transform(df): return df"
    assert payload["sample_rows"] == [{"value": 1, "extra": "ok"}]
    assert payload["expected_schema"] == {"value": "int64"}
    assert "volumes" not in call.kwargs
    assert call.kwargs["command"][:2] == ["python", "-c"]
    assert result.passed is True
    container.remove.assert_called_once_with(force=True)

def test_code_security_validator():
    validator = CodeSecurityValidator()
    
    assert validator.validate_ast("import os")[0] is False
    assert validator.validate_ast("eval('1+1')")[0] is False
    assert validator.validate_ast("x.__subclasses__()")[0] is False
    assert validator.validate_ast("import pandas as pd; df = pd.DataFrame()")[0] is True

def test_schema_analyzer():
    analyzer = SchemaAnalyzer()
    df = pd.DataFrame({"col1": [1, 2], "col3": [1.5, 2.5]})
    expected_schema = {"col1": "int", "col2": "str"}
    
    diff = analyzer.analyze_dataframe(df, expected_schema)
    
    assert diff["has_diff"] is True
    assert "col2" in diff["missing_columns"]
    assert "col3" in diff["new_columns"]

def test_schema_analyzer_normalizes_exact_dtype_names():
    analyzer = SchemaAnalyzer()
    df = pd.DataFrame({"value": [1.0]})

    diff = analyzer.analyze_dataframe(df, {"value": " FLOAT64 "})

    assert diff["type_mismatches"] == {}
    assert diff["has_diff"] is False

def test_patch_generator_parses_json_object_from_surrounding_text():
    generator = AIPatchGenerator()
    generator._client = MagicMock()
    response = generator._client.chat.completions.create.return_value
    response.choices[0].message.content = (
        'Result:\n```json\n{"fixed_code": "return {\\"value\\": \\"}\\"}", '
        '"heal_reason": "Düzeltildi"}\n```'
    )
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 20

    proposal = generator.generate_patch("broken", {}, "error")

    assert proposal.fixed_code == 'return {"value": "}"}'
    assert proposal.heal_reason == "Düzeltildi"
    generator._client.chat.completions.create.assert_called_once()
    assert "response_format" not in generator._client.chat.completions.create.call_args.kwargs

def test_patch_generator_uses_currency_fallback_when_api_call_fails(caplog):
    generator = AIPatchGenerator()
    generator._client = MagicMock()
    generator._client.chat.completions.create.side_effect = Exception("404 quota error")
    broken_code = (
        "import pandas as pd\n"
        "def transform(df: pd.DataFrame) -> pd.DataFrame:\n"
        "    df['net_amount'] = df['amount'].astype(float) * 1.20\n"
        "    return df\n"
    )

    proposal = generator.generate_patch(broken_code, {}, "could not convert string to float")

    assert "pd.to_numeric" in proposal.fixed_code
    assert "df['net_amount'] = df['amount'].astype(float) * 1.20" in proposal.fixed_code
    assert proposal.llm_model == "currency-fallback"
    assert proposal.prompt_tokens == 0
    assert "Patch generation API call failed" in caplog.text

@patch('app.agent.self_healer.AIPatchGenerator')
@patch('app.agent.self_healer.DockerSandboxRunner')
def test_orchestrator_e2e_mock(mock_runner_cls, mock_generator_cls):
    mock_db = MagicMock()
    
    # Mock return instances
    mock_generator = mock_generator_cls.return_value
    mock_runner = mock_runner_cls.return_value
    
    # Define proposal and result
    proposal = PatchProposal(
        fixed_code="def transform(df): return df",
        heal_reason="Kolon eklendi",
        llm_model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=50
    )
    mock_generator.generate_patch.return_value = proposal
    
    sandbox_result = SandboxResult(
        passed=True,
        output="OK",
        execution_time_ms=120
    )
    mock_runner.run_etl_test.return_value = sandbox_result
    
    # Mock DB query objects
    mock_log = MagicMock(spec=ExecutionLog)
    mock_log.id = uuid4()
    mock_log.pipeline_id = uuid4()
    mock_log.tenant_id = uuid4()
    mock_log.version_id = uuid4()
    mock_log.sample_corrupted_rows = []
    
    mock_pipeline = MagicMock(spec=Pipeline)
    mock_pipeline.auto_heal_enabled = True
    
    mock_version = MagicMock(spec=PipelineVersion)
    mock_version.python_code = "broken"
    mock_version.expected_schema = {}
    
    mock_tenant = MagicMock(spec=Tenant)
    mock_tenant.preferred_language = "TR"
    
    # Setup query chains
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_log, mock_pipeline, mock_version, mock_tenant
    ]
    # For the max version query
    mock_db.query.return_value.filter.return_value.scalar.return_value = 1
    
    orchestrator = SelfHealingOrchestrator()
    
    # Execute
    heal_event = orchestrator.heal_execution_error(mock_db, mock_log.id, mock_log.tenant_id)
    
    # Assert
    assert heal_event.sandbox_test_passed is True
    assert heal_event.prompt_tokens == 100
    assert heal_event.llm_model_used == "gpt-4o"
    
    # Verify DB commit
    mock_db.commit.assert_called()

