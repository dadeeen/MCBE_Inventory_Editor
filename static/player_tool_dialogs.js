(function () {
    "use strict";
    const doc = document;
    const t = window.t || (text => text);
    let active = null;
    let opener = null;
    let previousInert = false;
    const app = doc.querySelector('.app-container');
    function close() {
        if (!active) return;
        active.style.display = 'none';
        active.setAttribute('aria-hidden', 'true');
        active = null;
        if (app) app.inert = previousInert;
        opener?.focus({ preventScroll: true });
    }
    function otherOverlayOpen() {
        return [...doc.querySelectorAll('.modal-overlay, .loading-overlay')].some(el =>
            el !== active && getComputedStyle(el).display !== 'none');
    }
    doc.querySelectorAll('[data-player-tool]').forEach(button => {
        button.addEventListener('click', () => {
            const overlay = doc.getElementById(button.dataset.playerTool);
            if (!overlay || active) return;
            opener = button;
            active = overlay;
            const context = overlay.querySelector('[data-player-tool-context]');
            if (context) context.textContent = doc.querySelector('#playersList .player-row.active .player-name')?.textContent?.trim()
                || t('Kein Spieler ausgewählt');
            previousInert = app?.inert || false;
            if (app) app.inert = true;
            overlay.style.display = 'flex';
            overlay.setAttribute('aria-hidden', 'false');
            overlay.querySelector('[data-close-player-tool]').focus();
        });
    });
    doc.querySelectorAll('[data-close-player-tool]').forEach(button => button.addEventListener('click', close));
    doc.addEventListener('keydown', event => {
        if (!active || otherOverlayOpen()) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopImmediatePropagation();
            close();
        } else if (event.key === 'Tab') {
            const controls = [...active.querySelectorAll('button, input, select, textarea, a[href], [tabindex="0"]')]
                .filter(el => !el.disabled && el.getClientRects().length);
            const first = controls[0], last = controls[controls.length - 1];
            if (event.shiftKey && (doc.activeElement === first || !active.contains(doc.activeElement))) {
                event.preventDefault(); last?.focus();
            } else if (!event.shiftKey && (doc.activeElement === last || !active.contains(doc.activeElement))) {
                event.preventDefault(); first?.focus();
            }
        }
    }, true);
}());
