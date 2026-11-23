"""Sign the evidence manifest so a re-generated manifest.sha256 is detected.

Signature: OpenSSH `ssh-keygen -Y sign` (bundled with macOS, Linux and Windows 10+), namespace
`tirai-evidence`, written to manifest.sha256.sig. Optional RFC 3161 timestamp from a TSA
(`openssl ts`), written to manifest.sha256.tsr, proves the manifest existed at that time.
"""

import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from tirai.report import MANIFEST
from tirai.system import run_text

NAMESPACE = "tirai-evidence"
SIG = MANIFEST + ".sig"
PUB = MANIFEST + ".pub"
TSR = MANIFEST + ".tsr"
DEFAULT_TSA = "https://freetsa.org/tsr"


class SignError(RuntimeError):
    pass


def _tool(name):
    path = shutil.which(name)
    if not path:
        hint = "install OpenSSH" if name == "ssh-keygen" else "install OpenSSL (Git for Windows ships one)"
        raise SignError(f"{name} not found; {hint}")
    return path


def _pubkey_for(key):
    pub = Path(str(key) + ".pub")
    if pub.is_file():
        return pub.read_text(encoding="utf-8").strip()
    p = run_text([_tool("ssh-keygen"), "-y", "-f", str(key)], timeout=30)
    if p.returncode:
        raise SignError(f"cannot read public key of {key}: {p.stderr.strip()}")
    return p.stdout.strip()


def sign(rec_dir, key, tsa=None):
    """Sign manifest.sha256 with an SSH private key; optionally add an RFC 3161 timestamp."""
    rec_dir, key = Path(rec_dir), Path(os.path.expanduser(str(key)))
    manifest = rec_dir / MANIFEST
    if not manifest.is_file():
        raise SignError(f"{MANIFEST} not found in {rec_dir}; run `tirai compose` first")
    if not key.is_file():
        raise SignError(f"signing key not found: {key}")
    (rec_dir / SIG).unlink(missing_ok=True)
    p = run_text([_tool("ssh-keygen"), "-Y", "sign", "-q", "-f", str(key), "-n", NAMESPACE, str(manifest)], timeout=60)
    if p.returncode:
        raise SignError(f"ssh-keygen sign failed: {(p.stderr or p.stdout).strip()}")
    (rec_dir / PUB).write_text(_pubkey_for(key) + "\n", encoding="utf-8")
    out = [rec_dir / SIG, rec_dir / PUB]
    if tsa:
        out.append(timestamp(rec_dir, DEFAULT_TSA if tsa is True else tsa))
    return out


def timestamp(rec_dir, url=DEFAULT_TSA):
    rec_dir = Path(rec_dir)
    openssl = _tool("openssl")
    with tempfile.TemporaryDirectory() as tmp:
        tsq = Path(tmp) / "req.tsq"
        p = run_text(
            [openssl, "ts", "-query", "-data", str(rec_dir / MANIFEST), "-sha256", "-cert", "-out", str(tsq)],
            timeout=30,
        )
        if p.returncode:
            raise SignError(f"openssl ts -query failed: {p.stderr.strip()}")
        req = urllib.request.Request(
            url, data=tsq.read_bytes(), headers={"Content-Type": "application/timestamp-query"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - user-chosen TSA URL
                body = r.read()
        except OSError as e:
            raise SignError(f"timestamp request to {url} failed: {e}") from e
    out = rec_dir / TSR
    out.write_bytes(body)
    return out


def _fingerprint(pubkey):
    with tempfile.NamedTemporaryFile("w", suffix=".pub", delete=False) as f:
        f.write(pubkey + "\n")
    try:
        p = run_text([_tool("ssh-keygen"), "-l", "-f", f.name], timeout=30)
        return p.stdout.split()[1] if p.returncode == 0 and p.stdout else "?"
    finally:
        os.unlink(f.name)


def verify_signature(rec_dir, pubkey=None, allowed_signers=None, identity="tirai"):
    """Return (problems, notes). Trust comes from `pubkey`/`allowed_signers`; the bundled .pub only identifies."""
    rec_dir = Path(rec_dir)
    sig, manifest = rec_dir / SIG, rec_dir / MANIFEST
    if not sig.is_file():
        return (["not signed (no manifest.sha256.sig)"] if (pubkey or allowed_signers) else []), []
    notes = []
    with tempfile.TemporaryDirectory() as tmp:
        if allowed_signers:
            signers = Path(allowed_signers)
        else:
            trusted = pubkey is not None
            key = Path(os.path.expanduser(str(pubkey))) if trusted else rec_dir / PUB
            if not key.is_file():
                return [f"public key not found: {key}"], notes
            text = key.read_text(encoding="utf-8").strip()
            signers = Path(tmp) / "allowed_signers"
            signers.write_text(f'{identity} namespaces="{NAMESPACE}" {text}\n', encoding="utf-8")
            if not trusted:
                notes.append(
                    f"signature checked against the key stored in the folder ({_fingerprint(text)}); "
                    "pass --pubkey to check it against a key you trust"
                )
        with open(manifest, "rb") as data:
            p = subprocess.run(
                [
                    _tool("ssh-keygen"),
                    "-Y",
                    "verify",
                    "-f",
                    str(signers),
                    "-I",
                    identity,
                    "-n",
                    NAMESPACE,
                    "-s",
                    str(sig),
                ],
                stdin=data,
                capture_output=True,
                text=True,
                timeout=60,
            )
    if p.returncode:
        return [f"bad signature: {(p.stderr or p.stdout).strip()}"], notes
    notes.insert(0, f"signature ok ({p.stdout.strip() or identity})")
    return [], notes


def verify_timestamp(rec_dir, ca_file=None):
    rec_dir = Path(rec_dir)
    tsr = rec_dir / TSR
    if not tsr.is_file():
        return [], []
    openssl = _tool("openssl")
    info = run_text([openssl, "ts", "-reply", "-in", str(tsr), "-text"], timeout=30)
    when = next((ln.split(":", 1)[1].strip() for ln in info.stdout.splitlines() if ln.startswith("Time stamp:")), "?")
    if not ca_file:
        return [], [f"timestamp {when} (pass --tsa-ca to verify the TSA certificate chain)"]
    p = run_text(
        [openssl, "ts", "-verify", "-data", str(rec_dir / MANIFEST), "-in", str(tsr), "-CAfile", str(ca_file)],
        timeout=30,
    )
    if p.returncode or "Verification: OK" not in p.stdout:
        return [f"bad timestamp: {(p.stderr or p.stdout).strip()}"], []
    return [], [f"timestamp ok: {when}"]
