/* Epilepscreen reusable overlay widget. No dependencies, single file.
 *
 * Drop this script onto any page with a <video>, then:
 *   window.Epilepscreen.attach(video, { eventsUrl: '/events/123/' });
 *
 * It fetches timestamped hazard events and, while currentTime falls inside an
 * event window, dims a transparent overlay layered over the video so only the
 * hazardous segments are suppressed. Safe defaults + graceful degradation.
 */
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
    if (video.parentElement.style) video.parentElement.style.position = 'relative';
    video.parentElement.appendChild(overlay);
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

  window.Epilepscreen = {
    attach: function (video, options) {
      const opts = Object.assign({}, options || {});
      const dimFilter = opts.dimFilter || 'rgba(0,0,0,0.65)';
      const padding = opts.paddingSeconds || 0;
      const overlay = createOverlay(video);
      let events = [];
      let dimmed = false;

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

      const onTick = function () {
        const should = inHazard(video.currentTime, events, padding);
        if (should !== dimmed) {
          dimmed = should;
          setDimmed(overlay, dimFilter, should);
          setBadge(should);
        }
      };

      refresh();
      video.addEventListener('timeupdate', onTick);

      return {
        detach: function () {
          video.removeEventListener('timeupdate', onTick);
          setDimmed(overlay, dimFilter, false);
          setBadge(false);
        },
        _internals: {
          _inHazard: inHazard,
          _simulate: function (t) { video.currentTime = t; onTick(); },
          _badgeShown: function () { return badge.style.display === 'block'; },
          _dimmed: function () { return dimmed; },
        },
      };
    },
  };
})();
