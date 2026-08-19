# Photosensitive Detection — Reusable JS Overlay Widget — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, reusable JavaScript overlay widget (`Epilepscreen`) that queries stored hazard events for a video and suppresses **only the hazardous timestamps** by dimming a transparent overlay layered over any `<video>` element — droppable onto any page, including the Epilepscreen player.

**Architecture:** A single no-dependency JS file registers `window.Epilepscreen`. `attach(video, options)` loads events (from a provided URL or a `fetchEvents` callback), listens to the video's `timeupdate`, and toggles a full-size overlay element whenever `currentTime` falls inside an event window (with configurable padding and dim level). It degrades gracefully (no events → never dims; no options → sensible defaults). Plan 2 consumes the MySQL `hazard_event` rows produced by Plan 1.

**Tech Stack:** Plain vanilla JavaScript (no build step, no dependencies), Django static files for serving, the existing `templates/player.html`.

## Global Constraints

- No external JS libraries and no build tooling — the widget must work by dropping a single `.js` file onto a page.
- The widget MUST NOT hardcode the player page; it must work against any `<video>` element and any event source.
- Public API is exactly `window.Epilepscreen.attach(videoElement, options)`. `options.fetchEvents` (async `() => array`) and `options.eventsUrl` (string) are the two event sources; `options.dimFilter` (string), `options.paddingSeconds` (number), `options.badgeText` (string) configure behavior. Everything else is internal.
- Event shape consumed: `{kind, start, end}` (seconds). Extra fields are ignored.
- If an event fetch fails or returns no events, the widget must not error and must not dim.
- Working directory for all commands: `epilepsy-app/`.

---

### Task 1: Widget scaffold and overlay lifecycle

**Files:**
- Create: `epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.js`
- Test: `epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`

**Interfaces:**
- Produces:
  - `window.Epilepscreen.attach(video, options)` → `object` — attaches the guard; returns a handle with `detach()`.
  - Internal `_createOverlay(video)` → `HTMLElement` — a 100% absolute-positioned div inside the video's parent, `pointer-events: none`, `display: none`.
  - Internal `_setDimmed(overlay, dimFilter, on)` → `void` — toggles overlay visibility.

- [ ] **Step 1: Write the failing tests**

`epilepscreen/static/epilepscreen/epilepscreen.test.js`:
```js
// Run with: node --experimental-vm-modules (or plain node if the file is a script)
// This is a minimal, dependency-free DOM shim so the widget is testable in Node.
class FakeVideo {
  constructor() {
    this.currentTime = 0;
    this.parentElement = { appendChild: () => {}, querySelector: () => null };
  }
}
global.window = {};
require('./epilepscreen.js');
global.document = {
  createElement: (tag) => ({ tag, style: {}, dataset: {} }),
};

function fakeHandle() {
  return window.Epilepscreen.attach(new FakeVideo(), {
    eventsUrl: '',
    fetchEvents: async () => [{ kind: 'flicker', start: 5, end: 8 }],
  });
}

// Use node's built-in assert via a throw-based harness.
let failures = 0;
function assert(cond, msg) { if (!cond) { console.error('FAIL: ' + msg); failures++; } }

const h1 = fakeHandle();
assert(typeof h1.detach === 'function', 'attach returns a handle with detach()');
assert(typeof window.Epilepscreen.attach === 'function', 'Epilepscreen.attach exists');

setTimeout(() => {
  assert(failures === 0, failures + ' test(s) failed');
  if (failures === 0) console.log('OK: task 1 scaffold tests passed');
  process.exit(failures === 0 ? 0 : 1);
}, 50);
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`
Expected: exits non-zero (`TypeError: window.Epilepscreen.attach is not a function`).

- [ ] **Step 3: Write minimal implementation**

