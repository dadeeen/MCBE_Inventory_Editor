(function () {
    "use strict";

    // Runs before the application modules and deliberately has no dependencies.
    // A failed bootstrap cannot use the application's own notification controller.
    const notice = document.getElementById("startupNotice");
    const failure = document.getElementById("startupFailure");
    const existing = document.getElementById("startupExisting");
    let ready = false;
    let failed = false;

    function fail() {
        if (ready || failed) return;
        failed = true;
        notice.hidden = false;
        notice.classList.add("toast-error");
        notice.setAttribute("role", "alert");
        failure.hidden = false;
        existing.hidden = true;
        document.querySelector(".app-container").inert = true;
        const message = document.getElementById("startupFailureTitle").textContent;
        for (const id of ["autoPathHint", "statusMsg", "statusStackSummary", "serverStatusBadge"]) {
            const target = document.getElementById(id);
            if (target) target.textContent = message;
        }
        for (const id of ["worldScanLoading", "loadingOverlay"]) {
            const target = document.getElementById(id);
            if (target) target.style.display = "none";
        }
    }

    function onError(event) {
        const scriptFailed = event.target?.tagName === "SCRIPT" && event.target.src;
        const appError = event.target === window
            && (!event.filename || event.filename.startsWith(`${location.origin}/static/`));
        if (scriptFailed || appError) fail();
        // Keep the original exception in the console for diagnosis.
    }

    window.addEventListener("error", onError, true);
    window.addEventListener("load", () => { if (!ready) fail(); }, { once: true });
    document.getElementById("startupReload").addEventListener("click", () => location.reload());
    document.getElementById("startupDismiss").addEventListener("click", () => { notice.hidden = true; });

    // The launcher only adds this marker after identifying an existing editor.
    const url = new URL(location.href);
    const alreadyRunning = url.searchParams.get("already_running") === "1";
    if (alreadyRunning) {
        url.searchParams.delete("already_running");
        history.replaceState(history.state, "", url);
    }

    window.MCBEStartupGuard = {
        hasFailed: () => failed,
        ready() {
            if (failed) return;
            ready = true;
            window.removeEventListener("error", onError, true);
            if (alreadyRunning) {
                notice.setAttribute("role", "status");
                notice.hidden = false;
                existing.hidden = false;
            }
        },
    };
}());
