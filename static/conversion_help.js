(function () {
    "use strict";
    const trigger = document.getElementById('btnConversionHelp');
    const popover = document.getElementById('conversionHelp');
    if (!trigger || !popover) return;
    function position() {
        if (!popover.matches(':popover-open')) return;
        const anchor = trigger.getBoundingClientRect();
        const width = popover.offsetWidth;
        const height = popover.offsetHeight;
        const left = Math.max(12, Math.min(anchor.left, window.innerWidth - width - 12));
        const below = anchor.bottom + 8;
        const top = below + height <= window.innerHeight - 12 ? below
            : Math.max(12, Math.min(anchor.top - height - 8, window.innerHeight - height - 12));
        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;
    }
    popover.addEventListener('toggle', event => {
        if (event.newState === 'open') {
            position();
            popover.querySelector('button').focus({ preventScroll: true });
        }
    });
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape' || !popover.matches(':popover-open')) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        popover.hidePopover();
        trigger.focus({ preventScroll: true });
    }, true);
}());
