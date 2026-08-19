// Epilepscreen Guard content script.
// Injects the reusable widget, then attaches it to every <video> it can find:
//   - direct <video> elements (YouTube, Netflix, custom players)
//   - videos inside iframes (handled automatically by "all_frames": true)
//   - videos added later by single-page apps (MutationObserver + re-scan)
//   - videos hidden inside open shadow roots (many embedded players)
(function () {
  'use strict';

  var SRC = chrome.runtime.getURL('epilepscreen.js');
  var seen = new WeakSet();

  function collectVideos(root) {
    var out = Array.prototype.slice.call(root.querySelectorAll('video'));
    var all = root.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (el.shadowRoot) out = out.concat(collectVideos(el.shadowRoot));
    }
    return out;
  }

  function start() {
    if (!window.Epilepscreen) return;
    collectVideos(document).forEach(function (v) {
      if (seen.has(v)) return;
      seen.add(v);
      try {
        window.Epilepscreen.attach(v, { liveDetect: true, paddingSeconds: 0.2 });
      } catch (e) {
        /* never let a bad video break the page */
      }
    });
  }

  var s = document.createElement('script');
  s.src = SRC;
  s.onload = function () {
    start();
    // Re-scan periodically so videos that appear later still get guarded.
    setInterval(start, 2500);
  };
  document.head.appendChild(s);

  var mo = new MutationObserver(function () { start(); });
  mo.observe(document.documentElement, { childList: true, subtree: true });
})();
