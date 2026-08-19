/* Dependency-free Node test harness for the overlay widget.
 * Run: node epilepsy-app/epilepscreen/static/epilepscreen/epilepscreen.test.js
 */
'use strict';

class FakeVideo {
  constructor() {
    this.currentTime = 0;
    this._handlers = {};
    this.parentElement = {
      style: {},
      appendChild: () => {},
      querySelector: () => null,
    };
  }
  addEventListener(ev, fn) { this._handlers[ev] = fn; }
  removeEventListener(ev) { delete this._handlers[ev]; }
}

function makeElement(tag) {
  return { tag, style: {}, dataset: {}, textContent: '', className: '' };
}
global.document = { createElement: makeElement };
global.window = {};

require('./epilepscreen.js');

let failures = 0;
function assert(cond, msg) {
  if (!cond) { console.error('FAIL: ' + msg); failures++; }
}

(async () => {
  assert(typeof window.Epilepscreen.attach === 'function', 'attach exists');

  const video = new FakeVideo();
  const h1 = window.Epilepscreen.attach(video, {
    fetchEvents: async () => [{ kind: 'flicker', start: 5, end: 8 }],
    badgeText: 'Dimmed',
  });
  assert(typeof h1.detach === 'function', 'handle has detach');
  await new Promise((r) => setTimeout(r, 20)); // let refresh() resolve

  const fns = h1._internals;
  // Task 2: _inHazard window logic
  assert(fns._inHazard(6, [{ start: 5, end: 8 }], 0) === true, 'inside event');
  assert(fns._inHazard(3, [{ start: 5, end: 8 }], 0) === false, 'outside event');
  assert(fns._inHazard(4, [{ start: 5, end: 8 }], 1) === true, 'padding start');
  assert(fns._inHazard(9, [{ start: 5, end: 8 }], 1) === true, 'padding end');

  // Task 3: dim + badge toggling driven by playback position
  fns._simulate(6);
  assert(fns._dimmed() === true, 'dimmed while in hazard');
  assert(fns._badgeShown() === true, 'badge shown while dimmed');
  fns._simulate(2);
  assert(fns._dimmed() === false, 'not dimmed when safe');
  assert(fns._badgeShown() === false, 'badge hidden when safe');

  // liveDetect mode must not throw and still return a usable handle
  const v2 = new FakeVideo();
  v2.readyState = 2;
  const h2 = window.Epilepscreen.attach(v2, { liveDetect: true });
  assert(typeof h2.detach === 'function', 'liveDetect attach returns handle');
  h2.detach();

  h1.detach();
  if (failures === 0) console.log('OK: all overlay widget tests passed');
  else { console.error(failures + ' failure(s)'); process.exit(1); }
})();
