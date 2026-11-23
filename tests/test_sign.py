import shutil
import subprocess

import pytest

from tirai import report, sign

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen not available")


def keypair(path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
    return path


def evidence(tmp_path):
    d = tmp_path / "rec"
    d.mkdir()
    (d / "final.mp4").write_bytes(b"video")
    (d / "report.md").write_text("ok")
    report.write_manifest(d)
    return d


def test_sign_then_verify_with_trusted_key(tmp_path):
    d, key = evidence(tmp_path), keypair(tmp_path / "k")
    sign.sign(d, key)
    problems, notes = sign.verify_signature(d, pubkey=str(key) + ".pub")
    assert problems == [] and notes[0].startswith("signature ok")


def test_regenerated_manifest_is_detected(tmp_path):
    d, key = evidence(tmp_path), keypair(tmp_path / "k")
    sign.sign(d, key)
    (d / "final.mp4").write_bytes(b"tampered")
    report.write_manifest(d)  # attacker rewrites the manifest too
    assert report.verify(d) == []
    problems, _ = sign.verify_signature(d, pubkey=str(key) + ".pub")
    assert problems and problems[0].startswith("bad signature")


def test_other_key_is_rejected_and_bundled_key_only_noted(tmp_path):
    d = evidence(tmp_path)
    sign.sign(d, keypair(tmp_path / "attacker"))
    other = keypair(tmp_path / "owner")
    assert sign.verify_signature(d, pubkey=str(other) + ".pub")[0]
    problems, notes = sign.verify_signature(d)
    assert problems == [] and any("--pubkey" in n for n in notes)


def test_unsigned_folder_fails_only_when_a_key_is_required(tmp_path):
    d = evidence(tmp_path)
    assert sign.verify_signature(d) == ([], [])
    assert sign.verify_signature(d, pubkey=str(keypair(tmp_path / "k")) + ".pub")[0]
