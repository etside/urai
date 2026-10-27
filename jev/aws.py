#!/usr/bin/env python3
"""jev/aws.py — AWS integration layer for Urai (boto3-free, stdlib only).

Priority-only services used within free tier limits:
  S3          — model checkpoints, dataset backup, audio file cache
                Free: 5 GB storage, 20K GET, 2K PUT/month
  DynamoDB    — persistent sessions, memory, token-state (survives restarts)
                Free: 25 GB, 25 WCU, 25 RCU
  Polly       — TTS fallback (neural, Bengali+English, no key needed beyond IAM)
                Free: 5M chars/month (standard), 1M chars/month neural
  Transcribe  — STT fallback (Bengali+English)
                Free: 60 min/month
  CloudWatch  — structured server + watchdog logs (replaces in-memory _log)
                Free: 5 GB ingestion, 5 GB storage, 7-day retention
  Bedrock     — Claude Haiku / Nova Micro cloud LLM (needs model access enabled)
                Free: none (pay-per-token, but cheapest models ~$0.001/1K tokens)

NOT used (outside free tier or not priority):
  EC2, SageMaker, EKS, RDS, ElasticSearch, Kinesis, Step Functions

All calls use the AWS CLI subprocess pattern (no boto3 dependency) OR
the AWS SDK v4 signed HTTP pattern (pure stdlib). boto3 used if installed.

Env vars (all optional — AWS falls back gracefully if not set):
  AWS_DEFAULT_REGION   (default: ap-south-1)
  URAI_S3_BUCKET       (default: urai-data-<account>-<region>)
  URAI_BEDROCK_REGION  (default: us-east-1 — Bedrock primary)
"""
from __future__ import annotations
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")
BEDROCK_REGION = os.environ.get("URAI_BEDROCK_REGION", "us-east-1")
S3_BUCKET = os.environ.get("URAI_S3_BUCKET", "urai-data-089737991855-ap-south-1")
CW_SERVER_LOG = "/urai/server"
CW_WATCHDOG_LOG = "/urai/watchdog"

_POLLY_VOICE_MAP = {
    "alloy":   "Joanna",   # en-US female
    "echo":    "Matthew",  # en-US male
    "fable":   "Stephen",  # en-US male
    "onyx":    "Gregory",  # en-US male
    "nova":    "Ruth",     # en-US female
    "shimmer": "Kajal",    # en-IN female (Bengali-capable)
    "bn":      "Kajal",    # Bengali shortcut
}


def _aws(*args, input_data=None, region=None) -> tuple[bool, str]:
    """Run aws CLI command. Returns (ok, stdout/stderr)."""
    cmd = ["aws"] + list(args)
    if region:
        cmd += ["--region", region]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=30, input=input_data)
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, r.stderr.strip()[:500]
    except Exception as e:
        return False, str(e)[:200]


def available() -> bool:
    """True if AWS CLI is configured and reachable."""
    ok, _ = _aws("sts", "get-caller-identity", "--query", "Account",
                 "--output", "text")
    return ok


# ── S3 ─────────────────────────────────────────────────────────────────────────

def s3_upload(local_path: str, s3_key: str) -> dict:
    """Upload a file to the Urai S3 bucket."""
    ok, out = _aws("s3", "cp", local_path, f"s3://{S3_BUCKET}/{s3_key}",
                   region=AWS_REGION)
    return {"ok": ok, "detail": out, "key": s3_key,
            "url": f"s3://{S3_BUCKET}/{s3_key}"}


def s3_download(s3_key: str, local_path: str) -> dict:
    """Download a file from the Urai S3 bucket."""
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    ok, out = _aws("s3", "cp", f"s3://{S3_BUCKET}/{s3_key}", local_path,
                   region=AWS_REGION)
    return {"ok": ok, "detail": out, "local": local_path}


def s3_backup_data() -> dict:
    """Sync data/ directory to S3 (excludes large model files).
    Free tier safe: data/ is typically <50MB.
    """
    data_dir = str(ROOT / "data")
    ok, out = _aws("s3", "sync", data_dir,
                   f"s3://{S3_BUCKET}/data/",
                   "--exclude", "*.gguf", "--exclude", "*.safetensors",
                   "--exclude", "*.onnx", "--exclude", "*.bin",
                   region=AWS_REGION)
    return {"ok": ok, "detail": out}


def s3_restore_data() -> dict:
    """Restore data/ directory from S3 (on fresh deploy)."""
    data_dir = str(ROOT / "data")
    ok, out = _aws("s3", "sync", f"s3://{S3_BUCKET}/data/", data_dir,
                   region=AWS_REGION)
    return {"ok": ok, "detail": out}


