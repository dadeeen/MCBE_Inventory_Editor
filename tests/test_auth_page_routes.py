from types import SimpleNamespace
from unittest.mock import Mock

from mcbe_editor import auth_page_routes


class SessionDict(dict):
    def __init__(self):
        super().__init__()
        self.cleared = False

    def clear(self):
        self.cleared = True
        super().clear()


def _render_template(template, **context):
    return ("template", template, context)


def _redirect(target):
    return ("redirect", target)


def _url_for(endpoint):
    return f"/{endpoint}"


def _deps(**overrides):
    app_config = SimpleNamespace(
        auth_required=overrides.pop("auth_required", False),
        auth_username=overrides.pop("auth_username", "admin"),
        mode=overrides.pop("mode", "local"),
        worlds_root=overrides.pop("worlds_root", "C:/Worlds"),
        is_docker=overrides.pop("is_docker", False),
    )
    session = overrides.pop("session", SessionDict())
    deps = auth_page_routes.AuthPageDeps(
        app_config=app_config,
        setup_state=overrides.pop("setup_state", SimpleNamespace(save_password=Mock(return_value="stable-secret"), save_open=Mock())),
        session=session,
        logger=overrides.pop("logger", SimpleNamespace(info=Mock(), warning=Mock())),
        render_template=overrides.pop("render_template", _render_template),
        redirect=overrides.pop("redirect", _redirect),
        url_for=overrides.pop("url_for", _url_for),
        first_run_setup_required=overrides.pop("first_run_setup_required", Mock(return_value=True)),
        auth_enabled=overrides.pop("auth_enabled", Mock(return_value=True)),
        check_setup_post_token=overrides.pop("check_setup_post_token", Mock(return_value=None)),
        check_login_post_token=overrides.pop("check_login_post_token", Mock(return_value=None)),
        setup_csrf_token=overrides.pop("setup_csrf_token", Mock(return_value="setup-token")),
        get_csrf_token=overrides.pop("get_csrf_token", Mock(return_value="csrf-token")),
        valid_login=overrides.pop("valid_login", Mock(return_value=False)),
        safe_redirect_target=overrides.pop("safe_redirect_target", lambda target: target or "/"),
        effective_auth_username=overrides.pop("effective_auth_username", Mock(return_value="admin")),
        set_app_secret_key=overrides.pop("set_app_secret_key", Mock()),
        remote_addr=overrides.pop("remote_addr", Mock(return_value="127.0.0.1")),
        audit_event=overrides.pop("audit_event", Mock()),
        runtime_bind_host=overrides.pop("runtime_bind_host", "127.0.0.1"),
        runtime_bind_port=overrides.pop("runtime_bind_port", 5000),
    )
    assert not overrides
    return deps


def test_setup_get_renders_setup_template_with_token():
    deps = _deps()

    result = auth_page_routes.setup("GET", {}, deps)

    assert result[0] == "template"
    assert result[1] == "setup.html"
    assert result[2]["setup_token"] == "setup-token"
    assert result[2]["can_choose_open"] is True


def test_setup_password_rejects_mismatch_without_saving():
    setup_state = SimpleNamespace(save_password=Mock(return_value="stable-secret"), save_open=Mock())
    deps = _deps(setup_state=setup_state)

    result = auth_page_routes.setup(
        "POST",
        {"action": "password", "username": "admin", "password": "12345678", "password_confirm": "different"},
        deps,
    )

    assert result[0] == "template"
    assert "Die beiden Passwörter stimmen nicht überein." in result[2]["errors"]
    setup_state.save_password.assert_not_called()


def test_setup_password_success_sets_secret_clears_session_and_redirects():
    session = SessionDict()
    set_app_secret_key = Mock()
    setup_state = SimpleNamespace(save_password=Mock(return_value="stable-secret"), save_open=Mock())
    deps = _deps(session=session, set_app_secret_key=set_app_secret_key, setup_state=setup_state)

    result = auth_page_routes.setup(
        "POST",
        {"action": "password", "username": "admin", "password": "12345678", "password_confirm": "12345678"},
        deps,
    )

    assert result == ("redirect", "/login")
    assert session.cleared is True
    set_app_secret_key.assert_called_once_with("stable-secret")
    setup_state.save_password.assert_called_once()
    deps.audit_event.assert_called_once()


def test_login_success_sanitizes_redirect_and_starts_session(monkeypatch):
    monkeypatch.setattr(auth_page_routes.secrets, "token_urlsafe", Mock(return_value="new-csrf"))
    session = SessionDict()
    safe_redirect_target = Mock(return_value="/versions?from=login")
    deps = _deps(session=session, valid_login=Mock(return_value=True), safe_redirect_target=safe_redirect_target)

    result = auth_page_routes.login(
        "POST",
        {"next": "https://evil.example"},
        {"username": "admin", "password": "secret"},
        deps,
    )

    assert result == ("redirect", "/versions?from=login")
    assert session == {"authenticated": True, "csrf_token": "new-csrf"}
    safe_redirect_target.assert_called_once_with("https://evil.example")
    deps.audit_event.assert_called_once()


def test_failed_login_caps_and_escapes_username_in_application_log():
    logger = SimpleNamespace(info=Mock(), warning=Mock())
    deps = _deps(logger=logger)
    username = "x" * 200 + "\nforged-entry"

    auth_page_routes.login("POST", {}, {"username": username, "password": "wrong"}, deps)

    logger.warning.assert_called_once_with(
        "auth login_failure username=%r remote=%s",
        "x" * 120,
        "127.0.0.1",
    )


def test_logout_audits_and_clears_session():
    session = SessionDict()
    session["authenticated"] = True
    deps = _deps(session=session)

    result = auth_page_routes.logout(deps)

    assert result == ("redirect", "/login")
    assert session == {}
    assert session.cleared is True
    deps.audit_event.assert_called_once_with("auth.logout", "success")
