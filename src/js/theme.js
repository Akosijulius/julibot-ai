// Applied synchronously in <head> before the stylesheet loads so the page is
// painted with the saved theme on the very first frame (no wrong-theme flash).
// CSP forbids inline scripts, so this must be an external file.
(function () {
    'use strict';

    var THEME_KEY = 'julibot_theme';
    var theme = 'default';

    try {
        var saved = localStorage.getItem(THEME_KEY);
        if (saved === 'light' || saved === 'dark') {
            theme = saved;
        }
    } catch (e) {
        // localStorage unavailable (private mode / disabled) — fall back to default
    }

    document.documentElement.setAttribute('data-theme', theme);
})();