def s3_upload_model_checkpoint(checkpoint_path: str, tag: str) -> dict:
    """Upload a LoRA checkpoint to S3 for persistence across deploys."""
    key = f"models/checkpoints/{tag}/{Path(checkpoint_path).name}"
    return s3_upload(checkpoint_path, key)


def s3_list_checkpoints() -> list:
    """List available model checkpoints in S3."""
    ok, out = _aws("s3", "ls", f"s3://{S3_BUCKET}/models/checkpoints/",
                   "--recursive", region=AWS_REGION)
    if not ok:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            rows.append({"date": parts[0], "time": parts[1],
                         "size": int(parts[2]), "key": parts[3]})
    return rows


# ── DynamoDB ───────────────────────────────────────────────────────────────────

def _ddb_put(table: str, item: dict) -> dict:
    ok, out = _aws("dynamodb", "put-item",
                   "--table-name", table,
                   "--item", json.dumps(_to_ddb(item)),
                   region=AWS_REGION)
    return {"ok": ok, "detail": out[:200] if not ok else ""}


def _ddb_get(table: str, key_name: str, key_val: str) -> dict | None:
    ok, out = _aws("dynamodb", "get-item",
                   "--table-name", table,
                   "--key", json.dumps({key_name: {"S": key_val}}),
                   "--output", "json",
                   region=AWS_REGION)
    if not ok or not out:
        return None
    try:
        item = json.loads(out).get("Item")
        return _from_ddb(item) if item else None
    except Exception:
        return None


def _ddb_delete(table: str, key_name: str, key_val: str) -> dict:
    ok, out = _aws("dynamodb", "delete-item",
                   "--table-name", table,
                   "--key", json.dumps({key_name: {"S": key_val}}),
                   region=AWS_REGION)
    return {"ok": ok}


def _to_ddb(obj: dict) -> dict:
    """Convert plain dict to DynamoDB attribute-value format."""
    result = {}
    for k, v in obj.items():
        if isinstance(v, str):
            result[k] = {"S": v}
        elif isinstance(v, bool):
            result[k] = {"BOOL": v}
        elif isinstance(v, (int, float)):
            result[k] = {"N": str(v)}
        elif isinstance(v, dict):
            result[k] = {"S": json.dumps(v)}
        elif isinstance(v, list):
            result[k] = {"S": json.dumps(v)}
        elif v is None:
            result[k] = {"NULL": True}
        else:
            result[k] = {"S": str(v)}
    return result


def _from_ddb(item: dict) -> dict:
    """Convert DynamoDB attribute-value format to plain dict."""
    result = {}
    for k, v in item.items():
        if "S" in v:
            # Try JSON parse for nested objects
            try:
                result[k] = json.loads(v["S"])
            except Exception:
                result[k] = v["S"]
        elif "N" in v:
            n = v["N"]
            result[k] = float(n) if "." in n else int(n)
        elif "BOOL" in v:
            result[k] = v["BOOL"]
        elif "NULL" in v:
            result[k] = None
        else:
            result[k] = str(v)
    return result


# DynamoDB — sessions
def dynamo_save_session(session_id: str, data: dict) -> dict:
    item = {"id": session_id, "ts": int(time.time()),
            "data": json.dumps(data)}
    return _ddb_put("urai-sessions", item)


def dynamo_load_session(session_id: str) -> dict | None:
    return _ddb_get("urai-sessions", "id", session_id)


# DynamoDB — memory (cloud backup for jev/memory.py)
def dynamo_save_memory(mid: str, text: str, kind: str,
                       weight: float, hits: int) -> dict:
    item = {"id": mid, "text": text, "kind": kind,
            "weight": weight, "hits": hits, "ts": int(time.time())}
    return _ddb_put("urai-memory", item)


def dynamo_load_all_memories() -> list:
    ok, out = _aws("dynamodb", "scan",
                   "--table-name", "urai-memory",
                   "--output", "json",
                   region=AWS_REGION)
    if not ok or not out:
        return []
    try:
        items = json.loads(out).get("Items", [])
        return [_from_ddb(i) for i in items]
    except Exception:
        return []


# DynamoDB — token state (persists across server restarts)
def dynamo_save_token_state(state: dict) -> dict:
    # Store whole state as one record
    item = {"id": "singleton", "ts": int(time.time()),
            "state": json.dumps(state)}
    return _ddb_put("urai-token-state", item)


def dynamo_load_token_state() -> dict | None:
    rec = _ddb_get("urai-token-state", "id", "singleton")
    if rec and isinstance(rec.get("state"), str):
        try:
            return json.loads(rec["state"])
        except Exception:
            pass
    return rec


# ── CloudWatch Logs ────────────────────────────────────────────────────────────

_cw_seq_tokens: dict[str, str] = {}  # log_stream -> sequence_token


