import pytest
from django.conf import settings
from rest_framework.test import APIClient

from accounts.models import User

PASSWORD = "correct-horse-battery-9"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user():
    return User.objects.create_user(email="viewer@example.com", password=PASSWORD, display_name="Viewer")


def login(client, email="viewer@example.com", password=PASSWORD):
    return client.post("/api/auth/login/", {"email": email, "password": password}, format="json")


@pytest.mark.django_db
def test_register_creates_user_with_lowercased_email(client):
    response = client.post(
        "/api/auth/register/",
        {"email": "New@Example.com", "password": PASSWORD, "display_name": "New"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["email"] == "new@example.com"
    assert "password" not in response.data
    assert User.objects.get(email="new@example.com").check_password(PASSWORD)


@pytest.mark.django_db
def test_register_rejects_duplicate_and_weak_password(client, user):
    dup = client.post("/api/auth/register/", {"email": "VIEWER@example.com", "password": PASSWORD}, format="json")
    assert dup.status_code == 400
    weak = client.post("/api/auth/register/", {"email": "x@example.com", "password": "123"}, format="json")
    assert weak.status_code == 400


@pytest.mark.django_db
def test_login_returns_access_and_sets_httponly_refresh_cookie(client, user):
    response = login(client)
    assert response.status_code == 200
    assert response.data["access"]
    assert response.data["user"]["email"] == user.email
    assert "refresh" not in response.data
    cookie = response.cookies[settings.REFRESH_COOKIE_NAME]
    assert cookie["httponly"]
    assert cookie["path"] == "/api/auth/"


@pytest.mark.django_db
def test_login_with_wrong_password_fails(client, user):
    assert login(client, password="nope").status_code == 401


@pytest.mark.django_db
def test_me_requires_access_token(client, user):
    assert client.get("/api/auth/me/").status_code == 401
    access = login(client).data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    response = client.get("/api/auth/me/")
    assert response.status_code == 200
    assert response.data["display_name"] == "Viewer"


@pytest.mark.django_db
def test_refresh_rotates_cookie_and_old_token_is_blacklisted(client, user):
    old_refresh = login(client).cookies[settings.REFRESH_COOKIE_NAME].value

    response = client.post("/api/auth/refresh/")
    assert response.status_code == 200
    assert response.data["access"]
    new_refresh = response.cookies[settings.REFRESH_COOKIE_NAME].value
    assert new_refresh != old_refresh

    replay = APIClient()
    replay.cookies[settings.REFRESH_COOKIE_NAME] = old_refresh
    assert replay.post("/api/auth/refresh/").status_code == 401


@pytest.mark.django_db
def test_refresh_without_cookie_is_401(client):
    assert client.post("/api/auth/refresh/").status_code == 401


@pytest.mark.django_db
def test_logout_blacklists_refresh_and_clears_cookie(client, user):
    refresh = login(client).cookies[settings.REFRESH_COOKIE_NAME].value
    response = client.post("/api/auth/logout/")
    assert response.status_code == 204
    assert response.cookies[settings.REFRESH_COOKIE_NAME].value == ""

    replay = APIClient()
    replay.cookies[settings.REFRESH_COOKIE_NAME] = refresh
    assert replay.post("/api/auth/refresh/").status_code == 401


@pytest.mark.django_db
def test_health(client):
    response = client.get("/api/health/")
    assert response.status_code == 200
    assert response.data == {"status": "ok"}