`epilepscreen/static/epilepscreen/epilepscreen.js`:
```js
/* Epilepscreen reusable overlay widget. No dependencies, single file. */
(function () {
  'use strict';

  function createOverlay(video) {
    let overlay = video.parentElement.querySelector('.epilepscreen-overlay');
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'epilepscreen-overlay';
    overlay.style.cssText =
      'position:absolute;top:0;left:0;width:100%;height:100%;' +
      'pointer-events:none;z-index:10;display:none;';
    video.parentElement.style.position = 'relative';
    video.parentElement.appendChild(overlay);
    return overlay;
  }

  function setDimmed(overlay, dimFilter, on) {
    if (!overlay) return;
    overlay.style.display = on ? 'block' : 'none';
    if (on) overlay.style.background = dimFilter;
  }

  window.Epilepscreen = {
    attach: function (video, options) {
      const opts = Object.assign({}, options || {});
      const dimFilter = opts.dimFilter || 'rgba(0,0,0,0.65)';
      const overlay = createOverlay(video);
      let events = [];
      let failed = false;

      const refresh = async function () {
        try {
          if (opts.fetchEvents) events = (await opts.fetchEvents()) || [];
          else if (opts.eventsUrl) {
            const res = await fetch(opts.eventsUrl);
            if (!res.ok) throw new Error('events fetch failed');
            events = (await res.json()).events || [];
          } else events = [];
        } catch (err) {
          failed = true;
          events = [];
        }
      };

      refresh();

      return {
        detach: function () {
          setDimmed(overlay, dimFilter, false);
        },
      };
    },
  };
})();
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`
Expected: `OK: task 1 scaffold tests passed`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add epilepscreen/static/epilepscreen/
git commit -m "feat: add reusable Epilepscreen overlay widget scaffold"
```

---

### Task 2: Per-timestamp suppression

**Files:**
- Modify: `epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.js`
- Test: `epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`

**Interfaces:**
- Consumes: `_createOverlay`, `_setDimmed`, internal `events` list.
- Produces:
  - Internal `_inHazard(currentTime, events, padding)` → `boolean` — True if `currentTime` falls within `[start - padding, end + padding]` of any event.

- [ ] **Step 1: Write the failing tests**

Append to `epilepscreen.test.js`:
```js
function extract(p) {
  // Grab the _inHazard helper via the public API surface used in tests.
  // The widget exposes it on the returned handle for testability.
  return h1;
}
```
Replace the last `setTimeout` block with:
```js
const h1 = fakeHandle();
const fns = h1._internals || {};
if (typeof fns._inHazard !== 'function') {
  console.error('FAIL: _inHazard not exposed for testing');
  process.exit(1);
}
const ev = [{ start: 10, end: 12 }];
assert(fns._inHazard(11, ev, 0) === true, 'inside event');
assert(fns._inHazard(5, ev, 0) === false, 'outside event');
assert(fns._inHazard(9, ev, 1) === true, 'padding extends start');
assert(fns._inHazard(13, ev, 1) === true, 'padding extends end');
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`
Expected: `_inHazard not exposed` → exit 1.

- [ ] **Step 3: Write minimal implementation**

In `epilepscreen.js`, add the helper and expose it, and add the `timeupdate` listener:
```js
  function inHazard(currentTime, events, padding) {
    const p = padding || 0;
    for (const e of events) {
      if (currentTime >= (e.start - p) && currentTime <= (e.end + p)) return true;
    }
    return false;
  }
```
Add `_internals` to the returned handle and wire the listener:
```js
      let dimmed = false;
      const padding = opts.paddingSeconds || 0;
      const onTick = function () {
        const should = inHazard(video.currentTime, events, padding);
        if (should !== dimmed) {
          dimmed = should;
          setDimmed(overlay, dimFilter, should);
        }
      };
      video.addEventListener('timeupdate', onTick);

      return {
        detach: function () {
          video.removeEventListener('timeupdate', onTick);
          setDimmed(overlay, dimFilter, false);
        },
        _internals: { _inHazard: inHazard },
      };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`
Expected: all asserts pass, exit 0.

- [ ] **Step 5: Commit**

```bash
git add epilepscreen/static/epilepscreen/
git commit -m "feat: per-timestamp overlay suppression driven by timeupdate"
```

---

### Task 3: Config, badge, and safe defaults

**Files:**
- Modify: `epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.js`
- Test: `epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`

**Interfaces:**
- Consumes: `_inHazard`, `_setDimmed`.
- Produces:
  - `options.badgeText` (string) — text shown in a small corner badge while dimmed (default `'Photosensitive guard active'`).
  - `options.badgeColor` (string) — badge text color (default `'#cf6679'`).
  - `options.paddingSeconds` (number) — seconds to pad each event window (default `0`).

- [ ] **Step 1: Write the failing tests**

Append to `epilepscreen.test.js` before the final setTimeout:
```js
const h2 = window.Epilepscreen.attach(new FakeVideo(), {
  fetchEvents: async () => [{ kind: 'flicker', start: 1, end: 2 }],
  badgeText: 'Dimmed',
});
// Emulate timeupdate entering a hazard.
h2._internals._simulate(1.5);
assert(h2._internals._badgeShown() === true, 'badge shown while dimmed');
h2._internals._simulate(0);
assert(h2._internals._badgeShown() === false, 'badge hidden when safe');
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`
Expected: `_simulate is not a function` → exit 1.

- [ ] **Step 3: Write minimal implementation**

In `epilepscreen.js`, add a badge element next to the overlay, expose `_simulate`/`_badgeShown`, and set the badge text/color:
```js
      let badge = video.parentElement.querySelector('.epilepscreen-badge');
      if (!badge) {
        badge = document.createElement('div');
        badge.className = 'epilepscreen-badge';
        badge.style.cssText =
          'position:absolute;top:8px;right:8px;z-index:11;padding:4px 8px;' +
          'font:12px sans-serif;background:rgba(0,0,0,0.7);border-radius:4px;display:none;';
        video.parentElement.appendChild(badge);
      }
      badge.textContent = opts.badgeText || 'Photosensitive guard active';
      badge.style.color = opts.badgeColor || '#cf6679';
      const setBadge = function (on) { badge.style.display = on ? 'block' : 'none'; };