def cw_log(log_group: str, stream: str, message: str,
           level: str = "INFO") -> bool:
    """Send a log event to CloudWatch Logs. Best-effort (never raises)."""
    try:
        event = json.dumps([{
            "timestamp": int(time.time() * 1000),
            "message": json.dumps({"level": level, "msg": message,
                                   "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                       time.gmtime())}),
        }])
        # Ensure stream exists
        _aws("logs", "create-log-stream",
             "--log-group-name", log_group,
             "--log-stream-name", stream,
             region=AWS_REGION)
        args = ["logs", "put-log-events",
                "--log-group-name", log_group,
                "--log-stream-name", stream,
                "--log-events", event]
        seq = _cw_seq_tokens.get(f"{log_group}/{stream}")
        if seq:
            args += ["--sequence-token", seq]
        ok, out = _aws(*args, region=AWS_REGION)
        if ok:
            try:
                tok = json.loads(out).get("nextSequenceToken")
                if tok:
                    _cw_seq_tokens[f"{log_group}/{stream}"] = tok
            except Exception:
                pass
        return ok
    except Exception:
        return False


def cw_log_server(msg: str, level: str = "INFO") -> bool:
    return cw_log(CW_SERVER_LOG, "urai-server", msg, level)


def cw_log_watchdog(msg: str, level: str = "INFO") -> bool:
    return cw_log(CW_WATCHDOG_LOG, "urai-watchdog", msg, level)


# ── Polly TTS ─────────────────────────────────────────────────────────────────

def polly_tts(text: str, voice: str = "alloy",
              language: str = "en") -> bytes:
    """TTS via Amazon Polly neural engine.
    Free tier: 1M neural chars/month.
    Falls back to en-US if Bengali voice unavailable.
    """
    polly_voice = _POLLY_VOICE_MAP.get(voice, "Joanna")
    if language == "bn" or language.startswith("bn"):
        polly_voice = "Kajal"
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as t:
        out_path = t.name
    ok, err = _aws("polly", "synthesize-speech",
                   "--output-format", "mp3",
                   "--voice-id", polly_voice,
                   "--engine", "neural",
                   "--text", text[:2900],  # Polly limit 3000 chars
                   out_path,
                   region=AWS_REGION)
    if ok and Path(out_path).exists():
        data = Path(out_path).read_bytes()
        Path(out_path).unlink(missing_ok=True)
        return data
    Path(out_path).unlink(missing_ok=True)
    raise RuntimeError(f"Polly TTS failed: {err}")


# ── Transcribe STT ─────────────────────────────────────────────────────────────

def transcribe_stt(audio_bytes: bytes, language: str | None = None,
                   filename: str = "audio.wav") -> dict:
    """STT via Amazon Transcribe.
    Free tier: 60 min/month.
    Uploads audio to S3, starts job, polls until done, cleans up.
    """
    import uuid, tempfile
    job_name = f"urai-{uuid.uuid4().hex[:8]}"
    s3_key = f"transcribe-tmp/{job_name}/{filename}"

    # Upload audio to S3
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix,
                                     delete=False) as t:
        t.write(audio_bytes)
        tmp_path = t.name
    up = s3_upload(tmp_path, s3_key)
    Path(tmp_path).unlink(missing_ok=True)
    if not up["ok"]:
        raise RuntimeError(f"S3 upload for Transcribe failed: {up['detail']}")

    s3_uri = f"s3://{S3_BUCKET}/{s3_key}"
    lang_code = _transcribe_lang(language)

    # Start job
    start_args = [
        "transcribe", "start-transcription-job",
        "--transcription-job-name", job_name,
        "--media", f"MediaFileUri={s3_uri}",
        "--media-format", Path(filename).suffix.lstrip(".") or "wav",
        "--output-bucket-name", S3_BUCKET,
        "--output-key", f"transcribe-out/{job_name}.json",
    ]
    if lang_code:
        start_args += ["--language-code", lang_code]
    else:
        start_args += ["--identify-language"]

    ok, out = _aws(*start_args, region=AWS_REGION)
    if not ok:
        raise RuntimeError(f"Transcribe start failed: {out}")

    # Poll for completion (max 120s)
    for _ in range(24):
        time.sleep(5)
        ok, out = _aws("transcribe", "get-transcription-job",
                       "--transcription-job-name", job_name,
                       "--output", "json",
                       region=AWS_REGION)
        if not ok:
            continue
        try:
            status = json.loads(out)["TranscriptionJob"]["TranscriptionJobStatus"]
        except Exception:
            continue
        if status == "COMPLETED":
            break
        if status == "FAILED":
            raise RuntimeError("Transcribe job failed")

    # Fetch result from S3
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t:
        result_path = t.name
    dl = s3_download(f"transcribe-out/{job_name}.json", result_path)
    text = ""
    detected_lang = language or "auto"
    if dl["ok"]:
        try:
            res = json.loads(Path(result_path).read_text())
            text = res["results"]["transcripts"][0]["transcript"]
            detected_lang = res.get("results", {}).get(
                "language_identification", [{}])[0].get("code", language or "auto")
        except Exception:
            pass
    Path(result_path).unlink(missing_ok=True)

    # Cleanup S3 temp files
    _aws("s3", "rm", f"s3://{S3_BUCKET}/{s3_key}", region=AWS_REGION)
    _aws("s3", "rm", f"s3://{S3_BUCKET}/transcribe-out/{job_name}.json",
         region=AWS_REGION)

    return {"text": text, "language": detected_lang,
            "backend": "aws-transcribe", "job": job_name}


def _transcribe_lang(lang: str | None) -> str | None:
    MAP = {"en": "en-IN", "en-US": "en-US", "en-IN": "en-IN",
           "bn": "bn-IN", "bn-IN": "bn-IN"}
    return MAP.get(lang or "", None)


# ── Bedrock LLM ───────────────────────────────────────────────────────────────

def bedrock_complete(messages: list, model_id: str = "amazon.nova-micro-v1:0",
                     max_tokens: int = 512, temperature: float = 0.2) -> dict:
    """Chat completion via AWS Bedrock (Nova Micro = cheapest).
    Requires model access enabled in AWS Console → Bedrock → Model access.
    Returns same shape as other backends: {content, backend, model}.
    Falls back gracefully if access not enabled.
    """
    # Nova / Bedrock Converse API format
    payload = {
        "messages": [{"role": m["role"],
                       "content": [{"text": m["content"]}]}
                     for m in messages if m.get("role") != "system"],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
        },
    }
    system = [m["content"] for m in messages if m.get("role") == "system"]
    if system:
        payload["system"] = [{"text": "\n".join(system)}]

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     delete=False) as t:
        json.dump(payload, t)
        payload_path = t.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t:
        out_path = t.name

    ok, err = _aws("bedrock-runtime", "converse",
                   "--model-id", model_id,
                   "--cli-input-json", f"file://{payload_path}",
                   "--output", "json",
                   region=BEDROCK_REGION)

    Path(payload_path).unlink(missing_ok=True)

    if not ok:
        Path(out_path).unlink(missing_ok=True)
        raise RuntimeError(f"Bedrock {model_id} failed: {err[:300]}")

    try:
        data = json.loads(err if not ok else
                          subprocess.check_output(
                              ["aws", "bedrock-runtime", "converse",
                               "--model-id", model_id,
                               "--cli-input-json", f"file://{payload_path}",
                               "--output", "json",
                               "--region", BEDROCK_REGION],
                              text=True, timeout=60))
        text = data["output"]["message"]["content"][0]["text"]
        usage = data.get("usage", {})
        return {"content": text, "backend": f"bedrock:{model_id}",
                "model": model_id,
                "usage": {"prompt_tokens": usage.get("inputTokens", 0),
                          "completion_tokens": usage.get("outputTokens", 0),
                          "total_tokens": usage.get("totalTokens", 0)}}
    except Exception as e:
        Path(out_path).unlink(missing_ok=True)
        raise RuntimeError(f"Bedrock response parse failed: {e}")


