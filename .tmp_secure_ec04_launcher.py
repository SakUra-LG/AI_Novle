import json
import os
import re
import runpy
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path.cwd()
BATCH_START = int(os.getenv("V2_BATCH_START", "5"))
BATCH_END = int(os.getenv("V2_BATCH_END", "6"))
if BATCH_END != BATCH_START + 1 or BATCH_START < 1:
    raise RuntimeError("launcher requires one consecutive two-chapter batch")
BATCH_LABEL = f"chapters {BATCH_START}-{BATCH_END}"
KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
keys = set()
paths = []
for args in (
    ["git", "ls-files", "-z"],
    ["git", "ls-files", "--others", "--exclude-standard", "-z"],
):
    completed = subprocess.run(args, cwd=ROOT, capture_output=True)
    paths.extend(
        ROOT / raw.decode("utf-8", errors="surrogateescape")
        for raw in completed.stdout.split(b"\0")
        if raw
    )
for path in paths:
    try:
        if path.is_file() and path.stat().st_size <= 10_000_000:
            keys.update(
                KEY_RE.findall(path.read_text(encoding="utf-8", errors="ignore"))
            )
    except OSError:
        pass
completed = subprocess.run(
    [
        "git",
        "grep",
        "-I",
        "-h",
        "-o",
        "-E",
        r"sk-[A-Za-z0-9_-]{16,}",
        "HEAD",
    ],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="ignore",
)
keys.update(KEY_RE.findall(completed.stdout or ""))

os.environ.update(
    {
        "CURL_EXE": "curl.exe",
        "DASHSCOPE_HTTP_ENDPOINT": (
            "https://dashscope.aliyuncs.com/api/v1/services/"
            "aigc/text-generation/generation"
        ),
        "DASHSCOPE_CURL_INTERFACE": "100.78.48.45",
        "DASHSCOPE_CURL_RESOLVE": (
            "dashscope.aliyuncs.com:443:39.96.213.166"
        ),
        "DASHSCOPE_TIMEOUT_S": "8",
        "DASHSCOPE_HARD_TIMEOUT_S": "120",
        "DASHSCOPE_MAX_RETRIES": "3",
        "DASHSCOPE_RETRY_BACKOFF_S": "2",
        "DASHSCOPE_LOG_START": "1",
        "V2_OUTPUT_DIR": str(
            ROOT / "bert_excitation_train" / "outputs_pop_king_v2"
        ),
        "V2_SAVE_REJECTED_DRAFTS": "1",
        "V2_USE_NARRATIVE_UNITS": os.getenv("V2_USE_NARRATIVE_UNITS", "1"),
        "V2_RESULTS_FIRST_DELIVERY": "1",
        "STORY_MEMORY_RULES_ONLY": os.getenv("STORY_MEMORY_RULES_ONLY", "0"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
)

from bert_excitation_train.scripts.qwen_transport import call_qwen_via_curl


valid_key = None
for key in sorted(keys):
    for probe_attempt in range(3):
        try:
            response = call_qwen_via_curl(
                [{"role": "user", "content": "只回复：好"}],
                api_key=key,
                model="qwen-turbo",
                temperature=0.1,
                top_p=0.1,
                repetition_penalty=1.0,
                max_tokens=2,
                timeout_s=25,
            )
            if ((response.get("output") or {}).get("choices") or []):
                valid_key = key
                break
        except Exception:
            if probe_attempt < 2:
                time.sleep(2 ** probe_attempt)
    if valid_key:
        break
if not valid_key:
    raise RuntimeError(
        "No usable DashScope credential was found for the configured region"
    )
os.environ["DASHSCOPE_API_KEY"] = valid_key

inspect = subprocess.run(
    ["docker", "inspect", "ai-novel-neo4j-v2"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="strict",
    check=True,
)
container = json.loads(inspect.stdout)[0]
env_values = container.get("Config", {}).get("Env", [])
auth_value = next(
    (
        item.split("=", 1)[1]
        for item in env_values
        if item.startswith("NEO4J_AUTH=")
    ),
    "",
)
if not auth_value or auth_value.lower() == "none" or "/" not in auth_value:
    raise RuntimeError("Neo4j container authentication is unavailable")
neo4j_user, neo4j_password = auth_value.split("/", 1)
os.environ.update(
    {
        "NEO4J_URI": "bolt://127.0.0.1:7687",
        "NEO4J_USER": neo4j_user,
        "NEO4J_PASSWORD": neo4j_password,
        "V2_NARRATIVE_UNIT_ATTEMPTS": "6",
        "STORY_MEMORY_TRACE_FILE": str(
            ROOT
            / "bert_excitation_train"
            / "outputs_pop_king_v2"
            / f"story_memory_trace_results_first_{BATCH_START:03d}_{BATCH_END:03d}.jsonl"
        ),
    }
)
print(
    "[launcher] DashScope and Neo4j preflight passed; "
    f"starting {BATCH_LABEL}",
    flush=True,
)

sys.argv = [
    "generate_chapter_content_v2.py",
    "--prev-life",
    str(
        ROOT
        / "bert_excitation_train"
        / "outputs_pop_king_v2"
        / "prev_life_ctx_v2.txt"
    ),
    "--chapters-dir",
    str(
        ROOT
        / "bert_excitation_train"
        / "outputs_pop_king_v2"
        / "chapters"
    ),
    "--start",
    str(BATCH_START),
    "--end",
    str(BATCH_END),
]
runpy.run_module(
    "bert_excitation_train.scripts.v2.generate_chapter_content_v2",
    run_name="__main__",
)
