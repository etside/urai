#!/usr/bin/env python3
"""Urai Voice — STT, TTS, and transcription backend (v3 + AWS).

Priority order for TTS:
  1. ElevenLabs (ELEVENLABS_API_KEY)
  2. OpenAI TTS (OPENAI_API_KEY)
  3. AWS Polly neural (IAM configured)  ← NEW free tier path
  4. kokoro-onnx local GPU/CPU
  5. pyttsx3

Priority order for STT:
  1. OpenAI Whisper API (OPENAI_API_KEY)
  2. AWS Transcribe (IAM configured)   ← NEW free tier path
  3. faster-whisper local GPU/CPU

GPU selection: CUDA probed once, cached. Graceful CPU fallback.
VPS/cloud entries skipped silently if key/IAM unavailable.
"""
from __future__ import annotations
import json, os, time, io, threading
from pathlib import Path

VOICE_BACKEND = os.environ.get('URAI_VOICE_BACKEND', 'auto')
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
WHISPER_MODEL = os.environ.get('URAI_WHISPER_MODEL', 'small')
KOKORO_VOICE = os.environ.get('URAI_KOKORO_VOICE', 'af_heart')

_PROBE_CACHE: dict[str, bool] = {}
_PROBE_LOCK = threading.Lock()


def _probe(name: str, fn) -> bool:
    with _PROBE_LOCK:
        if name in _PROBE_CACHE:
            return _PROBE_CACHE[name]
    try:
        fn()
        ok = True
    except Exception:
        ok = False
    with _PROBE_LOCK:
        _PROBE_CACHE[name] = ok
    return ok


def _probe_gpu() -> bool:
    def check():
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("no cuda")
    return _probe("cuda", check)


def _probe_aws() -> bool:
    def check():
        from .aws import available as _av
        if not _av():
            raise RuntimeError("aws not configured")
    return _probe("aws", check)


def _device() -> str:
    return "cuda" if _probe_gpu() else "cpu"


class VoiceError(RuntimeError):
    pass


def _post_json(url, data, key=None, files=None, timeout=60):
    import urllib.request
    headers = {}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    if files is None:
        body = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, body, headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    else:
        import subprocess, tempfile
        parts = []
        tmpfiles = []
        for k, v in data.items():
            parts += ['-F', f'{k}={v}']
        for k, (fname, fdata) in files.items():
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(fname).suffix)
            tmp.write(fdata); tmp.flush(); tmp.close()
            tmpfiles.append(tmp.name)
            parts += ['-F', f'{k}=@{tmp.name};filename={fname}']
        cmd = (['curl', '-s', '-X', 'POST', url]
               + (['-H', f'Authorization: Bearer {key}'] if key else []) + parts)
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        for t in tmpfiles:
            try: os.unlink(t)
            except: pass
        if result.returncode != 0:
            raise VoiceError(f'curl failed: {result.stderr.decode()[:200]}')
        return result.stdout


def _tts_backend_order() -> list[str]:
    b = VOICE_BACKEND
    if b != 'auto':
        return [b]
    order = []
    if ELEVENLABS_API_KEY:
        order.append('elevenlabs')
    if OPENAI_API_KEY:
        order.append('openai')
    if _probe_aws():
        order.append('polly')   # AWS Polly free tier
    order.append('local')
    return order


def _stt_backend_order() -> list[str]:
    b = VOICE_BACKEND
    if b != 'auto':
        return [b]
    order = []
    if OPENAI_API_KEY:
        order.append('openai')
    if _probe_aws():
        order.append('transcribe')  # AWS Transcribe free tier
    order.append('local')
    return order


# ── TTS ────────────────────────────────────────────────────────────────────────

def tts(text: str, voice: str = 'alloy', speed: float = 1.0,
        format: str = 'mp3', language: str = 'en') -> bytes:
    last_err = None
    for backend in _tts_backend_order():
        try:
            if backend == 'elevenlabs':
                return _tts_elevenlabs(text, voice, speed, format)
            elif backend == 'openai':
                return _tts_openai(text, voice, speed, format)
            elif backend == 'polly':
                return _tts_polly(text, voice, language)
            else:
                return _tts_local(text, voice, speed, language)
        except VoiceError as e:
            last_err = e
        except Exception as e:
            last_err = VoiceError(str(e))
    raise last_err or VoiceError('No TTS backend available')


def _tts_elevenlabs(text, voice, speed, fmt) -> bytes:
    VOICE_MAP = {
        'alloy': 'EXAVITQu4vr4xnSDxMaL', 'echo': 'VR6AewLTigWG4xSOukaG',
        'fable': 'pNInz6obpgDQGcFmaJgB', 'onyx': 'yoZ06aMxZJJ28mfd3POQ',
        'nova': 'jBpfuIE2acCO8z3wKNLl', 'shimmer': 'oWAxZDx7w5VEj9dCyTzz',
    }
    voice_id = VOICE_MAP.get(voice, voice)
    payload = {'text': text, 'model_id': 'eleven_multilingual_v2',
               'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75,
                                  'speed': speed}}
    return _post_json(f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
                      payload, key=ELEVENLABS_API_KEY)


