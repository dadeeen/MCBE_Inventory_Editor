(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const TRANSIENT_DIRTY_NOTICE_CATEGORY = "dirty";
    const TRANSIENT_DIRTY_STATUS_TEXT = "Ungespeicherte Änderungen vorhanden";
    const STATUS_TYPES = new Set(["info", "running", "success", "warning", "error"]);

    function normalizeText(value) {
        return String(value || "").trim();
    }

    function isTransientDirtyStatusText(text) {
        return normalizeText(text) === t(TRANSIENT_DIRTY_STATUS_TEXT);
    }

    function normalizeStatusType(value) {
        const type = normalizeText(value).toLowerCase();
        return STATUS_TYPES.has(type) ? type : "info";
    }

    function normalizeAction(action) {
        const label = normalizeText(action?.label);
        return label && typeof action.onClick === "function" ? { label, onClick: action.onClick } : null;
    }

    function createStatusStore({ maxNotices = 8 } = {}) {
        let notices = [];

        function trimResolvedHistory() {
            const activeCount = notices.reduce((count, entry) => count + (entry.active ? 1 : 0), 0);
            let resolvedBudget = Math.max(0, maxNotices - activeCount);
            notices = notices.filter(entry => {
                if (entry.active) return true;
                if (resolvedBudget <= 0) return false;
                resolvedBudget -= 1;
                return true;
            });
        }

        function addNotice({
            time = "",
            type = "info",
            message = "",
            category = "",
            key = "",
            active = undefined,
            action = null,
        } = {}) {
            const normalizedType = normalizeStatusType(type);
            const normalizedCategory = normalizeText(category);
            const normalized = {
                time: normalizeText(time),
                type: normalizedType,
                message: normalizeText(message),
                category: normalizedCategory,
                key: normalizeText(key),
                active: typeof active === "boolean"
                    ? active
                    : (normalizedType === "running" || normalizedCategory === TRANSIENT_DIRTY_NOTICE_CATEGORY),
                // Offered while the notice is active; needs a key to be found again.
                action: normalizeText(key) ? normalizeAction(action) : null,
            };
            if (!normalized.message) return;

            if (normalized.key) {
                const previousIndex = notices.findIndex(entry => entry.key === normalized.key);
                if (previousIndex >= 0) notices.splice(previousIndex, 1);
            }

            const latest = notices[0];
            if (
                latest
                && latest.type === normalized.type
                && latest.message === normalized.message
                && latest.category === normalized.category
                && latest.key === normalized.key
                && latest.active === normalized.active
            ) {
                latest.time = normalized.time;
                latest.action = normalized.action;
                return;
            }

            notices.unshift(normalized);
            trimResolvedHistory();
        }

        function visibleNotices({ isDirty = false } = {}) {
            if (isDirty) return notices;
            return notices.filter(entry => entry.category !== TRANSIENT_DIRTY_NOTICE_CATEGORY);
        }

        function allNotices() {
            return notices.slice();
        }

        function noticeAction(key) {
            const normalizedKey = normalizeText(key);
            const notice = normalizedKey ? notices.find(entry => entry.key === normalizedKey) : null;
            return notice?.active ? notice.action : null;
        }

        function removeNotice(key) {
            const normalizedKey = normalizeText(key);
            if (!normalizedKey) return false;
            const previousLength = notices.length;
            notices = notices.filter(entry => entry.key !== normalizedKey);
            return notices.length !== previousLength;
        }

        function clear() {
            notices = [];
        }

        return {
            addNotice,
            allNotices,
            clear,
            noticeAction,
            removeNotice,
            visibleNotices,
        };
    }

    window.MCBEStatusStore = {
        TRANSIENT_DIRTY_NOTICE_CATEGORY,
        createStatusStore,
        isTransientDirtyStatusText,
        normalizeStatusType,
    };
}());
