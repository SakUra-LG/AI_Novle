"""Alternative DashScope transport for environments where Python TLS fails."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List

import requests


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
        ]
        curl_interface = os.getenv("DASHSCOPE_CURL_INTERFACE", "").strip()
        if curl_interface:
            command.extend(["--interface", curl_interface])
        curl_resolve = os.getenv("DASHSCOPE_CURL_RESOLVE", "").strip()
        if curl_resolve:
            command.extend(["--resolve", curl_resolve])
        curl_proxy = os.getenv("DASHSCOPE_CURL_PROXY", "").strip()
        if curl_proxy:
            command.extend(["--proxy", curl_proxy])
        command.extend(
            [
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
        )
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


def call_openai_compatible_via_curl(
    messages: List[Dict[str, str]],
    *,
    api_key: str,
    model: str,
    endpoint: str,
    temperature: float = 0.7,
    top_p: float = 0.82,
    max_tokens: int | None = None,
    timeout_s: float = 180,
) -> Dict[str, Any]:
    """Call an OpenAI-compatible chat-completions endpoint without an SDK.

    Secrets are supplied only through the caller's process environment and are
    never persisted.  Groq uses this transport through its documented
    ``/openai/v1/chat/completions`` endpoint.
    """
    if not str(api_key or "").strip():
        raise RuntimeError("OpenAI-compatible API key is empty")
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "top_p": float(top_p),
        "stream": False,
    }
    if "gpt-oss" in model.lower():
        # Preserve completion space for structured JSON on Groq's tight free
        # tier instead of spending most of it on hidden reasoning tokens.
        payload["reasoning_effort"] = os.getenv(
            "OPENAI_COMPATIBLE_REASONING_EFFORT", "low"
        ).strip() or "low"
    elif "qwen3" in model.lower():
        # Groq's Qwen 3.6 defaults to thinking mode.  Planner calls require a
        # compact JSON object, so hidden chain-of-thought would otherwise
        # consume the completion budget before the JSON begins.
        payload["reasoning_effort"] = "none"
        payload["response_format"] = {"type": "json_object"}
    elif "llama" in model.lower() and "prompt-guard" not in model.lower():
        payload["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        payload["max_completion_tokens"] = int(max_tokens)
    # Groq's OpenAI-compatible endpoint rejects DashScope's non-standard
    # ``enable_thinking`` field.  Its Qwen deployment is controlled through
    # ``reasoning_effort`` above instead.
    with tempfile.TemporaryDirectory(prefix="openai-compatible-curl-") as temp_dir:
        request_path = Path(temp_dir) / "request.json"
        response_path = Path(temp_dir) / "response.json"
        request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        command = [
            os.getenv("CURL_EXE", "curl"), "--silent", "--show-error", "--fail-with-body",
            "--max-time", str(max(1, int(timeout_s))),
        ]
        curl_proxy = os.getenv("OPENAI_COMPATIBLE_CURL_PROXY", "").strip()
        if curl_proxy:
            command.extend(["--proxy", curl_proxy])
        command.extend([
            "--request", "POST", endpoint,
            "--header", f"Authorization: Bearer {api_key}",
            "--header", "Content-Type: application/json",
            "--data-binary", f"@{request_path}", "--output", str(response_path),
        ])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s + 10)
        raw = response_path.read_text(encoding="utf-8") if response_path.exists() else ""
        if completed.returncode != 0:
            detail = raw or completed.stderr.strip()
            raise RuntimeError(
                f"OpenAI-compatible curl transport failed ({completed.returncode}): {detail[:500]}"
            )
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"OpenAI-compatible transport returned invalid JSON: {raw[:500]}"
            ) from exc
        if not isinstance(response, dict):
            raise RuntimeError("OpenAI-compatible transport returned a non-object response")
        if response.get("error"):
            raise RuntimeError(f"OpenAI-compatible API error: {str(response['error'])[:500]}")
        return response


def call_openai_compatible_via_requests(
    messages: List[Dict[str, str]],
    *,
    api_key: str,
    model: str,
    endpoint: str,
    temperature: float = 0.7,
    top_p: float = 0.82,
    max_tokens: int | None = None,
    timeout_s: float = 180,
) -> Dict[str, Any]:
    """OpenAI-compatible transport using Python/OpenSSL instead of Schannel.

    Some Windows proxy sessions make the system curl fail with
    ``SEC_E_NO_CREDENTIALS`` even though the same endpoint is healthy.  This
    path is used by the VectorEngine relay and keeps the bearer key in process
    memory rather than a command argument.
    """
    if not str(api_key or "").strip():
        raise RuntimeError("OpenAI-compatible API key is empty")
    stream_enabled = os.getenv("OPENAI_COMPATIBLE_STREAM", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "top_p": float(top_p),
        "stream": stream_enabled,
    }
    if max_tokens is not None:
        payload["max_completion_tokens"] = int(max_tokens)
    if "qwen3" in model.lower():
        payload["enable_thinking"] = False
    proxy = os.getenv("OPENAI_COMPATIBLE_CURL_PROXY", "").strip()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    session = requests.Session()
    # With no explicit proxy, make this a genuine Python/OpenSSL direct path;
    # otherwise requests may silently inherit a flaky desktop proxy from the
    # ambient HTTP(S)_PROXY variables.
    if not proxy:
        session.trust_env = False
    try:
        response = session.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            proxies=proxies,
            stream=stream_enabled,
            timeout=max(1.0, float(timeout_s)),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenAI-compatible requests transport failed: {exc}") from exc
    if not response.ok:
        raise RuntimeError(
            f"OpenAI-compatible requests transport HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
    if stream_enabled:
        content_parts: List[str] = []
        finish_reason: str | None = None
        response_model = model
        usage: Dict[str, Any] = {}
        try:
            for raw_line in response.iter_lines(decode_unicode=False):
                line = (
                    raw_line.decode("utf-8", errors="strict")
                    if isinstance(raw_line, bytes) else str(raw_line or "")
                ).strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                response_model = str(chunk.get("model") or response_model)
                if isinstance(chunk.get("usage"), dict):
                    usage = dict(chunk["usage"])
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] or {}
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if isinstance(piece, str):
                    content_parts.append(piece)
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice.get("finish_reason"))
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"OpenAI-compatible streaming transport failed: {exc}") from exc
        content = "".join(content_parts)
        if not content:
            raise RuntimeError("OpenAI-compatible streaming transport returned no content")
        return {
            "id": response.headers.get("x-request-id", "streamed-response"),
            "model": response_model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }],
            "usage": usage,
        }
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"OpenAI-compatible requests transport returned invalid JSON: {response.text[:500]}"
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError("OpenAI-compatible requests transport returned a non-object response")
    if result.get("error"):
        raise RuntimeError(f"OpenAI-compatible API error: {str(result['error'])[:500]}")
    return result


def list_openai_compatible_models_via_curl(
    *, api_key: str, endpoint: str, timeout_s: float = 30,
) -> List[str]:
    """Return model IDs visible to one OpenAI-compatible API key."""
    if not str(api_key or "").strip():
        raise RuntimeError("OpenAI-compatible API key is empty")
    with tempfile.TemporaryDirectory(prefix="openai-compatible-models-") as temp_dir:
        response_path = Path(temp_dir) / "response.json"
        command = [
            os.getenv("CURL_EXE", "curl"), "--silent", "--show-error", "--fail-with-body",
            "--max-time", str(max(1, int(timeout_s))),
        ]
        curl_proxy = os.getenv("OPENAI_COMPATIBLE_CURL_PROXY", "").strip()
        if curl_proxy:
            command.extend(["--proxy", curl_proxy])
        command.extend([
            "--request", "GET", endpoint,
            "--header", f"Authorization: Bearer {api_key}",
            "--header", "Accept: application/json", "--output", str(response_path),
        ])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s + 10)
        raw = response_path.read_text(encoding="utf-8") if response_path.exists() else ""
        if completed.returncode != 0:
            detail = raw or completed.stderr.strip()
            raise RuntimeError(
                f"OpenAI-compatible models endpoint failed ({completed.returncode}): {detail[:500]}"
            )
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"OpenAI-compatible models endpoint returned invalid JSON: {raw[:500]}"
            ) from exc
        rows = response.get("data") if isinstance(response, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("OpenAI-compatible models endpoint omitted data array")
        return [
            str(row.get("id") or "").strip() for row in rows
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        ]
