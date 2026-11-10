/* ==========================================================================
   Urai shared API client — window.Urai
   One client for every surface: webapp, APK WebView, CLI docs.

   Base URL  : localStorage.urai_ep (set by the Android WebView bridge) else
               same-origin ''.
   Auth      : localStorage.urai_key -> Authorization: Bearer <key>.
               Always sends X-Device-Id from localStorage.urai_device.
   Errors    : server returns {error:{message,type,code}} with an HTTP status.
               For exhausted guest tokens the payload additionally carries
               code "free_token_expired" plus blocked_until / usage /
               master_hint / approval_hint. errText() renders any shape to a
               plain UI string; the fetch wrapper throws {status,code,message}
               and dispatches a "urai:auth" CustomEvent on 401/403.
   ========================================================================== */
(function (global) {
  'use strict';

  if (global.Urai && global.Urai.__urai) return;

  var LS = global.localStorage;

  function lsGet(k, d) {
    try { var v = LS.getItem(k); return v == null ? d : v; } catch (e) { return d; }
  }
  function lsSet(k, v) {
    try { LS.setItem(k, v); } catch (e) { /* private mode / quota */ }
  }
  function lsDel(k) {
    try { LS.removeItem(k); } catch (e) {}
  }

  /* ── Identity ─────────────────────────────────────────────────────────── */
  function newDeviceId() {
    var rnd = (global.crypto && global.crypto.randomUUID)
      ? global.crypto.randomUUID().slice(0, 18)
      : Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
    return 'dev-' + rnd;
  }
  function deviceId() {
    var d = lsGet('urai_device', '');
    if (!d) { d = newDeviceId(); lsSet('urai_device', d); }
    return d;
  }

  /* ── Endpoint + key ───────────────────────────────────────────────────── */
  function baseUrl() {
    var ep = lsGet('urai_ep', '');
    if (ep) return String(ep).replace(/\/+$/, '');
    var origin = '';
    try { origin = global.location && global.location.origin; } catch (e) {}
    if (!origin || origin === 'null') return '';
    return ''; // same-origin
  }
  function apiKey() {
    return lsGet('urai_key', '') || lsGet('urai_master', '');
  }
  function setKey(k) {
    if (!k) return clearKey();
    lsSet('urai_key', k);
    lsSet('urai_master', k);
  }
  function clearKey() {
    lsDel('urai_key');
    lsDel('urai_master');
  }

  function absUrl(path) {
    if (/^https?:\/\//i.test(path)) return path;
    var b = baseUrl();
    if (!b) return path;
    return b + (path.charAt(0) === '/' ? path : '/' + path);
  }

  /* ── Error normalisation (the ONE contract) ───────────────────────────── */
  function errText(respObj, fallback) {
    if (respObj == null || respObj === '') return fallback || 'Request failed';
    if (typeof respObj === 'string') return respObj;
    if (typeof respObj !== 'object') return String(respObj);
    var e = respObj.error;
    if (e != null) {
      if (typeof e === 'string') return e;
      if (typeof e === 'object') {
        return e.message || e.error || e.detail || e.code || fallback || 'Request failed';
      }
    }
    return respObj.message || respObj.detail || respObj.code ||
           fallback || 'Request failed';
  }

  function normalizeError(body, res) {
    var status = res ? res.status : 0;
    var code = '', message = '', type = '';
    if (body && typeof body === 'object') {
      if (body.error && typeof body.error === 'object') {
        message = body.error.message || '';
        code = body.error.code || '';
        type = body.error.type || '';
      } else if (typeof body.error === 'string') {
        message = body.error;
      }
      if (!message) message = body.message || body.detail || '';
      if (!code) code = body.code || '';
      if (!type) type = body.type || '';
    }
    if (!message) message = (res && res.statusText) || ('HTTP ' + (status || 'error'));
    if (!code) {
      code = status === 401 ? 'unauthorized'
           : status === 403 ? 'forbidden'
           : 'http_' + status;
    }
    return { status: status, code: code, message: message, type: type };
  }

  function makeError(info, body) {
    var e = new Error(info.message);
    e.status = info.status;
    e.code = info.code;
    e.type = info.type;
    e.body = body || null;
    if (body && typeof body === 'object') {
      ['blocked_until', 'usage', 'master_hint', 'approval_hint'].forEach(function (f) {
        if (body[f] !== undefined) e[f] = body[f];
      });
    }
    return e;
  }

  /* ── Events ───────────────────────────────────────────────────────────── */
  function dispatch(name, detail) {
    try {
      global.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
    } catch (e) { /* very old engines */ }
  }
  function emitAuth(status, code, message, body) {
    dispatch('urai:auth', { status: status, code: code, message: message, body: body });
  }

  /* ── Fetch wrapper ────────────────────────────────────────────────────── */
  function buildHeaders(extra, hasJsonBody) {
    var h = Object.assign({ 'Accept': 'application/json' }, extra || {});
    if (hasJsonBody && !h['Content-Type'] && !h['content-type']) {
      h['Content-Type'] = 'application/json';
    }
    h['X-Device-Id'] = deviceId();
    var k = apiKey();
    if (k && !h['Authorization'] && !h['authorization']) {
      h['Authorization'] = 'Bearer ' + k;
    }
    return h;
  }

  function request(path, opts) {
    opts = opts || {};
    var method = (opts.method || 'GET').toUpperCase();
    var isForm = (typeof FormData !== 'undefined') && (opts.body instanceof FormData);
    var raw = opts.body;
    var init = {
      method: method,
      headers: buildHeaders(opts.headers, raw != null && !isForm),
      credentials: opts.credentials || 'same-origin'
    };
    if (opts.signal) init.signal = opts.signal;
    if (isForm) {
      init.body = raw;
    } else if (raw != null) {
      init.body = (typeof raw === 'string') ? raw : JSON.stringify(raw);
    }

    return global.fetch(absUrl(path), init).then(function (res) {
      if (res.status !== 401 && res.status !== 403) return res;
      return res.clone().json().catch(function () { return null; }).then(function (body) {
        var info = normalizeError(body, res);
        if (!opts.suppressAuth) emitAuth(res.status, info.code, info.message, body);
        throw makeError(info, body);
      });
    }, function (err) {
      if (err && err.name === 'AbortError') throw err;
      var e = new Error('Network error: ' + ((err && err.message) || 'request failed'));
      e.status = 0;
      e.code = 'network';
      throw e;
    });
  }

  function json(path, opts) {
    return request(path, opts).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        if (text) { try { data = JSON.parse(text); } catch (e) { data = text; } }
        if (!res.ok) {
          var info = normalizeError(data && typeof data === 'object' ? data : null, res);
          throw makeError(info, data);
        }
        return data;
      });
    });
  }

  function post(path, body, opts) {
    opts = Object.assign({ method: 'POST' }, opts || {});
    opts.body = body == null ? {} : body;
    return json(path, opts);
  }

  function extractContent(data) {
    if (!data) return '';
    if (data.choices && data.choices[0]) {
      var c = data.choices[0];
      if (c.message) return c.message.content || '';
      if (typeof c.text === 'string') return c.text;
    }
    if (typeof data.content === 'string') return data.content;
    if (typeof data.answer === 'string') return data.answer;
    if (typeof data.text === 'string') return data.text;
    return '';
  }

  function withMeta(data) {
    if (data && typeof data === 'object') {
      if (data.nlp === undefined) data.nlp = null;
      if (data.vibe === undefined) data.vibe = null;
    }
    return data;
  }

  /* ── SSE streaming chat ───────────────────────────────────────────────── */
  function streamChat(path, payload, o) {
    if (typeof payload.stream !== 'boolean') payload.stream = true;
    return request(path, { method: 'POST', body: payload, signal: o.signal })
      .then(function (res) {
        if (!res.ok) {
          return res.text().then(function (text) {
            var data = null;
            if (text) { try { data = JSON.parse(text); } catch (e) { data = { error: text }; } }
            var info = normalizeError(data && typeof data === 'object' ? data : null, res);
            throw makeError(info, data);
          });
        }
        if (!res.body || !res.body.getReader) {
          // No stream support: fall back to whole-body parse.
          return res.text().then(function (text) {
            var full = parseSseText(text, o);
            finishStream(o, full);
            return full;
          });
        }

        var reader = res.body.getReader();
        var dec = new TextDecoder();
        var buf = '';
        var full = '';
        var meta = { model: o.model || null, usage: null, nlp: null, vibe: null, urai: null };
        var done = false;

        function emitLine(line) {
          line = line.replace(/\r$/, '');
          if (line.indexOf('data:') !== 0) return;
          var data = line.slice(5);
          if (data.charAt(0) === ' ') data = data.slice(1);
          if (!data) return;
          if (data === '[DONE]') { done = true; return; }
          var chunk;
          try { chunk = JSON.parse(data); } catch (e) { return; }
          if (chunk.nlp) meta.nlp = chunk.nlp;
          if (chunk.vibe) meta.vibe = chunk.vibe;
          if (chunk.usage) meta.usage = chunk.usage;
          if (chunk.urai) meta.urai = chunk.urai;
          if (chunk.model) meta.model = chunk.model;
          var delta = '';
          if (chunk.choices && chunk.choices[0]) {
            var c = chunk.choices[0];
            delta = (c.delta && c.delta.content) || c.text || '';
          } else if (typeof chunk.content === 'string') {
            delta = chunk.content;
          }
          if (delta) {
            full += delta;
            if (typeof o.onDelta === 'function') o.onDelta(delta, full);
          }
        }

        function pump() {
          return reader.read().then(function (r) {
            if (r.done || done) return;
            buf += dec.decode(r.value, { stream: true });
            var idx;
            while ((idx = buf.indexOf('\n')) >= 0) {
              emitLine(buf.slice(0, idx));
              buf = buf.slice(idx + 1);
              if (done) break;
            }
            return pump();
          });
        }

        return pump().then(function () {
          if (buf) emitLine(buf);
          var out = {
            content: full,
            model: meta.model,
            usage: meta.usage,
            nlp: meta.nlp,
            vibe: meta.vibe,
            urai: meta.urai,
            raw: null
          };
          finishStream(o, out);
          return out;
        });
      });
  }

  function parseSseText(text, o) {
    var full = '';
    var meta = { model: o.model || null, usage: null, nlp: null, vibe: null, urai: null };
    String(text || '').split('\n').forEach(function (line) {
      line = line.replace(/\r$/, '');
      if (line.indexOf('data:') !== 0) return;
      var data = line.slice(5);
      if (data.charAt(0) === ' ') data = data.slice(1);
      if (!data || data === '[DONE]') return;
      var chunk; try { chunk = JSON.parse(data); } catch (e) { return; }
      if (chunk.nlp) meta.nlp = chunk.nlp;
      if (chunk.vibe) meta.vibe = chunk.vibe;
      if (chunk.usage) meta.usage = chunk.usage;
      if (chunk.model) meta.model = chunk.model;
      var delta = (chunk.choices && chunk.choices[0] &&
        ((chunk.choices[0].delta && chunk.choices[0].delta.content) ||
         chunk.choices[0].text)) || '';
      if (delta) { full += delta; if (typeof o.onDelta === 'function') o.onDelta(delta, full); }
    });
    return { content: full, model: meta.model, usage: meta.usage, nlp: meta.nlp, vibe: meta.vibe, urai: meta.urai, raw: null };
  }

  function finishStream(o, out) {
    if (typeof o.onDone === 'function') o.onDone(out);
  }

  /* ── Public API ───────────────────────────────────────────────────────── */
  var Urai = {
    __urai: true,

    /* config / identity */
    baseUrl: baseUrl,
    deviceId: deviceId,
    getKey: apiKey,
    setKey: setKey,
    clearKey: clearKey,

    /* errors */
    errText: errText,

    /* low-level primitives (exposed for advanced callers) */
    fetch: request,      // raw fetch wrapper: throws {status,code,message} on error
    rawRequest: request,
    json: json,
    post: post,

    /* discovery */
    capabilities: function () { return json('/v1/capabilities'); },
    models: function () { return json('/v1/models'); },
    health: function () { return json('/health'); },
    notices: function () { return json('/v1/notices'); },
    info: function () { return json('/v1/info'); },
    routing: function (payload) { return post('/agent/routing', payload).then(withMeta); },

    /* chat (streaming + non-streaming), exposes nlp/vibe metadata */
    chat: function (o) {
      o = o || {};
      var messages = o.messages || [];
      var payload = Object.assign({}, o.extra || {}, {
        model: o.model || 'auto',
        messages: messages
      });
      if (o.temperature != null) payload.temperature = o.temperature;
      if (o.max_tokens != null) payload.max_tokens = o.max_tokens;
      if (o.stream === true) return streamChat('/v1/chat/completions', payload, o);
      payload.stream = false;
      return json('/v1/chat/completions', { method: 'POST', body: payload, signal: o.signal })
        .then(function (data) {
          return {
            content: extractContent(data),
            model: data && data.model,
            usage: data && data.usage,
            nlp: (data && data.nlp) || null,
            vibe: (data && data.vibe) || null,
            urai: data && data.urai,
            raw: data
          };
        });
    },

    /* agent + agent-harness surfaces */
    agent: function (o) { return post('/agent', o || {}).then(withMeta); },
    swarm: function (o) { return post('/agent/swarm', o || {}).then(withMeta); },
    sessions: function (o) { return post('/agent/sessions', o || {}); },
    jobs: function (o) { return post('/agent/jobs', o || {}); },
    memory: function (o) { return post('/agent/memory', o || {}); },
    focus: function (o) { return post('/agent/focus', o || {}); },

    /* media / generation */
    imagine: function (o) { return post('/imagine', o || {}); },
    video: function (o) { return post('/video', o || {}); },
    see: function (o) { return post('/see', o || {}); },
    embed: function (input, o) {
      return post('/v1/embeddings', Object.assign({ input: input }, o || {}));
    },
    videoStatus: function (id) { return json('/v1/videos/' + encodeURIComponent(id || 'generations')); },

    /* token / gate */
    tokenStatus: function () {
      return json('/v1/token/status?device_id=' + encodeURIComponent(deviceId()))
        .catch(function () { return null; });
    },
    unlock: function (masterKey) {
      return post('/auth/unlock',
        { master_key: masterKey, device_id: deviceId() },
        { suppressAuth: true })
        .then(function (d) {
          if (d && d.ok) setKey(masterKey);
          return d;
        });
    },
    request: function (payload) {
      payload = payload || {};
      if (payload.device_id == null) payload.device_id = deviceId();
      return post('/auth/request', payload);
    },

    /* superadmin */
    superadmin: {
      messages: function (key) {
        return json('/superadmin/messages?key=' + encodeURIComponent(key || apiKey()),
          { suppressAuth: true });
      },
      approve: function (payload) { return post('/superadmin/approve', payload || {}, { suppressAuth: true }); },
      unblock: function (payload) { return post('/superadmin/unblock', payload || {}, { suppressAuth: true }); },
      tokens: function (key, action, extra) {
        return post('/superadmin/tokens',
          Object.assign({ key: key || apiKey(), action: action || 'list' }, extra || {}),
          { suppressAuth: true });
      },
      issue: function (label, quota, key) {
        return post('/superadmin/tokens', { key: key || apiKey(), action: 'issue', label: label || '', quota: quota || 0 }, { suppressAuth: true });
      },
      revoke: function (id, key) {
        return post('/superadmin/tokens', { key: key || apiKey(), action: 'revoke', id: id }, { suppressAuth: true });
      },
      list: function (key) {
        return post('/superadmin/tokens', { key: key || apiKey(), action: 'list' }, { suppressAuth: true });
      }
    },

    /* media helpers */
    media: {
      url: function (p) {
        if (!p) return '';
        if (/^(https?:|data:|blob:|file:)/i.test(p)) return p;
        var b = baseUrl();
        if (!b) return p;
        return b + (p.charAt(0) === '/' ? p : '/' + p);
      },
      fromB64: function (b64, mime) {
        return 'data:' + (mime || 'image/png') + ';base64,' + b64;
      },
      toBlob: function (url) {
        return global.fetch(absUrl(url)).then(function (r) { return r.blob(); });
      },
      toDataURL: function (blob) {
        return new Promise(function (resolve, reject) {
          var fr = new FileReader();
          fr.onload = function () { resolve(fr.result); };
          fr.onerror = reject;
          fr.readAsDataURL(blob);
        });
      },
      download: function (url, filename) {
        return global.fetch(absUrl(url))
          .then(function (r) { return r.blob(); })
          .then(function (blob) {
            var obj = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = obj;
            a.download = filename || 'urai-media';
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(function () { URL.revokeObjectURL(obj); }, 4000);
          });
      }
    },

    /* Android shell entry point: call boot() after injecting localStorage. */
    boot: function () {
      deviceId();
      try {
        if (global.UraiTheme && typeof global.UraiTheme.refresh === 'function') {
          global.UraiTheme.refresh();
        } else if (global.UraiTheme && typeof global.UraiTheme.set === 'function') {
          global.UraiTheme.set(global.UraiTheme.get());
        }
      } catch (e) {}
      var detail = { baseUrl: baseUrl(), deviceId: deviceId(), hasKey: !!apiKey() };
      dispatch('urai:ready', detail);
      return detail;
    }
  };

  global.Urai = Urai;

  /* Export guard (CommonJS / bundlers); classic <script> users get window.Urai. */
  if (typeof module !== 'undefined' && module && module.exports) {
    module.exports = Urai;
  }
  if (typeof exports !== 'undefined' && exports && !exports.Urai) {
    exports.Urai = Urai;
  }
})(typeof window !== 'undefined' ? window : this);
