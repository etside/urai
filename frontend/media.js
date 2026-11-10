/* ==========================================================================
   Urai media client — window.UraiMedia
   One client for the media surfaces (webapp, APK WebView):

     profiles()          GET  /v1/media/profiles
     status()            GET  /v1/videos/generations   (video runner status)
     job(id)             GET  /v1/videos/<id>
     generateVideo(o)    POST /v1/videos/generations
     generateImage(o)    POST /v1/images/generations

   Built on window.Urai (api.js) so the single error contract is preserved:
   api.json()/post() throw {status, code, message, body}. generateVideo()
   additionally resolves the documented "not installed" contract
   ({ok:false, installed:false, error, status:{missing:[...]}}) instead of
   throwing, so the UI can render an honest "not installed" panel with the
   missing files; every other failure keeps throwing.

   Task history (metadata only) lives in localStorage under
   "urai_media_history" so past jobs can re-show the exact weights, LoRA +
   strength, steps, sampler, scheduler, sparsity and effective duration.
   ========================================================================== */
(function (global) {
  'use strict';

  if (global.UraiMedia && global.UraiMedia.__urai) return;

  var HISTORY_KEY = 'urai_media_history';
  var HISTORY_MAX = 60;

  /* The three media profiles are deliberately separate surfaces. */
  var PROFILES = [
    { id: 'ref2va_vsa', label: 'H3 Ref2VA VSA', kind: 'video',
      provider: 'ref2va', grade: 'SOTA character-consistent' },
    { id: 'wan3', label: 'Wan 3.0', kind: 'video',
      provider: 'wan3', grade: 'SOTA t2v/i2v' },
    { id: 'seedream4', label: 'Seedream 4.0', kind: 'image',
      provider: 'seedream4', grade: 'SOTA image gen/edit' }
  ];

  function U() { return global.Urai; }
  function requireU() {
    var u = U();
    if (!u || typeof u.post !== 'function') {
      throw new Error('Urai API client (api.js) not loaded');
    }
    return u;
  }

  function errText(e, fallback) {
    var u = U();
    if (u && typeof u.errText === 'function') {
      return u.errText((e && e.body) || e, fallback);
    }
    if (e && e.message) return e.message;
    if (typeof e === 'string') return e;
    return fallback || 'Request failed';
  }

  function strip(obj) {
    Object.keys(obj).forEach(function (k) { if (obj[k] === undefined) delete obj[k]; });
    return obj;
  }

  function providerFor(profileId) {
    for (var i = 0; i < PROFILES.length; i++) {
      if (PROFILES[i].id === profileId) return PROFILES[i].provider;
    }
    return profileId || 'auto';
  }

  function profileMeta(profileId) {
    for (var i = 0; i < PROFILES.length; i++) {
      if (PROFILES[i].id === profileId) return PROFILES[i];
    }
    return null;
  }

  /* Documents "backend reports it is missing" vs a hard error. */
  function isNotInstalled(body) {
    if (!body || typeof body !== 'object') return false;
    if (body.installed === false) return true;
    var msg = String(body.error || body.message || '');
    return /not installed|not reachable|missing weights|missing files/i.test(msg);
  }

  /* ── profiles / status / job ──────────────────────────────────────────── */
  function profiles() {
    return requireU().json('/v1/media/profiles').then(function (d) {
      if (Array.isArray(d)) return d;
      return (d && d.profiles) || [];
    });
  }

  function status() {
    return requireU().json('/v1/videos/generations');
  }

  function job(id) {
    return requireU().json('/v1/videos/' + encodeURIComponent(id));
  }

  /* Missing files for a provider, from the video status endpoint. */
  function missingFiles(provider) {
    return status().then(function (st) {
      var p = String(provider || '').toLowerCase();
      if (p.indexOf('ref2va') === 0 || p === 'vsa' || p === 'h3') {
        return ((st && st.ref2va) || {}).missing || [];
      }
      return [];
    }).catch(function () { return []; });
  }

  /* ── video generation ─────────────────────────────────────────────────── */
  function generateVideo(opts) {
    opts = opts || {};
    var payload = strip({
      prompt: opts.prompt || '',
      provider: opts.provider || (opts.profile ? providerFor(opts.profile) : 'auto'),
      /* The API `profile` field is an override object, not an id string. */
      profile: (opts.profile && typeof opts.profile === 'object') ? opts.profile : undefined,
      duration: opts.duration,
      width: opts.width,
      height: opts.height,
      frames: opts.frames,
      fps: opts.fps,
      seed: opts.seed,
      sparsity: opts.sparsity,
      ref_images: opts.ref_images,
      settings: opts.settings,
      out: opts.out,
      response_format: opts.response_format
    });
    return requireU().post('/v1/videos/generations', payload).then(function (res) {
      if (!res || typeof res !== 'object') return { ok: false, error: 'empty response' };
      if (res.ok === undefined) res.ok = !res.error;
      return res;
    }, function (err) {
      var body = err && err.body;
      if (isNotInstalled(body)) {
        return Object.assign({ ok: false, installed: false, kind: 'video' }, body, {
          error: errText(body, err.message || 'not installed'),
          status: (body && body.status) || null,
          code: err && err.code
        });
      }
      throw err;
    });
  }

  /* ── image generation ─────────────────────────────────────────────────── */
  function generateImage(opts) {
    opts = opts || {};
    var payload = strip({
      prompt: opts.prompt || '',
      steps: opts.steps,
      width: opts.width,
      height: opts.height,
      seed: opts.seed,
      response_format: opts.response_format || 'b64_json'
    });
    return requireU().post('/v1/images/generations', payload).then(function (d) {
      var item = (d && d.data && d.data[0]) || {};
      var url = item.url || (item.b64_json ? requireU().media.fromB64(item.b64_json) : '');
      return { ok: !!url, url: url, raw: d };
    });
  }

  /* ── source resolution ────────────────────────────────────────────────── */
  function videoSrc(res) {
    if (!res) return '';
    if (res.b64_json) return 'data:' + (res.mime || 'video/mp4') + ';base64,' + res.b64_json;
    if (res.data_url) return res.data_url;
    var cand = res.url || res.path || '';
    if (/^(https?:|blob:|data:)/i.test(cand)) return cand;
    if (cand) return (U() ? U().media.url(cand) : cand);
    return '';
  }

  function imageSrc(res) {
    if (!res) return '';
    if (res.url) return res.url;
    if (res.b64_json) return 'data:' + (res.mime || 'image/png') + ';base64,' + res.b64_json;
    return '';
  }

  /* ── describe: weights / settings / effective duration ────────────────── */
  function describe(res) {
    res = res || {};
    var w = res.weights || {};
    var s = res.settings || {};
    return {
      id: res.id || '',
      provider: res.provider || '',
      provider_label: res.provider_label || res.provider || '',
      grade: res.grade || '',
      prompt: res.prompt || '',
      path: res.path || '',
      weights: {
        diffusion_model: w.diffusion_model || '',
        turbo_lora: w.turbo_lora || '',
        turbo_lora_strength: w.turbo_lora_strength,
        vsa_gate: w.vsa_gate || '',
        text_encoder: w.text_encoder || '',
        video_vae: w.video_vae || '',
        audio_vae: w.audio_vae || ''
      },
      settings: {
        steps: s.steps,
        sampler: s.sampler,
        scheduler: s.scheduler,
        sparsity: s.sparsity,
        shift_video: s.shift_video,
        shift_audio: s.shift_audio,
        width: (res.width != null ? res.width : s.width),
        height: (res.height != null ? res.height : s.height),
        frames: (res.frames != null ? res.frames : s.frames),
        fps: (res.fps != null ? res.fps : s.fps),
        seed: (s.seed != null ? s.seed : res.seed)
      },
      duration: (res.duration != null ? res.duration : null),
      fps: (res.fps != null ? res.fps : null),
      native_audio: !!res.native_audio,
      reference_images: res.reference_images || [],
      comfy_elapsed_s: (res.comfy_elapsed_s != null ? res.comfy_elapsed_s : null)
    };
  }

  function durationLabel(res) {
    var d = describe(res);
    if (d.duration != null) return d.duration + 's';
    var s = d.settings;
    if (s.frames && s.fps) return (Math.round(100 * s.frames / s.fps) / 100) + 's';
    return '—';
  }

  function summaryLine(res) {
    var d = describe(res);
    var bits = [];
    if (d.settings.steps != null) bits.push('steps ' + d.settings.steps);
    if (d.settings.sampler) bits.push(String(d.settings.sampler));
    if (d.settings.scheduler) bits.push(String(d.settings.scheduler));
    if (d.settings.sparsity != null) bits.push('sparsity ' + d.settings.sparsity);
    bits.push(durationLabel(res));
    return bits.join(' · ');
  }

  /* ── history (localStorage: urai_media_history) ───────────────────────── */
  function loadHistory() {
    try {
      var raw = global.localStorage.getItem(HISTORY_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) { return []; }
  }

  function saveHistory(list) {
    try {
      global.localStorage.setItem(HISTORY_KEY,
        JSON.stringify((list || []).slice(0, HISTORY_MAX)));
    } catch (e) { /* private mode / quota */ }
  }

  function appendHistory(rec) {
    var list = loadHistory();
    list.unshift(rec);
    saveHistory(list);
    return list;
  }

  function clearHistory() {
    try { global.localStorage.removeItem(HISTORY_KEY); } catch (e) {}
  }

  function record(res, extra) {
    var d = describe(res);
    var rec = Object.assign({}, d, {
      kind: (extra && extra.kind) || res.kind || 'video',
      profile: (extra && extra.profile) || res.profile || res.provider || '',
      created: Date.now()
    });
    if (extra && extra.prompt != null) rec.prompt = extra.prompt;
    return rec;
  }

  var api = {
    __urai: true,
    HISTORY_KEY: HISTORY_KEY,
    PROFILES: PROFILES,
    REF2VA_ID: 'ref2va_vsa',

    providerFor: providerFor,
    profileMeta: profileMeta,
    isNotInstalled: isNotInstalled,
    errText: errText,

    profiles: profiles,
    status: status,
    job: job,
    missingFiles: missingFiles,

    generateVideo: generateVideo,
    generateImage: generateImage,

    videoSrc: videoSrc,
    imageSrc: imageSrc,
    describe: describe,
    durationLabel: durationLabel,
    summaryLine: summaryLine,

    history: {
      load: loadHistory,
      save: saveHistory,
      append: appendHistory,
      clear: clearHistory,
      record: record
    }
  };

  global.UraiMedia = api;

  if (typeof module !== 'undefined' && module && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
