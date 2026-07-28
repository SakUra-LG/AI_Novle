"""Alternative DashScope transport for environments where Python TLS fails."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List


def call_qwen_via_curl(
    messages: List[Dict[str, str]],
    *,
    api_key: str,
    model: str = "qwen-turbo",
    temperature: float = 0.8,
    top_p: float = 0.85,
    repetition_penalty: float = 1.05,
    max_tokens: int | None = None,
    timeout_s: float = 120,
) -> Dict[str, Any]:
    """Call DashScope's native generation endpoint through the curl binary.

    The returned object matches the dictionary shape consumed by the existing
    DashScope SDK call sites.
    """
    if not str(api_key or "").strip():
        raise RuntimeError("DashScope API key is empty")
    endpoint = os.getenv(
        "DASHSCOPE_HTTP_ENDPOINT",
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
    )
    parameters: Dict[str, Any] = {
        "result_format": "message",
        "temperature": float(temperature),
        "top_p": float(top_p),
        "repetition_penalty": float(repetition_penalty),
    }
    if max_tokens is not None:
        parameters["max_tokens"] = int(max_tokens)
    payload = {"model": model, "input": {"messages": messages}, "parameters": parameters}

    with tempfile.TemporaryDirectory(prefix="qwen-curl-") as temp_dir:
        request_path = Path(temp_dir) / "request.json"
        response_path = Path(temp_dir) / "response.json"
        request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        command = [
            os.getenv("CURL_EXE", "curl"),
            "--silent",
            "--show-error",
            "--fail-with-body",
            "--max-time",
            str(max(1, int(timeout_s))),
            "--request",
            "POST",
            endpoint,
            "--header",
            f"Authorization: Bearer {api_key}",
            "--header",
            "Content-Type: application/json",
            "--data-binary",
            f"@{request_path}",
            "--output",
            str(response_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s + 10)
        raw = response_path.read_text(encoding="utf-8") if response_path.exists() else ""
        if completed.returncode != 0:
            detail = raw or completed.stderr.strip()
            raise RuntimeError(f"DashScope curl transport failed ({completed.returncode}): {detail[:500]}")
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DashScope curl transport returned invalid JSON: {raw[:500]}") from exc
        if not isinstance(response, dict):
            raise RuntimeError("DashScope curl transport returned a non-object response")
        if response.get("code") and not response.get("output"):
            raise RuntimeError(f"DashScope error {response.get('code')}: {response.get('message')}")
        return response
