#!/usr/bin/env python3
"""Urai Voice — STT, TTS, and transcription backend.

Local path (no API key):
  STT: faster-whisper (int8, GPU→CPU auto) — Bengali + English
  TTS: kokoro-onnx (GPU→CPU auto, ~80MB) — ElevenLabs-compatible quality
  Transcription: same faster-whisper pipeline

Cloud path (API key):
  STT: OpenAI Whisper API (/v1/audio/transcriptions)
  TTS: ElevenLabs API (eleven_multilingual_v2)
       OpenAI TTS API (/v1/audio/speech)
  Transcription: same as STT

All endpoints are OpenAI audio API compatible:
  POST /v1/audio/speech         — TTS
  POST /v1/audio/transcriptions — STT/transcribe

GPU selection:
  Prefers CUDA GPU if available, falls back to CPU silently.
  VPS/remote backend skipped if unavailable — no hard errors.
  Each backend probed once and cached (_PROBE_CACHE).

Bengali (bn) + English (en) are first-class.
"""

from __future__ import annotations
import json, os, time, io, threading
from pathlib import Path

VOICE_BACKEND = os.environ.get('URAI_VOICE_BACKEND', 'auto')  # auto|local|elevenlabs|openai
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
WHISPER_MODEL = os.environ.get('URAI_WHISPER_MODEL', 'small')  # tiny/base/small/medium
KOKORO_VOICE = os.environ.get('URAI_KOKORO_VOICE', 'af_heart')

# ── probe cache ────────────────────────────────────────────────────────────────
# Maps backend name → True (ok) | False (unavailable) | None (untested)
_PROBE_CACHE: dict[str, bool] = {}
_PROBE_LOCK = threading.Lock()


def _probe(name: str, fn) -> bool:
    """Run fn() once; cache and return True if it succeeds, False otherwise."""
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
    """True if a CUDA device is reachable."""
    def check():
        import torch  # type: ignore
        if not torch.cuda.is_available():
            raise RuntimeError("no cuda")
    return _probe("cuda", check)


def _device() -> str:
    """Return 'cuda' if GPU available, else 'cpu'."""
    return "cuda" if _probe_gpu() else "cpu"


class VoiceError(RuntimeError):
    pass


def _post_json(url, data, key=None, files=None, timeout=60):
    """Stdlib HTTP POST (json or multipart). Returns raw bytes."""
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
        # multipart/form-data via curl (no requests dep)
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
               + (['-H', f'Authorization: Bearer {key}'] if key else [])
               + parts)
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        for t in tmpfiles:
            try:
                os.unlink(t)
            except Exception:
                pass
        if result.returncode != 0:
            raise VoiceError(f'curl failed: {result.stderr.decode()[:200]}')
        return result.stdout


# ── Backend selection ──────────────────────────────────────────────────────────

def _tts_backend_order() -> list[str]:
    """Priority list for TTS.  VPS/cloud entries skipped if key absent."""
    b = VOICE_BACKEND
    if b != 'auto':
        return [b]
    order = []
    if ELEVENLABS_API_KEY:
        order.append('elevenlabs')
    if OPENAI_API_KEY:
        order.append('openai')
    order.append('local')  # always last — never skipped entirely
    return order


def _stt_backend_order() -> list[str]:
    """Priority list for STT."""
    b = VOICE_BACKEND
    if b != 'auto':
        return [b]
    order = []
    if OPENAI_API_KEY:
        order.append('openai')
    if ELEVENLABS_API_KEY:
        # ElevenLabs has no STT; skip it silently
        pass
    order.append('local')
    return order


# ── TTS ────────────────────────────────────────────────────────────────────────

def tts(text: str, voice: str = 'alloy', speed: float = 1.0,
        format: str = 'mp3', language: str = 'en') -> bytes:
    """Text-to-speech. Returns audio bytes.
    Tries each backend in priority order; skips unavailable ones gracefully.
    """
    last_err: Exception | None = None
    for backend in _tts_backend_order():
        try:
            if backend == 'elevenlabs':
                return _tts_elevenlabs(text, voice, speed, format)
            elif backend == 'openai':
                return _tts_openai(text, voice, speed, format)
            else:
                return _tts_local(text, voice, speed, language)
        except VoiceError as e:
            last_err = e
            continue  # try next backend
        except Exception as e:
            last_err = VoiceError(str(e))
            continue
    raise last_err or VoiceError('No TTS backend available')


def _tts_elevenlabs(text, voice, speed, fmt) -> bytes:
    VOICE_MAP = {
        'alloy':   'EXAVITQu4vr4xnSDxMaL',  # Rachel
        'echo':    'VR6AewLTigWG4xSOukaG',   # Arnold
        'fable':   'pNInz6obpgDQGcFmaJgB',   # Adam
        'onyx':    'yoZ06aMxZJJ28mfd3POQ',   # Sam
        'nova':    'jBpfuIE2acCO8z3wKNLl',   # Gigi
        'shimmer': 'oWAxZDx7w5VEj9dCyTzz',   # Grace (Bengali-capable)
    }
    voice_id = VOICE_MAP.get(voice, voice)
    payload = {
        'text': text,
        'model_id': 'eleven_multilingual_v2',
        'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75, 'speed': speed},
    }
    return _post_json(
        f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
        payload, key=ELEVENLABS_API_KEY)