```
Update `onTick` to call `setBadge(should)` alongside `setDimmed`. Add to the returned handle:
```js
        _internals: {
          _inHazard: inHazard,
          _simulate: function (t) { video.currentTime = t; onTick(); },
          _badgeShown: function () { return badge.style.display === 'block'; },
        },
```
In `detach`, also `setBadge(false)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`
Expected: all asserts pass, exit 0.

- [ ] **Step 5: Commit**

```bash
git add epilepscreen/static/epilepscreen/
git commit -m "feat: configurable dim badge with safe defaults"
```

---

### Task 4: Integration — player uses the widget and exposes events endpoint

**Files:**
- Modify: `epilepsy-app/epilepscreen/urls.py`
- Modify: `epilepsy-app/epilepscreen/views.py`
- Modify: `epilepsy-app/epilepscreen/views.py` (event-fetch view)
- Modify: `epilepsy-app/templates/player.html`

**Interfaces:**
- Consumes: `window.Epilepscreen.attach` (Tasks 1–3).
- Produces:
  - URL route `"events/<str:video_hash>/"` → `views.video_events(request, video_hash)`.
  - `views.video_events` → `JsonResponse` with `{"events": [{kind, start, end, attributes}]}` read from the `hazard_event` table.

- [ ] **Step 1: Add the events route and view**

Modify `epilepscreen/urls.py` to add `path("events/<str:video_hash>/", views.video_events, name="video_events")`. Append to `epilepscreen/views.py`:
```python
def video_events(request, video_hash):
    """Return stored hazard events for a video, for the overlay widget."""
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT kind, start_time, end_time, attributes FROM hazard_event "
            "WHERE video_hash = %s ORDER BY start_time",
            (int(video_hash),),
        )
        rows = cursor.fetchall()
        cursor.close()
        cnx.close()
    except Exception as exc:  # pragma: no cover - DB path
        return JsonResponse({"events": []})
    events = [
        {"kind": r["kind"], "start": float(r["start_time"]),
         "end": float(r["end_time"]),
         "attributes": r["attributes"]}
        for r in rows
    ]
    return JsonResponse({"events": events})
```

- [ ] **Step 2: Wire the widget into the player template**

In `templates/player.html`, add a `<script>` tag loading the widget before the inline script, and inside `playVideo` call `Epilepscreen.attach`:
```html
<script src="/static/epilepscreen/epilepscreen.js"></script>
```
```js
let guard = null;
function playVideo(path) {
    source.src = path;
    video.load();
    video.play();
    const hash = path.split('/').filter(Boolean)[1];
    if (guard) guard.detach();
    guard = window.Epilepscreen.attach(video, {
        eventsUrl: '/events/' + hash + '/',
        paddingSeconds: 0.2,
    });
}
```

- [ ] **Step 3: Run the widget test suite and Django check**

Run: `node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js`
Expected: exit 0.

Run: `python manage.py check`
Expected: `System check identified no issues.`

- [ ] **Step 4: Commit**

```bash
git add epilepscreen/urls.py epilepscreen/views.py templates/player.html
git commit -m "feat: integrate overlay widget into player and add events endpoint"
```

---

## Self-Review

**Spec coverage:** Reusable widget droppable onto any page → Task 1 (`window.Epilepscreen.attach`). Reads stored events from the DB → Task 4 (`/events/<hash>/` view) + `eventsUrl`. Suppresses only hazardous timestamps → Task 2 (`_inHazard` + `timeupdate`). Configurable dim/badge → Task 3. Safe defaults and no-error degradation → Global Constraints + Task 1/3. Player uses the same widget → Task 4.

**Placeholder scan:** No TBD/TODO. Every step has concrete code.

**Type consistency:** `attach`, `detach`, `_inHazard`, `_simulate`, `_badgeShown`, `_internals`, `eventsUrl`, `fetchEvents`, `paddingSeconds`, `dimFilter`, `badgeText`, `badgeColor` are consistent across tasks. Event objects are `{kind, start, end, attributes}` in both the view and the widget.

---

## Execution Handoff

**Plan complete and saved to `epilepsy-app/docs/superpowers/plans/2026-08-19-photosensitive-js-overlay.md`.**
