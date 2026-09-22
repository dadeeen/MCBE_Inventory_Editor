/* Keep the local server alive while the user completes login or setup. */
(() => {
    "use strict";
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    if (!token) return;
    const heartbeat = () => fetch("/api/heartbeat", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": token },
    }).catch(() => {});
    heartbeat();
    window.setInterval(heartbeat, 5000);
})();
