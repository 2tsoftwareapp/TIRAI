import pytest

from tirai import bootstrap
from tirai.scenario import validate
from tirai.system import parse_ffmpeg_version


def test_parse_ffmpeg_version():
    assert parse_ffmpeg_version("ffmpeg version 4.4.2-0ubuntu0.22.04.1 Copyright") == (4, 4)
    assert parse_ffmpeg_version("ffmpeg version n8.1-3-gabc Copyright") == (8, 1)
    assert parse_ffmpeg_version("ffmpeg version 7.0.2-static https://") == (7, 0)
    assert parse_ffmpeg_version("ffmpeg version N-118000-g123 Copyright") == (99, 0)
    assert parse_ffmpeg_version("nope") is None


@pytest.mark.parametrize(
    "plat,ff,agent",
    [
        (("linux", "x64"), "linux64-gpl-8.1.tar.xz", "agent-browser-linux-x64"),
        (("linux", "arm64"), "linuxarm64-gpl-8.1.tar.xz", "agent-browser-linux-arm64"),
        (("windows", "x64"), "win64-gpl-8.1.zip", "agent-browser-win32-x64.exe"),
        (("macos", "arm64"), None, "agent-browser-darwin-arm64"),
    ],
)
def test_download_assets(monkeypatch, plat, ff, agent):
    monkeypatch.setattr(bootstrap, "platform_arch", lambda: plat)
    url = bootstrap.ffmpeg_asset()
    assert (url is None) if ff is None else url.endswith(ff)
    url, sha = bootstrap.agent_browser_asset()
    assert url.endswith("/v0.43.0/" + agent) and len(sha) == 64


@pytest.mark.parametrize(
    "plat,want",
    [
        (("linux", "x64"), "DBX_0.6.72_x64-browser-static.tar.gz"),
        (("linux", "arm64"), "DBX_0.6.72_arm64-browser-static.tar.gz"),
        (("windows", "x64"), "dbx-web_0.6.72_x86_64-browser-static.zip"),
        (("windows", "arm64"), None),
        (("macos", "arm64"), None),
    ],
)
def test_dbx_asset(monkeypatch, plat, want):
    monkeypatch.setattr(bootstrap, "platform_arch", lambda: plat)
    assert bootstrap.dbx_asset("0.6.72") == want


def test_scenario_driver_key():
    base = {"name": "x", "tabs": {"app": {"url": "http://a"}}, "steps": []}
    assert not any("driver" in e for e in validate({**base, "driver": "bsk"}))
    assert any("driver" in e for e in validate({**base, "driver": "selenium"}))


def test_pinned_dbx_hashes_match_names():
    for name in bootstrap.DBX_SHA256:
        assert bootstrap.DBX_VERSION in name


def test_fetch_verified(monkeypatch, tmp_path):
    def fake_download(url, dest):
        dest.write_bytes(b"abc")
        return dest

    monkeypatch.setattr(bootstrap, "download", fake_download)
    good = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert bootstrap.fetch_verified("u", tmp_path / "a", good).read_bytes() == b"abc"
    with pytest.raises(bootstrap.VerifyError, match="mismatch"):
        bootstrap.fetch_verified("u", tmp_path / "b", "0" * 64)
    assert not (tmp_path / "b").exists()
    monkeypatch.delenv("TIRAI_ALLOW_UNVERIFIED", raising=False)
    with pytest.raises(bootstrap.VerifyError, match="no SHA-256"):
        bootstrap.fetch_verified("u", tmp_path / "c", None)
    monkeypatch.setenv("TIRAI_ALLOW_UNVERIFIED", "1")
    assert bootstrap.fetch_verified("u", tmp_path / "c", None).exists()


def test_agent_browser_version_override_uses_release_digest(monkeypatch):
    monkeypatch.setattr(bootstrap, "platform_arch", lambda: ("linux", "x64"))
    monkeypatch.setenv("TIRAI_AGENT_BROWSER_VERSION", "9.9.9")
    monkeypatch.setattr(bootstrap, "release_digest", lambda repo, tag, name: f"{tag}:{name}")
    url, sha = bootstrap.agent_browser_asset()
    assert "/v9.9.9/agent-browser-linux-x64" in url and sha() == "v9.9.9:agent-browser-linux-x64"
