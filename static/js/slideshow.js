/* SDZ launch slideshows (Mpumalanga, Northern Cape). One independent instance per [data-slideshow].
   - Starts automatically, 10 s per image, loops forever.
   - One timer only; timing is anchored to an ideal schedule so it cannot drift.
   - Fade is a CSS crossfade inside the 10 s window; it adds no delay. */
(function () {
  'use strict';
  function init(root) {
  if (!root || root.getAttribute('data-ss-ready') === '1') return; // prevent duplicate instances
  root.setAttribute('data-ss-ready', '1');

  var INTERVAL = 10000, FADE_MS = 950;
  var slides = Array.prototype.slice.call(root.querySelectorAll('.ss-slide'));
  var cur = root.querySelector('[data-ss-current]');
  var toggle = root.querySelector('[data-ss-toggle]');
  var timer = null, cleanup = null, anchor = Date.now(), paused = false, pos = 0;

  function valid() { return slides.filter(function (s) { return !s.classList.contains('is-broken'); }); }

  slides.forEach(function (s) {
    var img = s.querySelector('img');
    img.addEventListener('error', function () {
      var wasActive = s.classList.contains('is-active');
      s.classList.add('is-broken');
      if (wasActive && valid().length) { s.classList.remove('is-active'); pos = 0; show(0, true); }
      var t = root.querySelector('[data-ss-total]'); if (t) t.textContent = valid().length;
    });
  });

  function show(i, instant) {
    var list = valid(); if (!list.length) return;
    pos = ((i % list.length) + list.length) % list.length;
    var next = list[pos];
    clearTimeout(cleanup);
    slides.forEach(function (s) {
      if (s === next) return;
      if (s.classList.contains('is-active') && !instant) { s.classList.remove('is-active'); s.classList.add('is-prev'); }
      else s.classList.remove('is-active', 'is-prev');
    });
    next.classList.remove('is-prev');
    next.classList.add('is-active');
    cur.textContent = pos + 1;
    var after = list[(pos + 1) % list.length]; // warm the cache for the next image
    if (after && after.firstElementChild) after.firstElementChild.loading = 'eager';
    cleanup = setTimeout(function () { slides.forEach(function (s) { if (s !== next) s.classList.remove('is-prev'); }); }, FADE_MS);
  }

  function schedule() {
    clearTimeout(timer);
    if (paused) return;
    timer = setTimeout(tick, Math.max(0, anchor + INTERVAL - Date.now()));
  }
  function tick() {
    var steps = Math.max(1, Math.floor((Date.now() - anchor) / INTERVAL)); // catches up after throttled background tabs
    anchor += steps * INTERVAL;
    show(pos + steps);
    schedule();
  }
  function go(delta) { anchor = Date.now(); show(pos + delta); schedule(); } // manual move restarts the 10 s window

  root.querySelector('[data-ss-prev]').addEventListener('click', function () { go(-1); });
  root.querySelector('[data-ss-next]').addEventListener('click', function () { go(1); });
  toggle.addEventListener('click', function () {
    paused = !paused;
    toggle.setAttribute('aria-pressed', String(paused));
    toggle.setAttribute('aria-label', paused ? 'Play slideshow' : 'Pause slideshow');
    toggle.textContent = paused ? '▶' : '❚❚';
    if (paused) clearTimeout(timer); else { anchor = Date.now(); schedule(); }
  });
  root.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') go(-1); else if (e.key === 'ArrowRight') go(1);
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && !paused && Date.now() - anchor >= INTERVAL) { clearTimeout(timer); tick(); }
  });

  show(0, true);
  schedule();
  }
  Array.prototype.forEach.call(document.querySelectorAll('[data-slideshow]'), init);
})();
