"""Handlers for setup, login, and logout pages."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from werkzeug.security import generate_password_hash

from .i18n import t


@dataclass(frozen=True)
class AuthPageDeps:
    app_config: Any
    setup_state: Any
    session: Any
    logger: Any
    render_template: Callable[..., Any]
    redirect: Callable[..., Any]
    url_for: Callable[..., str]
    first_run_setup_required: Callable[[], bool]
    auth_enabled: Callable[[], bool]
    check_setup_post_token: Callable[[], str | None]
    check_login_post_token: Callable[[], str | None]
    setup_csrf_token: Callable[[], str]
    get_csrf_token: Callable[[], str]
    valid_login: Callable[[str, str], bool]
    safe_redirect_target: Callable[[str | None], str]
    effective_auth_username: Callable[[], str]
    set_app_secret_key: Callable[[str], None]
    remote_addr: Callable[[], str]
    audit_event: Callable[..., None]
    runtime_bind_host: str | None
    runtime_bind_port: int | None


def setup(method: str, form: Any, deps: AuthPageDeps):
    if not deps.first_run_setup_required():
        return deps.redirect(deps.url_for("index"))

    errors: list[str] = []
    can_choose_open = not deps.app_config.auth_required

    if method == "POST":
        token_error = deps.check_setup_post_token()
        if token_error:
            errors.append(token_error)
        action = form.get("action", "").strip()
        if not errors and action == "password":
            username = form.get("username", deps.app_config.auth_username).strip() or deps.app_config.auth_username
            password = form.get("password", "")
            confirm = form.get("password_confirm", "")
            if len(password) < 8:
                errors.append(t("Das Passwort muss mindestens 8 Zeichen lang sein."))
            elif password != confirm:
                errors.append(t("Die beiden Passwörter stimmen nicht überein."))
            else:
                password_hash = generate_password_hash(password)
                stable_secret = deps.setup_state.save_password(username=username, password_hash=password_hash)
                deps.set_app_secret_key(stable_secret)
                deps.session.clear()
                deps.logger.info("setup completed mode=password username=%r remote=%s", username[:120], deps.remote_addr())
                deps.audit_event("setup.password", "success", details={"username": username})
                return deps.redirect(deps.url_for("login"))
        elif not errors and action == "open":
            if not can_choose_open:
                errors.append(t("Offener Betrieb ist deaktiviert, weil Authentifizierung explizit angefordert wurde."))
            elif form.get("risk_ack") != "yes":
                errors.append(t("Bitte bestätige die Risiko-Hinweise, wenn du ohne Passwort fortfahren möchtest."))
            else:
                deps.setup_state.save_open()
                deps.session.clear()
                deps.logger.warning("setup completed mode=open remote=%s risk_acknowledged=true", deps.remote_addr())
                deps.audit_event("setup.open", "success", details={"risk_acknowledged": True})
                return deps.redirect(deps.url_for("index"))
        elif not errors:
            errors.append(t("Bitte wähle Passwort aktivieren oder offen fortfahren."))

    return deps.render_template(
        "setup.html",
        errors=errors,
        setup_token=deps.setup_csrf_token(),
        default_username=deps.app_config.auth_username,
        can_choose_open=can_choose_open,
        bind_host=deps.runtime_bind_host,
        bind_port=deps.runtime_bind_port,
        mode=deps.app_config.mode,
        worlds_root=deps.app_config.worlds_root,
        docker_mode=deps.app_config.is_docker,
    )


def login(method: str, args: Any, form: Any, deps: AuthPageDeps):
    if not deps.auth_enabled():
        return deps.redirect(deps.url_for("index"))

    error = ""
    if method == "POST":
        token_error = deps.check_login_post_token()
        username = form.get("username", "").strip()
        password = form.get("password", "")
        if token_error:
            error = token_error
            deps.audit_event("auth.login", "failure", details={"reason": "csrf_or_origin"})
        elif deps.valid_login(username, password):
            deps.logger.info("auth login_success username=%r remote=%s", username[:120], deps.remote_addr())
            deps.audit_event("auth.login", "success", details={"username": username})
            deps.session.clear()
            deps.session["authenticated"] = True
            deps.session["csrf_token"] = secrets.token_urlsafe(32)
            target = deps.safe_redirect_target(args.get("next"))
            return deps.redirect(target)
        else:
            deps.logger.warning("auth login_failure username=%r remote=%s", (username or "<empty>")[:120], deps.remote_addr())
            deps.audit_event("auth.login", "failure", details={"username": username or "<empty>"})
            error = t("Ungültiger Benutzername oder Passwort.")

    return deps.render_template("login.html", error=error, auth_username=deps.effective_auth_username(), csrf_token=deps.get_csrf_token())


def logout(deps: AuthPageDeps):
    deps.logger.info("auth logout remote=%s", deps.remote_addr())
    deps.audit_event("auth.logout", "success")
    deps.session.clear()
    return deps.redirect(deps.url_for("login"))
