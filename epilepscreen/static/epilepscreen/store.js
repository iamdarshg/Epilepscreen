/* Storefront interactions: the source-browser dialog and small form aids.
 * Everything here is progressive. Without JavaScript the source links open
 * the same reader as a full page, and the order and upload forms post as usual.
 */
(function () {
  'use strict';

  var dialog = document.querySelector('[data-source-browser]');
  var frame = dialog ? dialog.querySelector('[data-browser-frame]') : null;
  var title = dialog ? dialog.querySelector('[data-browser-title]') : null;
  var status = dialog ? dialog.querySelector('[data-capture-status]') : null;
  var closeButton = dialog ? dialog.querySelector('[data-close-browser]') : null;

  function openBrowser(link) {
    if (!dialog || !frame || typeof dialog.showModal !== 'function') return false;
    var href = link.getAttribute('href');
    if (!href) return false;
    frame.src = href;
    if (title) {
      title.textContent = link.getAttribute('data-source-name') || 'Source browser';
    }
    if (status) {
      status.textContent = 'Direct video downloads are saved to the library.';
    }
    dialog.showModal();
    if (closeButton) closeButton.focus();
    return true;
  }

  document.querySelectorAll('[data-open-browser]').forEach(function (link) {
    link.addEventListener('click', function (event) {
      if (openBrowser(link)) event.preventDefault();
    });
  });

  if (dialog) {
    dialog.addEventListener('close', function () {
      if (frame) frame.src = 'about:blank';
    });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) dialog.close();
    });
  }

  if (closeButton && dialog) {
    closeButton.addEventListener('click', function () {
      dialog.close();
    });
  }

  window.addEventListener('message', function (event) {
    if (event.origin !== window.location.origin) return;
    var data = event.data || {};
    if (data.type !== 'epilepscreen-capture') return;
    if (!status) return;
    status.textContent = data.saved
      ? 'Saved ' + data.title + ' to the library.'
      : data.title + ' was already in the library.';
  });

  document.querySelectorAll('[data-file-input]').forEach(function (input) {
    var target = document.querySelector(input.getAttribute('data-file-input'));
    if (!target) return;
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      target.textContent = file ? file.name : 'No file chosen.';
    });
  });
})();
