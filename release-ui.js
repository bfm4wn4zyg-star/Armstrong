(function () {
  'use strict';
  var mask = document.getElementById('mask');
  var drawer = mask.querySelector('.drawer');
  var shell = document.querySelector('.dashboard-shell');
  var wasOpen = false, previousFocus = null;
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-modal', 'true');
  drawer.setAttribute('aria-labelledby', 'drawerTitle');
  drawer.tabIndex = -1;
  var close = drawer.querySelector('.close');
  close.setAttribute('aria-label', window.DASHBOARD_LANG === 'en' ? 'Close details' : '关闭详情');
  function focusable() {
    return Array.from(drawer.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])')).filter(function (element) { return element.getClientRects().length && !element.closest('[hidden]'); });
  }
  new MutationObserver(function () {
    var open = mask.classList.contains('show');
    if (open === wasOpen) return;
    wasOpen = open;
    shell.inert = open;
    if (open) {
      previousFocus = document.activeElement;
      (focusable()[0] || drawer).focus();
    } else if (previousFocus && previousFocus.isConnected) previousFocus.focus();
  }).observe(mask, {attributes:true, attributeFilter:['class']});
  mask.addEventListener('keydown', function (event) {
    if (!mask.classList.contains('show')) return;
    if (event.key === 'Escape') {
      event.preventDefault();event.stopPropagation();window.closeDrawer();return;
    }
    if (event.key !== 'Tab') return;
    var elements = focusable(), first = elements[0] || drawer, last = elements[elements.length - 1] || drawer;
    if (!elements.length || event.shiftKey && document.activeElement === first) {
      event.preventDefault();last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();first.focus();
    }
  });
})();
