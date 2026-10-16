/* ==========================================================================
   Urai theme controller — window.UraiTheme
   Choice is stored in localStorage.urai_theme (light | dark | system).
   Applies data-theme on <html>, follows prefers-color-scheme while "system"
   is selected, persists the choice, and notifies listeners via "urai:theme".

   ── No-flash snippet (put this inline in <head>, BEFORE the stylesheets) ──
   <script>
   (function () {
     try {
       var t = localStorage.getItem('urai_theme') || 'system';
       var dark = t === 'dark' ||
         (t !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
       document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
     } catch (e) {}
   })();
   </script>
   ========================================================================== */
(function (global) {
  'use strict';

  if (global.UraiTheme && global.UraiTheme.__urai) return;

  var KEY = 'urai_theme';
  var CHOICES = ['light', 'dark', 'system'];
  var media = null;
  try { media = global.matchMedia('(prefers-color-scheme: dark)'); } catch (e) {}

  function lsGet(k, d) {
    try { var v = global.localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; }
  }
  function lsSet(k, v) {
    try { global.localStorage.setItem(k, v); } catch (e) {}
  }

  function normalize(choice) {
    choice = String(choice || '').toLowerCase();
    return CHOICES.indexOf(choice) >= 0 ? choice : 'system';
  }

  function get() { return normalize(lsGet(KEY, 'system')); }

  function resolved(choice) {
    choice = normalize(choice == null ? get() : choice);
    if (choice === 'system') {
      return (media && media.matches) ? 'dark' : 'light';
    }
    return choice;
  }

  function apply(choice) {
    choice = normalize(choice == null ? get() : choice);
    var theme = resolved(choice);
    var root = global.document ? global.document.documentElement : null;
    if (root) {
      root.setAttribute('data-theme', theme);
      root.setAttribute('data-theme-choice', choice);
    }
    return theme;
  }

  function emit(choice) {
    try {
      global.dispatchEvent(new CustomEvent('urai:theme', {
        detail: { choice: choice, resolved: resolved(choice) }
      }));
    } catch (e) {}
  }

  function set(choice) {
    choice = normalize(choice);
    lsSet(KEY, choice);
    apply(choice);
    emit(choice);
    return choice;
  }

  /* Cycle light -> dark -> system -> light. */
  function toggle() {
    var order = ['light', 'dark', 'system'];
    var next = order[(order.indexOf(get()) + 1) % order.length];
    return set(next);
  }

  /* Re-apply the current choice (e.g. after the APK bridge injects storage). */
  function refresh() {
    apply(get());
    return get();
  }

  if (media) {
    var onScheme = function () { if (get() === 'system') apply('system'); };
    if (typeof media.addEventListener === 'function') media.addEventListener('change', onScheme);
    else if (typeof media.addListener === 'function') media.addListener(onScheme);
  }

  /* Keep multiple tabs in sync. */
  try {
    global.addEventListener('storage', function (e) {
      if (e && e.key === KEY) { apply(get()); emit(get()); }
    });
  } catch (e) {}

  global.UraiTheme = {
    __urai: true,
    KEY: KEY,
    CHOICES: CHOICES,
    get: get,
    set: set,
    toggle: toggle,
    cycle: toggle,
    resolved: resolved,
    refresh: refresh,
    apply: apply
  };

  /* Apply immediately so data-theme is correct even without the inline hint. */
  apply(get());

  /* Export guard (CommonJS / bundlers). */
  if (typeof module !== 'undefined' && module && module.exports) {
    module.exports = global.UraiTheme;
  }
})(typeof window !== 'undefined' ? window : this);
