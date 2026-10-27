#!/usr/bin/env python3
"""Urai Voice — STT, TTS, and transcription backend.

Local path (no API key):
  STT: faster-whisper (int8, CPU/GPU) — Bengali + English
  TTS: kokoro-onnx (CPU, ~80MB) — ElevenLabs-compatible quality
  Transcription: same faster-whisper pipeline

Cloud path (API key):
  STT: OpenAI Whisper API (/v1/audio/transcriptions)
  TTS: ElevenLabs API (eleven_multilingual_v2)
       OpenAI TTS API (/v1/audio/speech)
  Transcription: same as STT

All endpoints are OpenAI audio API compatible:
  POST /v1/audio/speech       — TTS
  POST /v1/audio/transcriptions — STT/transcribe

Bengali (bn) + English (en) are first-class.
"""

from __future__ import annotations
import json, os, time, io
from pathlib import Path

VOICE_BACKEND = os.environ.get('URAI_VOICE_BACKEND', 'auto')  # auto|local|elevenlabs|openai
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
WHISPER_MODEL = os.environ.get('URAI_WHISPER_MODEL', 'small')  # tiny/base/small/medium
KOKORO_VOICE = os.environ.get('URAI_KOKORO_VOICE', 'af_heart')  # kokoro voice id


class VoiceError(RuntimeError):
    pass


def _post_json(url, data, key=None, files=None, timeout=60):
    """Stdlib HTTP POST (json or multipart)."""
    import urllib.request, urllib.parse
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
        # multipart/form-data via subprocess curl (avoids requests dep)
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
        cmd = ['curl', '-s', '-X', 'POST', url] + (['-H', f'Authorization: Bearer {key}'] if key else []) + parts
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        for t in tmpfiles:
            try: os.unlink(t)
            except: pass
        if result.returncode != 0:
            raise VoiceError(f'curl failed: {result.stderr.decode()[:200]}')
        return result.stdout


# --- TTS ---

def tts(text: str, voice: str = 'alloy', speed: float = 1.0,
        format: str = 'mp3', language: str = 'en') -> bytes:
    """Text-to-speech. Returns audio bytes."""
    backend = VOICE_BACKEND
    if backend == 'auto':
        if ELEVENLABS_API_KEY:
            backend = 'elevenlabs'
        elif OPENAI_API_KEY:
            backend = 'openai'
        else:
            backend = 'local'

    if backend == 'elevenlabs':
        return _tts_elevenlabs(text, voice, speed, format)
    elif backend == 'openai':
        return _tts_openai(text, voice, speed, format)
    else:
        return _tts_local(text, voice, speed, language)


def _tts_elevenlabs(text, voice, speed, fmt) -> bytes:
    # Map OpenAI voice names to ElevenLabs voice IDs
    VOICE_MAP = {
        'alloy': 'EXAVITQu4vr4xnSDxMaL',  # Rachel
        'echo': 'VR6AewLTigWG4xSOukaG',   # Arnold
        'fable': 'pNInz6obpgDQGcFmaJgB',  # Adam
        'onyx': 'yoZ06aMxZJJ28mfd3POQ',   # Sam
        'nova': 'jBpfuIE2acCO8z3wKNLl',   # Gigi
        'shimmer': 'oWAxZDx7w5VEj9dCyTzz', # Grace (Bengali-capable)
    }
    voice_id = VOICE_MAP.get(voice, voice)  # pass-through if raw ID
    payload = {'text': text, 'model_id': 'eleven_multilingual_v2',
               'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75, 'speed': speed}}
    result = _post_json(
        f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
        payload, key=ELEVENLABS_API_KEY)
    return result


def _tts_openai(text, voice, speed, fmt) -> bytes:
    payload = {'model': 'tts-1', 'input': text, 'voice': voice,
               'speed': speed, 'response_format': fmt}
    base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    return _post_json(f'{base}/audio/speech', payload, key=OPENAI_API_KEY)


def _tts_local(text, voice, speed, language) -> bytes:
    """Local TTS via kokoro-onnx. Falls back to pyttsx3 if not installed."""
    try:
        from kokoro_onnx import Kokoro
        kok = Kokoro('kokoro-v1.0.onnx', 'voices-v1.0.bin')
        samples, sr = kok.create(text, voice=KOKORO_VOICE, speed=speed, lang=language)
        import wave, struct
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            wf.writeframes(struct.pack(f'<{len(samples)}h', *[int(s*32767) for s in samples]))
        return buf.getvalue()
    except ImportError:
        pass
    try:
        import pyttsx3, tempfile
        eng = pyttsx3.init()
        eng.setProperty('rate', int(eng.getProperty('rate') * speed))
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
            eng.save_to_file(text, t.name); eng.runAndWait()
            return open(t.name, 'rb').read()
    except Exception as e:
        raise VoiceError(f'Local TTS unavailable: {e}. Set ELEVENLABS_API_KEY or OPENAI_API_KEY.')


# --- STT / Transcription ---

def transcribe(audio_bytes: bytes, language: str | None = None,
               filename: str = 'audio.wav') -> dict:
    """Speech-to-text. Returns {text, language, duration_s, backend}."""
    backend = VOICE_BACKEND
    if backend == 'auto':
        backend = 'openai' if OPENAI_API_KEY else 'local'

    if backend == 'openai':
        return _stt_openai(audio_bytes, language, filename)
    elif backend == 'elevenlabs':
        # ElevenLabs doesn't have STT — fall back to OpenAI if available, else local
        if OPENAI_API_KEY:
            return _stt_openai(audio_bytes, language, filename)
        return _stt_local(audio_bytes, language)
    else:
        return _stt_local(audio_bytes, language)


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


def _stt_local(audio_bytes, language) -> dict:
    """Local STT via faster-whisper. Bengali + English first-class."""
    try:
        from faster_whisper import WhisperModel
        import tempfile
        model = WhisperModel(WHISPER_MODEL, device='auto', compute_type='int8')
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
            t.write(audio_bytes)
            t.flush()
            segs, info = model.transcribe(t.name, language=language,
                                          vad_filter=True, beam_size=5)
            text = ' '.join(s.text.strip() for s in segs)
        return {'text': text, 'language': info.language,
                'duration_s': info.duration, 'backend': 'faster-whisper'}
    except ImportError:
        raise VoiceError(
            'faster-whisper not installed. Run: pip install faster-whisper\n'
            'Or set OPENAI_API_KEY to use OpenAI Whisper API.')


# --- Health ---

def healthy() -> dict:
    """Returns voice capability status."""
    out = {'tts': None, 'stt': None, 'backend': VOICE_BACKEND}
    if ELEVENLABS_API_KEY:
        out['tts'] = 'elevenlabs'; out['stt'] = 'openai-whisper' if OPENAI_API_KEY else 'local'
    elif OPENAI_API_KEY:
        out['tts'] = 'openai'; out['stt'] = 'openai-whisper'
    else:
        out['tts'] = 'local-kokoro'; out['stt'] = 'local-whisper'
    return out
