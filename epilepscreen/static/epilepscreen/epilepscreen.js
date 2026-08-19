/* Epilepscreen reusable overlay widget. No dependencies, single file.
 *
 * Drop this script onto any page with a <video>, then:
 *   window.Epilepscreen.attach(video, { eventsUrl: '/events/123/' });
 *
 * It dims a transparent overlay over the video while a photosensitive trigger
 * is active. Triggers come from either:
 *   - precomputed timestamped events (eventsUrl / fetchEvents), OR
 *   - live in-browser detection (liveDetect: true), which samples frames via a
 *     small canvas and flags luminance flashes.
 * Safe defaults + graceful degradation: if a cross-origin page blocks canvas
 * reads, live detection simply never dims (no false positives).
 */
(function () {
  'use strict';

  function createOverlay(video) {
    const parent = video.parentElement;
    const overlay = document.createElement('div');
    overlay.className = 'epilepscreen-overlay';
    overlay.style.cssText =
      'position:absolute;top:0;left:0;width:100%;height:100%;' +
      'pointer-events:none;z-index:10;display:none;';
    if (parent && parent.style) {
      if (!parent.style.position || parent.style.position === 'static') {
        parent.style.position = 'relative';
      }
      parent.appendChild(overlay);
    }
    return overlay;
  }

  function setDimmed(overlay, dimFilter, on) {
    if (!overlay) return;
    overlay.style.display = on ? 'block' : 'none';
    if (on) overlay.style.background = dimFilter;
  }

  function inHazard(currentTime, events, padding) {
    const p = padding || 0;
    for (const e of events || []) {
      if (currentTime >= (e.start - p) && currentTime <= (e.end + p)) return true;
    }
    return false;
  }

  function makeLiveDetector() {
    let lastLum = null;
    let hot = false;
    let hotUntil = 0;
    let canvas = null;
    let ctx = null;

    function ensureCtx() {
      if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.width = 32;
        canvas.height = 32;
        ctx = canvas.getContext('2d', { willReadFrequently: true });
      }
    }

    return {
      detect: function (video) {
        if (!video || video.readyState < 2) return false;
        try {
          ensureCtx();
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
          let sum = 0;
          let n = 0;
          for (let i = 0; i < d.length; i += 40) {
            sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
            n++;
          }
          const lum = n ? sum / n / 255 : 0;
          if (lastLum !== null && Math.abs(lum - lastLum) > 0.35) {
            hot = true;
            hotUntil = Date.now() + 250;
          } else if (Date.now() > hotUntil) {
            hot = false;
          }
          lastLum = lum;
          return hot;
        } catch (err) {
          // Cross-origin page (e.g. YouTube) taints the canvas -> never dim.
          return false;
        }
      },
    };
  }

  window.Epilepscreen = {
    attach: function (video, options) {
      const opts = Object.assign({}, options || {});
      const dimFilter = opts.dimFilter || 'rgba(0,0,0,0.65)';
      const padding = opts.paddingSeconds || 0;
      const overlay = createOverlay(video);
      let events = [];
      let dimmed = false;

      const badge = document.createElement('div');
      badge.className = 'epilepscreen-badge';
      badge.style.cssText =
        'position:absolute;top:8px;right:8px;z-index:11;padding:4px 8px;' +
        'font:12px sans-serif;background:rgba(0,0,0,0.7);border-radius:4px;display:none;';
      badge.textContent = opts.badgeText || 'Photosensitive guard active';
      badge.style.color = opts.badgeColor || '#cf6679';
      if (video.parentElement) video.parentElement.appendChild(badge);
      const setBadge = function (on) { badge.style.display = on ? 'block' : 'none'; };

      const refresh = async function () {
        try {
          if (opts.fetchEvents) {
            events = (await opts.fetchEvents()) || [];
          } else if (opts.eventsUrl) {
            const res = await fetch(opts.eventsUrl);
            if (!res.ok) throw new Error('events fetch failed');
            events = (await res.json()).events || [];
          } else {
            events = [];
          }
        } catch (err) {
          events = [];
        }
      };

      const live = opts.liveDetect ? makeLiveDetector() : null;
      let liveTimer = null;

      const tick = function () {
        const evHazard = inHazard(video.currentTime, events, padding);
        const liveHazard = live ? live.detect(video) : false;
        const should = evHazard || liveHazard;
        if (should !== dimmed) {
          dimmed = should;
          setDimmed(overlay, dimFilter, should);
          setBadge(should);
        }
      };

      refresh();
      video.addEventListener('timeupdate', tick);
      if (live) liveTimer = setInterval(tick, 100);

      return {
        detach: function () {
          video.removeEventListener('timeupdate', tick);
          if (liveTimer) clearInterval(liveTimer);
          setDimmed(overlay, dimFilter, false);
          setBadge(false);
          if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
          if (badge && badge.parentNode) badge.parentNode.removeChild(badge);
        },
        _internals: {
          _inHazard: inHazard,
          _simulate: function (t) { video.currentTime = t; tick(); },
          _badgeShown: function () { return badge.style.display === 'block'; },
          _dimmed: function () { return dimmed; },
        },
      };
    },
  };
})();
