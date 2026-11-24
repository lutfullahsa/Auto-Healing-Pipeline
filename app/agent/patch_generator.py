import ast
import os
import json
import logging
import re
from typing import Any, Optional
from pydantic import BaseModel, Field
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PatchProposal(BaseModel):
    fixed_code: str
    heal_reason: str
    llm_model: str
    prompt_tokens: int
    completion_tokens: int

class AIPatchGenerator:
    def __init__(self, model_name: str = os.getenv("OPENAI_MODEL", "gemini-2.0-flash")):
        self.model_name = model_name
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL")
            )
        return self._client


    def _clean_code(self, code: str) -> str:
        # Remove markdown code blocks like ```python ... ```
        code = re.sub(r'^```python\s*', '', code, flags=re.IGNORECASE)
        code = re.sub(r'^```\s*', '', code)
        code = re.sub(r'\s*```$', '', code)
        return code.strip()

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        for start, char in enumerate(content):
            if char != "{":
                continue

            depth = 0
            in_string = False
            escaped = False
            for end in range(start, len(content)):
                char = content[end]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            result = json.loads(content[start:end + 1])
                        except json.JSONDecodeError:
                            break
                        if isinstance(result, dict):
                            return result
                        break

        raise ValueError("Model response did not contain a valid JSON object.")

    def _currency_fallback_code(self, broken_code: str) -> str:
        normalization = """import pandas as pd
import re
df = df.copy()

def _normalize_currency(value):
    text = str(value).strip()
    is_us_currency = bool(re.search(r"(?i)(?:USD|DOLLAR|\\$)", text))
    is_turkish_currency = bool(re.search(r"(?i)\\b(?:TL|TRY)\\b", text))
    text = re.sub(r"(?i)\\b(?:TL|TRY|USD|EUR|GBP|DOLAR|DOLLAR)\\b|\\$", "", text)
    text = re.sub(r"[^0-9,.\\-+]", "", text)

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if is_us_currency and re.fullmatch(r"-?\\d{1,3}(?:,\\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif is_turkish_currency and re.fullmatch(r"-?\\d{1,3}(?:\\.\\d{3})+", text):
        text = text.replace(".", "")

    return text

for column in df.select_dtypes(include=["object", "string"]).columns:
    values = df[column].astype("string")
    name = str(column).lower()
    is_monetary_column = any(
        term in name
        for term in ("amount", "tutar", "price", "cost", "total", "balance", "fiyat", "ucret")
    )
    has_currency = values.str.contains(
        r"(?i)\\b(?:TL|TRY|USD|EUR|GBP|DOLAR|DOLLAR)\\b|\\$", regex=True, na=False
    ).any()
    if is_monetary_column or has_currency:
        df[column] = pd.to_numeric(values.map(_normalize_currency), errors="coerce")
"""
        try:
            tree = ast.parse(broken_code)
        except SyntaxError:
            tree = None

        transform = next(
            (
                node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "transform" and node.body
            ),
            None
        ) if tree else None

        if transform:
            body_index = 1 if (
                isinstance(transform.body[0], ast.Expr)
                and isinstance(transform.body[0].value, ast.Constant)
                and isinstance(transform.body[0].value.value, str)
            ) else 0
            insertion_line = (
                transform.body[body_index].lineno - 1
                if body_index < len(transform.body)
                else transform.body[-1].end_lineno
            )
            lines = broken_code.splitlines(keepends=True)
            indentation_line = (
                lines[insertion_line]
                if insertion_line < len(lines)
                else lines[transform.body[0].lineno - 1]
            )
            indent = indentation_line[:len(indentation_line) - len(indentation_line.lstrip())]
            injected = "".join(
                f"{indent}{line}\n" if line else "\n"
                for line in normalization.splitlines()
            )
            lines.insert(insertion_line, injected)
            return "".join(lines)

        fallback_body = "".join(
            f"    {line}\n" if line else "\n"
            for line in normalization.splitlines()
        )
        return (
            "import pandas as pd\n\n"
            "def transform(df: pd.DataFrame) -> pd.DataFrame:\n"
            f"{fallback_body}"
            "    return df\n"
        )

    def generate_patch(
        self,
        broken_code: str,
        expected_schema: dict[str, str],
        error_traceback: str,
        schema_diff: Optional[dict[str, Any]] = None,
        sample_rows: Optional[list[dict[str, Any]]] = None,
        language: str = "TR",
        previous_sandbox_error: Optional[str] = None
    ) -> PatchProposal:
        
        system_instruction = (
            "You are an AI autonomous code fixer. "
            "1. Produce code that MUST follow the signature: 'def transform(df: pd.DataFrame) -> pd.DataFrame:'. "
            "2. Forbidden modules: os, sys, subprocess, requests, etc. Use only data processing libs: pandas, numpy, datetime, re. "
            "3. Return output strictly in JSON format: {'fixed_code': '...', 'heal_reason': '...'}. "
            f"4. 'heal_reason' must be in {language} language."
        )

        user_prompt = f"""
        Fix the following broken code which failed in the pipeline.
        Broken Code:
        {broken_code}
        
        Expected Schema: {expected_schema}
        Error Traceback: {error_traceback}
        Schema Diff: {schema_diff}
        Sample Rows: {sample_rows}
        """

        if previous_sandbox_error:
            user_prompt += f"\nPrevious Sandbox Error: {previous_sandbox_error}. Please address this specific error."

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1
            )
        except Exception:
            logger.exception("Patch generation API call failed; using currency fallback.")
            return PatchProposal(
                fixed_code=self._currency_fallback_code(broken_code),
                heal_reason=(
                    "API çağrısı başarısız oldu; para birimi biçimindeki metinler "
                    "normalize edilerek mevcut dönüşüm korundu."
                ),
                llm_model="currency-fallback",
                prompt_tokens=0,
                completion_tokens=0
            )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model response was empty.")
        result = self._parse_json_object(content)
        usage = response.usage

        return PatchProposal(
            fixed_code=self._clean_code(result["fixed_code"]),
            heal_reason=result["heal_reason"],
            llm_model=self.model_name,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens
        )
