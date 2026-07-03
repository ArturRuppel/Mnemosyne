// DEPRECATED — the PWA tab shell this drove was retired for limited usefulness.
// No generated page includes this script and the server no longer serves it; the
// file is kept only as scaffold in case the multitab shell is ever revived. See
// also catalog/shell.html.
//
// Shared by every generated/static catalog page. Provides navigate(url, opts)
// and intercepts clicks so that, inside the installed PWA's tab shell, plain
// clicks replace the active tab and middle-click/Ctrl-Cmd-click open a new
// tab — mirroring normal browser tab conventions instead of escaping the PWA.
// Outside the shell (bookmarked page, share bundle) it falls back to the
// page's pre-shell behavior: full-window navigation / a real new browser tab.
(function () {
    'use strict';

    var inShell = false;
    try {
        inShell = window.parent !== window.self && window.parent.__ELN_SHELL__ === true;
    } catch (e) {
        inShell = false;
    }

    window.navigate = function (url, opts) {
        opts = opts || {};
        if (inShell) {
            window.parent.postMessage(
                {type: 'tabnav:navigate', url: url, newTab: !!opts.newTab},
                window.location.origin
            );
        } else if (opts.newTab) {
            window.open(url, '_blank');
        } else {
            window.location.href = url;
        }
    };

    if (inShell) {
        // Tells the shell what to show as this tab's title. Sent once per
        // load since generated pages don't change <title> after load.
        window.addEventListener('load', function () {
            window.parent.postMessage(
                {type: 'tabnav:title', title: document.title},
                window.location.origin
            );
        });
    }

    // Find the in-app navigation target for a click, or null if this click
    // isn't ours to handle (external link, anchor-only "#" link, an <a>
    // with an explicit target other than _self/"").
    function resolveTarget(el) {
        var a = el.closest && el.closest('a[href]');
        if (a) {
            if (a.target && a.target !== '_self') return null;
            var href = a.getAttribute('href');
            if (!href || href.charAt(0) === '#') return null;
            if (/^(https?:)?\/\//i.test(href) || href.indexOf('mailto:') === 0
                || href.indexOf('tel:') === 0) return null;
            return href;
        }
        // Non-anchor clickable elements (e.g. the explorer tree's report
        // rows) expose their target via data-nav-href instead of a real
        // href, since a <div> has no native click-to-navigate behavior to
        // intercept in the first place.
        var marked = el.closest && el.closest('[data-nav-href]');
        if (marked) return marked.dataset.navHref;
        return null;
    }

    document.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button !== 0) return;
        var url = resolveTarget(e.target);
        if (!url) return;
        e.preventDefault();
        navigate(url, {newTab: e.ctrlKey || e.metaKey});
    });

    document.addEventListener('auxclick', function (e) {
        if (e.button !== 1) return; // middle button only
        var url = resolveTarget(e.target);
        if (!url) return;
        e.preventDefault();
        navigate(url, {newTab: true});
    });
})();
