/* ==========================================================================
   Urai shell — window.UraiShell
   A tiny History-API router + shell controller shared by the webapp and the
   Android WebView. It owns:
     • top-level nav (Chat / Tasks / Knowledge / Studio / Tools / Settings)
     • sidebar conversation list + collapse (persisted) and mobile off-canvas
     • main-panel swapping between [data-view] sections
     • deep links, back/forward (popstate), and a "urai:route" event

   Views are registered by the host page:
     UraiShell.register('tasks', { mount(root){...}, show(){...}, hide(){...} });
   ========================================================================== */
(function (global) {
  'use strict';

  if (global.UraiShell && global.UraiShell.__urai) return;

  var MOBILE_MAX = 720;
  var SIDEBAR_KEY = 'urai_sidebar';

  var ICONS = {
    chat:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    tasks:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
    knowledge:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    studio:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>',
    tools:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 1 5.4-5.4l-2.3 2.3 1.4 1.4z"/></svg>',
    settings:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    admin:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 6v6c0 5 3.4 8.4 8 10 4.6-1.6 8-5 8-10V6z"/></svg>'
  };

  var ROUTES = [
    { path: '/',          name: 'chat',      label: 'Chat',      icon: ICONS.chat },
    { path: '/tasks',     name: 'tasks',     label: 'Tasks',     icon: ICONS.tasks },
    { path: '/knowledge', name: 'knowledge', label: 'Knowledge', icon: ICONS.knowledge },
    { path: '/studio',    name: 'studio',    label: 'Studio',    icon: ICONS.studio },
    { path: '/tools',     name: 'tools',     label: 'Tools',     icon: ICONS.tools },
    { path: '/settings',  name: 'settings',  label: 'Settings',  icon: ICONS.settings }
  ];
  var HIDDEN_ROUTES = [
    { path: '/admin', name: 'admin', label: 'Admin', icon: ICONS.admin }
  ];

  var views = {};          // name -> { mount, show, hide, render, mounted }
  var current = { path: '/', name: 'chat' };
  var started = false;
  var els = {};
  var collapsed = false;

  function lsGet(k, d) {
    try { var v = global.localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; }
  }
  function lsSet(k, v) {
    try { global.localStorage.setItem(k, v); } catch (e) {}
  }

  function isMobile() { return global.innerWidth <= MOBILE_MAX; }

  /* Normalise a location.pathname to a canonical route name + path. */
  function resolvePath(pathname) {
    var p = pathname || '/';
    // Server serves the app at / and /app/*; strip the /app prefix.
    if (p === '/app') p = '/';
    else if (p.indexOf('/app/') === 0) p = p.slice(4);
    // Hidden admin entry points.
    if (p === '/superadmin' || p.indexOf('/superadmin/') === 0) p = '/admin';
    // trailing slash normalization (keep root)
    if (p.length > 1 && p.charAt(p.length - 1) === '/') p = p.replace(/\/+$/, '');
    if (p === '' ) p = '/';

    var all = ROUTES.concat(HIDDEN_ROUTES);
    for (var i = 0; i < all.length; i++) {
      if (all[i].path === p) return all[i];
    }
    // Unknown -> chat, but remember the requested path for deep-link consumers.
    return { path: p, name: 'chat', label: 'Chat', icon: ICONS.chat, unknown: true };
  }

  function findRoute(name) {
    var all = ROUTES.concat(HIDDEN_ROUTES);
    for (var i = 0; i < all.length; i++) if (all[i].name === name) return all[i];
    return ROUTES[0];
  }

  /* ── Nav ──────────────────────────────────────────────────────────────── */
  function buildNav() {
    var rail = els.navRail;
    if (!rail || rail.getAttribute('data-built') === '1') return;
    rail.innerHTML = '';
    ROUTES.concat(HIDDEN_ROUTES).forEach(function (r) {
      var b = global.document.createElement('button');
      b.type = 'button';
      b.className = 'nav-item';
      b.setAttribute('data-route', r.path);
      b.setAttribute('data-name', r.name);
      b.setAttribute('data-tip', r.label);
      b.setAttribute('aria-label', r.label);
      b.innerHTML =
        '<span class="nav-icon" aria-hidden="true">' + r.icon + '</span>' +
        '<span class="nav-label">' + r.label + '</span>';
      b.addEventListener('click', function () {
        navigate(r.path);
        closeMobile();
      });
      rail.appendChild(b);
    });
    rail.setAttribute('data-built', '1');
    var admin = rail.querySelector('[data-name="admin"]');
    if (admin) admin.hidden = true; // revealed on /admin or 5 taps
  }

  function markActive(name) {
    var rail = els.navRail;
    if (!rail) return;
    Array.prototype.forEach.call(rail.querySelectorAll('.nav-item'), function (b) {
      b.classList.toggle('is-active', b.getAttribute('data-name') === name);
    });
  }

  function setTitle(label) {
    var t = els.title;
    if (t) t.textContent = label;
    try { global.document.title = 'Urai — ' + label; } catch (e) {}
  }

  /* ── View swapping ────────────────────────────────────────────────────── */
  function viewEl(name) {
    var root = els.viewRoot;
    if (!root) return null;
    return root.querySelector('[data-view="' + name + '"]');
  }

  function ensureView(name) {
    var el = viewEl(name);
    if (el) return el;
    var root = els.viewRoot;
    if (!root) return null;
    // Dynamically create a view container for routes without static markup.
    el = global.document.createElement('section');
    el.className = 'view';
    el.setAttribute('data-view', name);
    el.hidden = true;
    root.appendChild(el);
    return el;
  }

  function mountView(name) {
    var v = views[name];
    if (v && !v.mounted && typeof v.mount === 'function') {
      var el = ensureView(name);
      try { v.mount(el, { shell: api }); } catch (e) { console.error('view mount failed', name, e); }
      v.mounted = true;
    }
  }

  function showView(name) {
    var root = els.viewRoot;
    if (!root) return;
    Array.prototype.forEach.call(root.querySelectorAll('.view'), function (el) {
      el.hidden = el.getAttribute('data-view') !== name;
    });
    ensureView(name);
    var el = viewEl(name);
    if (el) el.hidden = false;
    mountView(name);
    var v = views[name];
    if (v && typeof v.show === 'function') {
      try { v.show(el); } catch (e) { console.error('view show failed', name, e); }
    }
  }

  /* ── Sidebar ──────────────────────────────────────────────────────────── */
  function applyCollapse() {
    if (!els.app) return;
    els.app.classList.toggle('is-collapsed', collapsed && !isMobile());
    var btn = els.collapseBtn;
    if (btn) {
      btn.setAttribute('aria-expanded', String(!collapsed));
      btn.setAttribute('data-tip', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    }
  }

  function setCollapsed(on) {
    collapsed = !!on;
    lsSet(SIDEBAR_KEY, collapsed ? 'collapsed' : 'expanded');
    applyCollapse();
    return collapsed;
  }

  function toggleCollapse() { return setCollapsed(!collapsed); }

  function openMobile() {
    if (!els.app) return;
    els.app.classList.add('is-mobile-open');
    if (els.scrim) els.scrim.classList.add('is-open');
  }
  function closeMobile() {
    if (!els.app) return;
    els.app.classList.remove('is-mobile-open');
    if (els.scrim) els.scrim.classList.remove('is-open');
  }

  function toggleSidebar() {
    if (isMobile()) {
      if (els.app && els.app.classList.contains('is-mobile-open')) closeMobile();
      else openMobile();
    } else {
      toggleCollapse();
    }
  }

  /* ── Conversation list ────────────────────────────────────────────────── */
  function renderConversations(items, activeId, onSelect) {
    var list = els.chatList;
    if (!list) return;
    items = items || [];
    if (!items.length) {
      list.innerHTML =
        '<div class="side-label" style="padding-left:8px">No chats yet</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(function (c) {
      var el = global.document.createElement('div');
      el.className = 'chat-item' + (c.id === activeId ? ' is-active' : '');
      el.setAttribute('data-id', c.id);
      el.innerHTML =
        '<span aria-hidden="true">💬</span>' +
        '<span class="chat-title"></span>';
      el.querySelector('.chat-title').textContent = c.title || 'Untitled';
      el.addEventListener('click', function () {
        if (typeof onSelect === 'function') onSelect(c.id);
        closeMobile();
      });
      list.appendChild(el);
    });
  }

  function setActiveConversation(id) {
    var list = els.chatList;
    if (!list) return;
    Array.prototype.forEach.call(list.querySelectorAll('.chat-item'), function (el) {
      el.classList.toggle('is-active', el.getAttribute('data-id') === String(id));
    });
  }

  /* ── Routing ──────────────────────────────────────────────────────────── */
  function navigate(path, opts) {
    opts = opts || {};
    var route = resolvePath(path);
    if (opts.replace) {
      try { global.history.replaceState({ urai: route.path }, '', route.path); } catch (e) {}
    } else {
      try {
        if (global.location.pathname !== route.path) {
          global.history.pushState({ urai: route.path }, '', route.path);
        }
      } catch (e) {}
    }
    apply(route, opts);
  }

  function apply(route, opts) {
    var prev = current;
    current = route;
    markActive(route.name);
    setTitle(route.label);
    showView(route.name);
    var v = views[prev.name];
    if (prev.name !== route.name && v && typeof v.hide === 'function') {
      try { v.hide(); } catch (e) {}
    }
    try {
      global.dispatchEvent(new CustomEvent('urai:route', {
        detail: { path: route.path, name: route.name, route: route, opts: opts || {} }
      }));
    } catch (e) {}
  }

  function navigateByName(name, opts) {
    navigate(findRoute(name).path, opts);
  }

  /* ── Registration / start ─────────────────────────────────────────────── */
  function register(name, def) {
    views[name] = Object.assign({ mounted: false }, views[name] || {}, def || {});
    if (started && current.name === name) {
      mountView(name);
      var v = views[name];
      if (v && v.mounted && typeof v.show === 'function') v.show(viewEl(name));
    }
    return views[name];
  }

  function exposeAdmin() {
    var rail = els.navRail;
    if (!rail) return;
    var admin = rail.querySelector('[data-name="admin"]');
    if (admin) admin.hidden = false;
  }

  function bind() {
    els.app = global.document.getElementById('app') || global.document.querySelector('.app-shell');
    els.sidebar = global.document.getElementById('sidebar');
    els.navRail = global.document.getElementById('nav-rail');
    els.chatList = global.document.getElementById('chat-list');
    els.viewRoot = global.document.getElementById('view-root');
    els.title = global.document.getElementById('topbar-title');
    els.scrim = global.document.getElementById('scrim');
    els.collapseBtn = global.document.getElementById('collapse-btn');
    els.mobileBtn = global.document.getElementById('mobile-btn');

    if (els.collapseBtn) els.collapseBtn.addEventListener('click', toggleCollapse);
    if (els.mobileBtn) els.mobileBtn.addEventListener('click', toggleSidebar);
    if (els.scrim) els.scrim.addEventListener('click', closeMobile);

    global.addEventListener('resize', function () {
      applyCollapse();
      if (!isMobile()) closeMobile();
    });
    global.addEventListener('popstate', function () {
      apply(resolvePath(global.location.pathname));
    });
    global.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeMobile();
    });
  }

  function start() {
    if (started) return api;
    started = true;
    collapsed = lsGet(SIDEBAR_KEY, 'expanded') === 'collapsed';
    bind();
    buildNav();
    applyCollapse();
    var route = resolvePath(global.location.pathname);
    if (route.name === 'admin') exposeAdmin();
    // Normalise deep links such as /app/tasks into /tasks (keep / and /admin).
    if (global.location.pathname.indexOf('/app') === 0) {
      try { global.history.replaceState({ urai: route.path }, '', route.path); } catch (e) {}
    }
    apply(route);
    return api;
  }

  var api = {
    __urai: true,
    ROUTES: ROUTES,
    HIDDEN_ROUTES: HIDDEN_ROUTES,
    register: register,
    start: start,
    navigate: navigate,
    navigateByName: navigateByName,
    current: function () { return { path: current.path, name: current.name }; },
    resolve: resolvePath,
    renderConversations: renderConversations,
    setActiveConversation: setActiveConversation,
    setCollapsed: setCollapsed,
    toggleCollapse: toggleCollapse,
    isCollapsed: function () { return collapsed; },
    openMobile: openMobile,
    closeMobile: closeMobile,
    toggleSidebar: toggleSidebar,
    exposeAdmin: exposeAdmin,
    viewEl: viewEl
  };

  global.UraiShell = api;

  /* Auto-start as soon as the DOM is ready (host may also call start()). */
  if (global.document) {
    if (global.document.readyState === 'loading') {
      global.document.addEventListener('DOMContentLoaded', function () { start(); });
    } else {
      start();
    }
  }

  if (typeof module !== 'undefined' && module && module.exports) {
    module.exports = api;
  }
})(typeof window !== 'undefined' ? window : this);
