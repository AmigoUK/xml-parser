"""Limit prób obecnego hasła przy zmianie hasła: osobna pula `pwchange:<e-mail>`, wspólny tylko limit per IP."""
from app.models import LoginAttempt
from app.services.login_guard import PASSWORD_CHANGE_PREFIX

EMAIL = "admin@example.com"
POOL = PASSWORD_CHANGE_PREFIX + EMAIL


def _change(client, current="zle", new="nowehaslo456"):
    return client.post("/konto/haslo", data={"current_password": current, "new_password": new,
                                             "new_password2": new})


def _login(client, password):
    return client.post("/login", data={"email": EMAIL, "password": password})


def _count(app, email):
    with app.app_context():
        return LoginAttempt.query.filter_by(email=email).count()


def test_locked_after_limit_wrong_current_passwords(app, auth_client):
    limit = app.config["LOGIN_MAX_ATTEMPTS"]
    for _ in range(limit):
        r = _change(auth_client)
        assert r.status_code == 200
        assert "Obecne hasło jest nieprawidłowe." in r.get_data(as_text=True)
    r = _change(auth_client, current="haslo123")  # nawet poprawne hasło jest już zablokowane
    assert r.status_code == 429
    assert "Zbyt wiele nieudanych prób zmiany hasła" in r.get_data(as_text=True)


def test_lockout_does_not_block_login_with_correct_password(app, auth_client):
    for _ in range(app.config["LOGIN_MAX_ATTEMPTS"] + 1):
        _change(auth_client)
    assert _change(auth_client).status_code == 429
    assert _login(auth_client, "haslo123").status_code == 302


def test_login_failures_do_not_count_for_password_change(app, auth_client):
    limit = app.config["LOGIN_MAX_ATTEMPTS"]
    for _ in range(limit):
        assert _login(auth_client, "zle").status_code == 200
    for _ in range(limit):
        assert _change(auth_client).status_code == 200  # pula pwchange nietknięta przez logowanie
    # i odwrotnie: każda pula ma dokładnie swoje próby
    assert _count(app, EMAIL) == limit
    assert _count(app, POOL) == limit


def test_correct_current_password_clears_prefixed_failures(app, auth_client):
    _change(auth_client)
    _change(auth_client)
    assert _count(app, POOL) == 2
    r = _change(auth_client, current="haslo123")
    assert r.status_code == 302
    assert _count(app, POOL) == 0


def test_blocked_attempt_is_discarded(app, auth_client):
    limit = app.config["LOGIN_MAX_ATTEMPTS"]
    for _ in range(limit):
        _change(auth_client)
    for _ in range(3):
        assert _change(auth_client).status_code == 429
    assert _count(app, POOL) == limit  # zablokowane próby nie przedłużają blokady


def test_login_with_reserved_prefix_does_not_touch_password_change_pool(app, auth_client):
    for _ in range(60):
        r = auth_client.post("/login", data={"email": POOL, "password": "zle"})
        assert r.status_code == 200
        assert "Nieprawidłowy e-mail lub hasło." in r.get_data(as_text=True)
    assert _count(app, POOL) == 0
    with app.app_context():
        assert LoginAttempt.query.count() == 0
    assert _change(auth_client, current="haslo123").status_code == 302
