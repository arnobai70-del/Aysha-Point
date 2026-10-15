"""Create the owner's stable Android release signing key (PKCS#12), without Java or Android Studio.

Android only installs an update over an existing app when both are signed with the same key; then
the app's data (signal inbox, journal) is kept. CI builds without this key use a throwaway debug
key, so every update needs an uninstall. Run once, keep the files offline, never commit them.
"""

from __future__ import annotations

import base64
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path


def make_key(out_dir: Path, alias: str = "ayesha", years: int = 30, common_name: str = "AYESHA FX owner") -> dict:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    out_dir.mkdir(parents=True, exist_ok=True)
    ks = out_dir / "ayesha-release.p12"
    if ks.exists():
        raise FileExistsError(f"{ks} already exists; a new key would stop updates from installing. Keep the old one.")
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(32))
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365 * years)).sign(key, hashes.SHA256()))
    enc = (serialization.PrivateFormat.PKCS12.encryption_builder().kdf_rounds(50000)
           .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC).hmac_hash(hashes.SHA256())
           .build(password.encode()))
    ks.write_bytes(pkcs12.serialize_key_and_certificates(alias.encode(), key, cert, None, enc))
    fp = cert.fingerprint(hashes.SHA256()).hex()
    b64 = base64.b64encode(ks.read_bytes()).decode()
    secrets_file = out_dir / "github-secrets-DELETE-AFTER-USE.txt"
    secrets_file.write_text(
        "Add these four repository secrets on GitHub (Settings -> Secrets and variables -> Actions),\n"
        "then DELETE this file. Keep ayesha-release.p12 and the password in a safe offline place.\n\n"
        f"AYESHA_KEYSTORE_BASE64\n{b64}\n\nAYESHA_KEYSTORE_PASSWORD\n{password}\n\n"
        f"AYESHA_KEY_ALIAS\n{alias}\n\nAYESHA_KEY_PASSWORD\n{password}\n\n"
        f"Certificate SHA-256 (also shown in every release note once configured):\n{fp}\n", encoding="utf-8")
    return {"keystore": str(ks), "secrets_file": str(secrets_file), "sha256": fp, "alias": alias}
