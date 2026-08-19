# Epilepscreen Guard — Browser Extension

A reusable overlay widget that **dims videos while a photosensitive trigger is active**
(flashes, rapid luminance changes, high-contrast patterns). It runs on any site with a
`<video>` element — YouTube, Netflix, or your own Epilepscreen player — and dims only the
hazardous moments via a transparent overlay, leaving the rest of the video untouched.

- No dependencies, single file (`epilepscreen.js`)
- Manifest V3 → works in **Chrome** and **Firefox**
- **Live in-browser detection**: samples frames via a small canvas and flags luminance
  flashes. On cross-origin pages (e.g. YouTube) the browser blocks canvas reads, so the
  guard simply doesn't dim there — it never produces false positives.

## Where it works

| Source | Works | Notes |
|--------|-------|-------|
| YouTube / Netflix / direct `<video>` | ✅ | Direct video elements |
| YouTube embeds / any `<iframe>` player | ✅ | Content script runs in all frames |
| Videos added by SPAs after load | ✅ | MutationObserver + periodic re-scan |
| Custom players in **shadow DOM** | ✅ | Content script pierces open shadow roots |
| Adobe Flash | ⛔ | Flash is end-of-life (2020) and no browser runs it anymore; all Flash content now uses HTML5 `<video>`, which is covered |

If a page's video can't be read from a canvas (cross-origin), the guard **stays off** for it
rather than risk a false alarm — it never dims when it isn't sure.

---

## Install into Chrome

1. Open `chrome://extensions`.
2. Toggle **Developer mode** (top-right) ON.
3. Click **Load unpacked**.
4. Select the `browser-extension/` folder from this repo.
5. The **Epilepscreen Guard** card appears. It's now active on every page with a video.

## Install into Firefox

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…**.
3. Select `browser-extension/manifest.json`.
4. The add-on loads and runs until Firefox closes. (For a permanent install, package it via
   AMO using the same `browser-extension/` folder.)

---

## How it works

| Layer | File | Role |
|------|------|------|
| Content script | `content.js` | Injects the widget and attaches it to every `<video>` (re-scans as SPAs add videos). |
| Widget | `epilepscreen.js` | `window.Epilepscreen.attach(video, { liveDetect: true })` dims an overlay during triggers. |
| Manifest | `manifest.json` | Declares the content script + exposes the widget as a web-accessible script. |

### Reusing the widget without the extension

On any page of yours, load the widget and call:

```html
<script src="/epilepscreen.js"></script>
<script>
  const video = document.querySelector('video');
  window.Epilepscreen.attach(video, {
    liveDetect: true,        // live flash detection
    eventsUrl: '/events/123/', // OR precomputed hazard events from the server
    paddingSeconds: 0.2,
    dimFilter: 'rgba(0,0,0,0.65)',
    badgeText: 'Photosensitive guard active',
  });
</script>
```

The `eventsUrl` path reads timestamped hazard events persisted by the Python analyzer
(`hazard_event` table); `liveDetect` is the self-contained fallback that needs no server.