def _tts_openai(text, voice, speed, fmt) -> bytes:
    payload = {'model': 'tts-1', 'input': text, 'voice': voice,
               'speed': speed, 'response_format': fmt}
    base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    return _post_json(f'{base}/audio/speech', payload, key=OPENAI_API_KEY)


def _tts_polly(text, voice, language) -> bytes:
    """AWS Polly neural TTS — free tier 1M chars/month."""
    try:
        from .aws import polly_tts
        return polly_tts(text, voice=voice, language=language)
    except Exception as e:
        raise VoiceError(f'Polly TTS failed: {e}')


def _tts_local(text, voice, speed, language) -> bytes:
    try:
        from kokoro_onnx import Kokoro
        kok = Kokoro('kokoro-v1.0.onnx', 'voices-v1.0.bin')
        samples, sr = kok.create(text, voice=KOKORO_VOICE, speed=speed, lang=language)
        import wave, struct
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            wf.writeframes(struct.pack(f'<{len(samples)}h',
                                       *[int(s * 32767) for s in samples]))
        return buf.getvalue()
    except ImportError:
        pass
    except Exception:
        pass
    try:
        import pyttsx3, tempfile
        eng = pyttsx3.init()
        eng.setProperty('rate', int(eng.getProperty('rate') * speed))
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
            eng.save_to_file(text, t.name); eng.runAndWait()
            return open(t.name, 'rb').read()
    except Exception as e:
        raise VoiceError(
            f'Local TTS unavailable: {e}. Set ELEVENLABS_API_KEY / OPENAI_API_KEY '
            'or configure AWS IAM for Polly.')


# ── STT ────────────────────────────────────────────────────────────────────────

def transcribe(audio_bytes: bytes, language: str | None = None,
               filename: str = 'audio.wav') -> dict:
    last_err = None
    for backend in _stt_backend_order():
        try:
            if backend == 'openai':
                return _stt_openai(audio_bytes, language, filename)
            elif backend == 'transcribe':
                return _stt_transcribe(audio_bytes, language, filename)
            else:
                return _stt_local(audio_bytes, language)
        except VoiceError as e:
            last_err = e
        except Exception as e:
            last_err = VoiceError(str(e))
    raise last_err or VoiceError('No STT backend available')


def _stt_openai(audio_bytes, language, filename) -> dict:
    base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    data = {'model': 'whisper-1', 'response_format': 'verbose_json'}
    if language:
        data['language'] = language
    raw = _post_json(f'{base}/audio/transcriptions', data,
                     key=OPENAI_API_KEY,
                     files={'file': (filename, audio_bytes)})
    r = json.loads(raw)
    return {'text': r.get('text', ''), 'language': r.get('language', language or 'auto'),
            'duration_s': r.get('duration'), 'backend': 'openai-whisper'}


def _stt_transcribe(audio_bytes, language, filename) -> dict:
    """AWS Transcribe — free tier 60 min/month."""
    try:
        from .aws import transcribe_stt
        return transcribe_stt(audio_bytes, language=language, filename=filename)
    except Exception as e:
        raise VoiceError(f'AWS Transcribe failed: {e}')


def _stt_local(audio_bytes, language) -> dict:
    try:
        from faster_whisper import WhisperModel
        import tempfile
        device = _device()
        compute = 'float16' if device == 'cuda' else 'int8'
        model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
            t.write(audio_bytes); t.flush()
            segs, info = model.transcribe(t.name, language=language,
                                          vad_filter=True, beam_size=5)
            text = ' '.join(s.text.strip() for s in segs)
        try: os.unlink(t.name)
        except: pass
        return {'text': text, 'language': info.language,
                'duration_s': info.duration,
                'backend': f'faster-whisper/{device}'}
    except ImportError:
        raise VoiceError(
            'faster-whisper not installed. pip install faster-whisper\n'
            'Or configure AWS IAM for Transcribe.')
    except Exception as e:
        raise VoiceError(f'Local STT failed: {e}')


# ── Health ─────────────────────────────────────────────────────────────────────

def healthy() -> dict:
    try:
        gpu = _probe_gpu()
        aws = _probe_aws()
        if ELEVENLABS_API_KEY:
            tts_b = 'elevenlabs'
            stt_b = 'openai-whisper' if OPENAI_API_KEY else ('aws-transcribe' if aws else f'faster-whisper/{"cuda" if gpu else "cpu"}')
        elif OPENAI_API_KEY:
            tts_b = 'openai'
            stt_b = 'openai-whisper'
        elif aws:
            tts_b = 'aws-polly'
            stt_b = 'aws-transcribe'
        else:
            tts_b = 'local-kokoro'
            stt_b = f'faster-whisper/{"cuda" if gpu else "cpu"}'
        return {
            'tts': tts_b, 'stt': stt_b, 'gpu': gpu,
            'device': 'cuda' if gpu else 'cpu',
            'aws': aws, 'backend': VOICE_BACKEND,
            'whisper_model': WHISPER_MODEL,
        }
    except Exception as e:
        return {'tts': None, 'stt': None, 'gpu': False, 'error': str(e)}