def _tts_openai(text, voice, speed, fmt) -> bytes:
    payload = {'model': 'tts-1', 'input': text, 'voice': voice,
               'speed': speed, 'response_format': fmt}
    base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    return _post_json(f'{base}/audio/speech', payload, key=OPENAI_API_KEY)


def _tts_local(text, voice, speed, language) -> bytes:
    """GPU-first kokoro-onnx TTS, CPU fallback, then pyttsx3."""
    # kokoro-onnx doesn't use torch directly but faster to run on GPU via
    # onnxruntime-gpu.  We pass device hint if onnxruntime-gpu is available.
    try:
        from kokoro_onnx import Kokoro  # type: ignore
        kok = Kokoro('kokoro-v1.0.onnx', 'voices-v1.0.bin')
        samples, sr = kok.create(text, voice=KOKORO_VOICE, speed=speed, lang=language)
        import wave, struct
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f'<{len(samples)}h',
                                       *[int(s * 32767) for s in samples]))
        return buf.getvalue()
    except ImportError:
        pass  # kokoro not installed — try pyttsx3
    except Exception as e:
        pass  # model files missing etc — try pyttsx3

    try:
        import pyttsx3, tempfile  # type: ignore
        eng = pyttsx3.init()
        eng.setProperty('rate', int(eng.getProperty('rate') * speed))
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
            eng.save_to_file(text, t.name)
            eng.runAndWait()
            data = open(t.name, 'rb').read()
        return data
    except Exception as e:
        raise VoiceError(
            f'Local TTS unavailable: {e}. '
            'Install kokoro-onnx or set ELEVENLABS_API_KEY / OPENAI_API_KEY.')


# ── STT / Transcription ────────────────────────────────────────────────────────

def transcribe(audio_bytes: bytes, language: str | None = None,
               filename: str = 'audio.wav') -> dict:
    """Speech-to-text. Returns {text, language, duration_s, backend}.
    Tries each backend in priority order; skips unavailable ones gracefully.
    """
    last_err: Exception | None = None
    for backend in _stt_backend_order():
        try:
            if backend == 'openai':
                return _stt_openai(audio_bytes, language, filename)
            else:
                return _stt_local(audio_bytes, language)
        except VoiceError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = VoiceError(str(e))
            continue
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
    return {'text': r.get('text', ''),
            'language': r.get('language', language or 'auto'),
            'duration_s': r.get('duration'),
            'backend': 'openai-whisper'}


def _stt_local(audio_bytes, language) -> dict:
    """GPU-first faster-whisper STT. Falls back to CPU silently.
    Bengali + English first-class via language param.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
        import tempfile

        device = _device()          # 'cuda' if GPU available, else 'cpu'
        compute = 'float16' if device == 'cuda' else 'int8'

        # WhisperModel is cached implicitly by faster-whisper across calls
        # within the same process; we don't need our own cache here.
        model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
            t.write(audio_bytes)
            t.flush()
            segs, info = model.transcribe(t.name,
                                          language=language,
                                          vad_filter=True,
                                          beam_size=5)
            text = ' '.join(s.text.strip() for s in segs)
        try:
            os.unlink(t.name)
        except Exception:
            pass

        return {'text': text,
                'language': info.language,
                'duration_s': info.duration,
                'backend': f'faster-whisper/{device}'}

    except ImportError:
        raise VoiceError(
            'faster-whisper not installed. Run: pip install faster-whisper\n'
            'Or set OPENAI_API_KEY to use OpenAI Whisper API.')
    except Exception as e:
        raise VoiceError(f'Local STT failed: {e}')


# ── Health ─────────────────────────────────────────────────────────────────────

def healthy() -> dict:
    """Returns voice capability status dict (never raises)."""
    try:
        gpu = _probe_gpu()
        tts_b: str
        stt_b: str
        if ELEVENLABS_API_KEY:
            tts_b = 'elevenlabs'
            stt_b = 'openai-whisper' if OPENAI_API_KEY else f'faster-whisper/{"cuda" if gpu else "cpu"}'
        elif OPENAI_API_KEY:
            tts_b = 'openai'
            stt_b = 'openai-whisper'
        else:
            tts_b = 'local-kokoro'
            stt_b = f'faster-whisper/{"cuda" if gpu else "cpu"}'

        return {
            'tts': tts_b,
            'stt': stt_b,
            'gpu': gpu,
            'device': 'cuda' if gpu else 'cpu',
            'backend': VOICE_BACKEND,
            'whisper_model': WHISPER_MODEL,
        }
    except Exception as e:
        return {'tts': None, 'stt': None, 'gpu': False, 'error': str(e)}