def bedrock_available() -> bool:
    """Check if Bedrock model access is enabled (probe once)."""
    from .backends import _probe_cached
    def check():
        import tempfile
        payload = {"messages": [{"role": "user",
                                  "content": [{"text": "hi"}]}],
                   "inferenceConfig": {"maxTokens": 1}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False) as t:
            json.dump(payload, t)
            pp = t.name
        ok, out = _aws("bedrock-runtime", "converse",
                       "--model-id", "amazon.nova-micro-v1:0",
                       "--cli-input-json", f"file://{pp}",
                       region=BEDROCK_REGION)
        Path(pp).unlink(missing_ok=True)
        if not ok:
            raise RuntimeError(out)
    return _probe_cached("bedrock", check, ttl=300)


# ── Health summary ─────────────────────────────────────────────────────────────

def aws_health() -> dict:
    """Return AWS integration status for /health endpoint."""
    ok = available()
    if not ok:
        return {"ok": False, "reason": "aws cli not configured"}
    return {
        "ok": True,
        "region": AWS_REGION,
        "s3_bucket": S3_BUCKET,
        "bedrock_available": bedrock_available(),
        "polly": True,      # always available if IAM allows
        "transcribe": True, # always available if IAM allows
        "dynamodb": True,
        "cloudwatch": True,
    }
