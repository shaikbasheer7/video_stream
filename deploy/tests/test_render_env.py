import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import render_env  # noqa: E402

PEM = "-----BEGIN PRIVATE KEY-----\nMIIabc\n-----END PRIVATE KEY-----\n"
CONFIG = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod", "DJANGO_ALLOWED_HOSTS": "app.example.com",
    "POSTGRES_HOST": "db.internal", "POSTGRES_DB": "streaming", "KAFKA_BOOTSTRAP_SERVERS": "b-1:9094,b-2:9094",
    "S3_BUCKET": "media", "CDN_BASE_URL": "https://media.example.com", "CLOUDFRONT_KEY_PAIR_ID": "K1",
    "AWS_REGION": "us-east-1",
}  # fmt: skip
# Generated passwords contain anything; these are the characters that break naive env files.
NASTY = "p@ss'w\"o$rd#1 \\x${HOME}"


@pytest.fixture
def files(tmp_path):
    def write(name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        return str(path)

    return {
        "config": write("config.json", CONFIG),
        "app": write(
            "app.json",
            {"DJANGO_SECRET_KEY": "k" * 50, "MONGO_URL": "mongodb+srv://u:p@x/?a=1&b=2", "CLOUDFRONT_PRIVATE_KEY": PEM},
        ),  # fmt: skip
        "db": write("db.json", {"username": "streaming", "password": NASTY}),
        "host": write("host.env", "ENVIRONMENT=staging\nECR_REGISTRY=1.dkr.ecr\nLOG_GROUP=/s/app\n# comment\n"),
        "pem": str(tmp_path / "cloudfront.pem"),
    }


def run(files, capsys):
    code = render_env.main([files["config"], files["app"], files["db"], files["host"], "--pem-out", files["pem"]])
    return code, capsys.readouterr()


def test_renders_every_source_and_writes_the_key_file(files, capsys):
    code, out = run(files, capsys)
    assert code == 0
    env = out.out
    assert 'POSTGRES_USER="streaming"' in env
    assert 'ENVIRONMENT="staging"' in env and 'POSTGRES_HOST="db.internal"' in env
    assert "PRIVATE KEY" not in env  # the PEM goes to its own file, never into the env file
    assert Path(files["pem"]).read_text() == PEM
    if os.name == "posix":
        assert oct(os.stat(files["pem"]).st_mode & 0o777) == "0o400"


def test_quoting_survives_compose_special_characters(files, capsys):
    _, out = run(files, capsys)
    line = next(line for line in out.out.splitlines() if line.startswith("POSTGRES_PASSWORD="))
    assert line == 'POSTGRES_PASSWORD="p@ss\'w\\"o$$rd#1 \\\\x$${HOME}"'


def test_missing_settings_are_named(files, capsys, tmp_path):
    (tmp_path / "app.json").write_text(json.dumps({"MONGO_URL": "x"}))
    code, out = run(files, capsys)
    assert code == 1
    assert "DJANGO_SECRET_KEY" in out.err and "CLOUDFRONT_PRIVATE_KEY" in out.err
    assert out.out == ""


def test_multiline_values_are_rejected():
    with pytest.raises(ValueError):
        render_env.quote("a\nb")
