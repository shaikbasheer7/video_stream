import pytest
from django.db import connection
from rest_framework.test import APIClient

from accounts.models import User
from common import kafka, storage
from videos.models import Video
from videos.uploads import part_size_for

MiB = 1024**2


class FakeS3:
    """In-memory stand-in for common.storage."""

    def __init__(self):
        self.objects = {}  # key -> size
        self.multipart = {}  # upload_id -> key
        self.deleted = []
        self.deleted_prefixes = []
        self.aborted = []

    def install(self, monkeypatch):
        monkeypatch.setattr(storage, "presign_put", lambda key, ct, exp: f"https://s3.test/{key}?sig=put")
        monkeypatch.setattr(storage, "create_multipart_upload", self.create_multipart_upload)
        monkeypatch.setattr(storage, "presign_part", lambda key, uid, n, exp: f"https://s3.test/{key}?part={n}")
        monkeypatch.setattr(storage, "complete_multipart_upload", self.complete_multipart_upload)
        monkeypatch.setattr(storage, "abort_multipart_upload", lambda key, uid: self.aborted.append(uid))
        monkeypatch.setattr(storage, "head_object", self.head_object)
        monkeypatch.setattr(storage, "delete_object", self.deleted.append)
        monkeypatch.setattr(storage, "delete_prefix", self.deleted_prefixes.append)

    def create_multipart_upload(self, key, content_type):
        upload_id = f"upload-{len(self.multipart) + 1}"
        self.multipart[upload_id] = key
        return upload_id

    def complete_multipart_upload(self, key, upload_id, parts):
        self.completed_parts = parts

    def head_object(self, key):
        return {"ContentLength": self.objects[key]} if key in self.objects else None


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def published(monkeypatch):
    messages = []

    def fake_publish(topic, key, payload, event=None, timeout=10.0):
        messages.append({"topic": topic, "key": str(key), **kafka.build_event(event or topic, payload)})

    monkeypatch.setattr(kafka, "publish", fake_publish)
    return messages


@pytest.fixture
def owner():
    return User.objects.create_user(email="owner@example.com", password="pw-123456789", display_name="Owner")


@pytest.fixture
def api(owner):
    client = APIClient()
    client.force_authenticate(owner)
    return client


@pytest.fixture
def stranger_api():
    client = APIClient()
    client.force_authenticate(User.objects.create_user(email="other@example.com", password="pw-123456789"))
    return client


def create(api, size=10 * MiB, filename="clip.mp4", content_type="video/mp4"):
    return api.post(
        "/api/videos/",
        {"title": "My clip", "description": "", "filename": filename, "size": size, "content_type": content_type},
        format="json",
    )


@pytest.mark.django_db
def test_small_file_gets_single_presigned_put(api, s3):
    response = create(api)
    assert response.status_code == 201
    video = Video.objects.get(pk=response.data["video"]["id"])
    assert video.status == Video.Status.UPLOADING
    assert video.source_key == f"raw/{video.id}/source.mp4"
    upload = response.data["upload"]
    assert upload["method"] == "single"
    assert upload["url"].startswith(f"https://s3.test/raw/{video.id}/source.mp4")
    assert upload["headers"] == {"Content-Type": "video/mp4"}


@pytest.mark.django_db
def test_large_file_gets_multipart_urls(api, s3):
    response = create(api, size=250 * MiB, filename="big.MOV", content_type="video/quicktime")
    assert response.status_code == 201
    upload = response.data["upload"]
    assert upload["method"] == "multipart"
    assert upload["part_size"] == 16 * MiB
    assert [p["part_number"] for p in upload["parts"]] == list(range(1, 17))  # ceil(250 / 16)
    video = Video.objects.get(pk=response.data["video"]["id"])
    assert video.upload_id == "upload-1"
    assert video.source_key.endswith("source.mov")


def test_part_size_grows_to_stay_under_s3_part_limit():
    assert part_size_for(100 * MiB) == 16 * MiB
    huge = 500 * 1024**3
    assert huge / part_size_for(huge) <= 10_000


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("filename", "content_type", "size", "field"),
    [
        ("notes.txt", "text/plain", MiB, "filename"),
        ("noext", "video/mp4", MiB, "filename"),
        ("clip.mp4", "video/webm", MiB, "content_type"),
        ("clip.mp4", "video/mp4", 6 * 1024**3, "size"),
    ],
)
def test_create_rejects_bad_files(api, s3, filename, content_type, size, field):
    response = create(api, size=size, filename=filename, content_type=content_type)
    assert response.status_code == 400
    assert field in response.data
    assert not Video.objects.exists()


@pytest.mark.django_db
def test_create_requires_auth(s3):
    assert create(APIClient()).status_code == 401


