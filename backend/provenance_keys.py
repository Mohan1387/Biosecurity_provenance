"""Explicit local provisioning: python provenance_keys.py /secure/path.

Never runs at application startup. Existing directories are refused.
"""
import argparse
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def provision(directory):
    path = Path(directory).resolve()
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    registry = {"active": {}, "keys": {}}
    for component in ("logger", "profiler", "detector", "clusterer"):
        key = Ed25519PrivateKey.generate()
        key_path = path / f"{component}.pem"
        with os.fdopen(os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        kid = f"{component}-{uuid4()}"
        registry["active"][component] = kid
        registry["keys"][kid] = {"component": component, "status": "active", "public_key": base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()}
        print(f"PROVENANCE_{component.upper()}_KEY={key_path}")
    (path / "registry.json").write_text(json.dumps(registry, indent=2))
    print(f"PROVENANCE_REGISTRY={path / 'registry.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    provision(parser.parse_args().directory)
