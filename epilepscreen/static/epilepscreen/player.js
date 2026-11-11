/* Player page: overlay wiring, timeline, protection controls.
 *
 * All the detection numbers on this page come from Python. This file only
 * renders a timeline from them, moves the video around, and hands the event
 * list to the reusable overlay widget in epilepscreen.js.
 */
(function () {
  'use strict';

  var video = document.getElementById('player-video');
  var stage = document.querySelector('[data-stage]');
  if (!video) return;

  var dataTag = document.getElementById('hazard-data');
  var events = [];
  try {
    events = JSON.parse((dataTag && dataTag.textContent) || '[]');
  } catch (err) {
    events = [];
  }

  var timeline = document.querySelector('[data-timeline]');
  var playhead = document.querySelector('[data-playhead]');
  var dimRange = document.querySelector('[data-dim-range]');
  var dimValue = document.querySelector('[data-dim-value]');
  var padRange = document.querySelector('[data-pad-range]');
  var padValue = document.querySelector('[data-pad-value]');
  var guardToggle = document.querySelector('[data-guard-toggle]');
  var nextButton = document.querySelector('[data-next-hazard]');
  var guardStatus = document.querySelector('[data-guard-status]');
  var screenForm = document.querySelector('[data-screen-form]');
  var screenStatus = document.querySelector('[data-screen-status]');

  var dim = dimRange ? Number(dimRange.value) / 100 : 0.65;
  var padding = padRange ? Number(padRange.value) / 1000 : 0.4;

  /* --- overlay --------------------------------------------------------- */

  var handle = null;
  if (window.Epilepscreen) {
    handle = window.Epilepscreen.attach(video, {
      fetchEvents: function () { return Promise.resolve(events); },
      paddingSeconds: padding,
      dimFilter: 'rgba(0,0,0,' + dim + ')',
      badgeText: 'Guard active',
    });
  }

  function applyDim() {
    if (stage) stage.style.setProperty('--guard-dim', String(dim));
  }
  applyDim();

  if (dimRange) {
    dimRange.addEventListener('input', function () {
      dim = Number(dimRange.value) / 100;
      if (dimValue) dimValue.textContent = Math.round(dim * 100) + '%';
      applyDim();
      if (handle && handle.setDimFilter) {
        handle.setDimFilter('rgba(0,0,0,' + dim + ')');
      }
    });
  }

  if (padRange) {
    padRange.addEventListener('input', function () {
      padding = Number(padRange.value) / 1000;
      if (padValue) padValue.textContent = padding.toFixed(1) + ' s';
      if (handle && handle.setPadding) handle.setPadding(padding);
    });
  }

  if (guardToggle) {
    guardToggle.addEventListener('change', function () {
      if (handle) handle.setEnabled(guardToggle.checked);
      if (guardStatus) {
        guardStatus.textContent = guardToggle.checked
          ? 'Guard armed for ' + events.length + ' window(s).'
          : 'Guard off. The overlay will not dim.';
      }
    });
  }

  /* --- timeline -------------------------------------------------------- */

  var segments = [];
  function buildTimeline() {
    if (!timeline) return;
    segments.forEach(function (node) { node.remove(); });
    segments = [];
    var duration = video.duration;
    if (!duration || !isFinite(duration)) return;
    events.forEach(function (event) {
      var start = Math.max(0, Math.min(duration, event.start));
      var end = Math.max(start, Math.min(duration, event.end));
      var node = document.createElement('button');
      node.type = 'button';
      node.className = 'timeline__seg';
      node.dataset.kind = event.kind;
      node.style.left = (start / duration) * 100 + '%';
      node.style.width = Math.max(0.4, ((end - start) / duration) * 100) + '%';
      node.title = event.label + ' at ' + start.toFixed(1) + 's';
      node.setAttribute('aria-label', 'Jump to ' + event.label + ' at ' + start.toFixed(1) + ' seconds');
      node.addEventListener('click', function () { seekTo(start); });
      timeline.appendChild(node);
      segments.push(node);
    });
  }

  video.addEventListener('loadedmetadata', function () {
    buildTimeline();
    if (playhead) playhead.style.left = '0%';
  });
  video.addEventListener('durationchange', buildTimeline);
  // The metadata may already be in when this script runs (it sits at the end
  // of the body), so try to build once straight away as well.
  if (video.readyState >= 1) buildTimeline();

  video.addEventListener('timeupdate', function () {
    if (!playhead) return;
    var duration = video.duration;
    if (!duration || !isFinite(duration)) return;
    playhead.style.left = (video.currentTime / duration) * 100 + '%';
  });

  function seekTo(seconds) {
    video.currentTime = Math.max(0, seconds);
    var play = video.play();
    if (play && play.catch) play.catch(function () {});
  }

  document.querySelectorAll('[data-seek]').forEach(function (button) {
    button.addEventListener('click', function () {
      seekTo(Number(button.getAttribute('data-seek')));
    });
  });

  function nextHazard() {
    var now = video.currentTime;
    var next = null;
    for (var i = 0; i < events.length; i++) {
      if (events[i].start > now + 0.25) { next = events[i]; break; }
    }
    if (!next && events.length) next = events[0];
    if (next) seekTo(next.start);
  }

  if (nextButton) nextButton.addEventListener('click', nextHazard);

  document.addEventListener('keydown', function (event) {
    var tag = (event.target && event.target.tagName) || '';
    if (/INPUT|TEXTAREA|SELECT/.test(tag) || event.metaKey || event.ctrlKey) return;
    if (event.key === 'n') { nextHazard(); }
    if (event.key === 'g' && guardToggle) {
      guardToggle.checked = !guardToggle.checked;
      guardToggle.dispatchEvent(new Event('change'));
    }
  });

  /* --- screening request ----------------------------------------------- */

  if (screenForm) {
    screenForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var button = screenForm.querySelector('[data-screen-button]');
      if (button) { button.disabled = true; button.textContent = 'Screening…'; }
      if (screenStatus) screenStatus.textContent = 'Decoding frames and measuring them. This can take a moment.';

      fetch(screenForm.getAttribute('action'), {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
      })
        .then(function (response) { return response.json().then(function (body) { return { ok: response.ok, body: body }; }); })
        .then(function (result) {
          if (!result.ok || !result.body.analyzed) {
            if (screenStatus) screenStatus.textContent = 'Screening failed: ' + (result.body.error || 'unknown error');
            if (button) { button.disabled = false; button.textContent = 'Screen this video'; }
            return;
          }
          if (screenStatus) {
            screenStatus.textContent = result.body.is_safe
              ? 'Screened: no triggers above the thresholds.'
              : 'Screened: ' + result.body.event_count + ' hazard window(s) found. Reloading…';
          }
          window.setTimeout(function () { window.location.reload(); }, 700);
        })
        .catch(function () {
          if (screenStatus) screenStatus.textContent = 'The request failed. Check the server log.';
          if (button) { button.disabled = false; button.textContent = 'Screen this video'; }
        });
    });
  }

  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input) return input.value;
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }
})();