@pytest.mark.django_db
def test_complete_publishes_video_uploaded_once(api, s3, published, owner):
    video_id = create(api).data["video"]["id"]
    s3.objects[f"raw/{video_id}/source.mp4"] = 10 * MiB

    response = api.post(f"/api/videos/{video_id}/complete/", {}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "uploaded"
    assert len(published) == 1
    message = published[0]
    assert message["topic"] == "video.uploaded"
    assert message["key"] == video_id
    assert message["video_id"] == video_id
    assert message["source_key"] == f"raw/{video_id}/source.mp4"
    assert message["owner_id"] == owner.id
    assert message["schema_version"] == 1
    assert message["event_id"]

    # Still 'uploaded' (encoder hasn't claimed it): a retry re-publishes; the encoder skips duplicates.
    assert api.post(f"/api/videos/{video_id}/complete/", {}, format="json").status_code == 200
    assert len(published) == 2

    # Once encoding has started, retries do nothing.
    Video.objects.filter(pk=video_id).update(status=Video.Status.PROCESSING)
    assert api.post(f"/api/videos/{video_id}/complete/", {}, format="json").status_code == 200
    assert len(published) == 2


@pytest.mark.django_db
def test_complete_fails_when_object_missing_or_wrong_size(api, s3, published):
    video_id = create(api).data["video"]["id"]
    assert api.post(f"/api/videos/{video_id}/complete/", {}, format="json").status_code == 400

    s3.objects[f"raw/{video_id}/source.mp4"] = 5
    response = api.post(f"/api/videos/{video_id}/complete/", {}, format="json")
    assert response.status_code == 400
    assert "does not match" in response.data["detail"]
    assert Video.objects.get(pk=video_id).status == Video.Status.UPLOADING
    assert published == []


@pytest.mark.django_db
def test_complete_multipart_requires_parts_then_assembles(api, s3, published, monkeypatch):
    video_id = create(api, size=200 * MiB).data["video"]["id"]
    key = f"raw/{video_id}/source.mp4"
    assert api.post(f"/api/videos/{video_id}/complete/", {}, format="json").status_code == 400

    def complete(k, upload_id, parts):
        s3.completed_parts = parts
        s3.objects[k] = 200 * MiB

    monkeypatch.setattr(storage, "complete_multipart_upload", complete)
    parts = [{"part_number": n, "etag": f'"etag-{n}"'} for n in range(1, 14)]
    response = api.post(f"/api/videos/{video_id}/complete/", {"parts": parts}, format="json")
    assert response.status_code == 200
    assert s3.completed_parts[0] == {"part_number": 1, "etag": '"etag-1"'}
    assert s3.objects[key] == 200 * MiB
    assert Video.objects.get(pk=video_id).upload_id == ""


@pytest.mark.django_db(transaction=True)
def test_publish_happens_after_commit_and_failure_is_retryable(api, s3, monkeypatch):
    in_transaction = []

    def publish(topic, key, payload, event=None, timeout=10.0):
        # A consumer only sees committed rows, so no transaction may be open when the message goes out.
        in_transaction.append(connection.in_atomic_block)
        if len(in_transaction) == 1:
            raise kafka.PublishError("broker down")

    monkeypatch.setattr(kafka, "publish", publish)
    video_id = create(api).data["video"]["id"]
    s3.objects[f"raw/{video_id}/source.mp4"] = 10 * MiB

    assert api.post(f"/api/videos/{video_id}/complete/", {}, format="json").status_code == 503
    assert Video.objects.get(pk=video_id).status == Video.Status.UPLOADED
    assert api.post(f"/api/videos/{video_id}/complete/", {}, format="json").status_code == 200
    assert in_transaction == [False, False]


@pytest.mark.django_db
def test_only_owner_can_complete_delete_or_see_unready_video(api, stranger_api, s3, published):
    video_id = create(api).data["video"]["id"]
    s3.objects[f"raw/{video_id}/source.mp4"] = 10 * MiB
    assert stranger_api.get(f"/api/videos/{video_id}/").status_code == 404
    assert stranger_api.post(f"/api/videos/{video_id}/complete/", {}, format="json").status_code == 404
    assert stranger_api.delete(f"/api/videos/{video_id}/").status_code == 404
    assert api.get(f"/api/videos/{video_id}/").status_code == 200


@pytest.mark.django_db
def test_list_shows_ready_videos_and_mine_shows_all_own(api, stranger_api, s3, owner):
    create(api)
    Video.objects.create(
        owner=owner, title="Done", original_filename="d.mp4", content_type="video/mp4", size_bytes=1,
        source_key="raw/x/source.mp4", status=Video.Status.READY,
    )  # fmt: skip
    public = stranger_api.get("/api/videos/")
    assert [v["title"] for v in public.data["results"]] == ["Done"]
    mine = api.get("/api/videos/?mine=true")
    assert {v["status"] for v in mine.data["results"]} == {"uploading", "ready"}
    assert all(v["is_owner"] for v in mine.data["results"])


@pytest.mark.django_db
def test_delete_aborts_multipart_and_removes_all_files(api, s3):
    video_id = create(api, size=200 * MiB).data["video"]["id"]
    assert api.delete(f"/api/videos/{video_id}/").status_code == 204
    assert s3.aborted == ["upload-1"]
    assert s3.deleted == [f"raw/{video_id}/source.mp4"]
    assert s3.deleted_prefixes == [f"hls/{video_id}/", f"thumbnails/{video_id}/"]
    assert not Video.objects.filter(pk=video_id).exists()
