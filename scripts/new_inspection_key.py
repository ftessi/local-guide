"""Creates the company's inspection key pair: the private key file for the security team (keep it offline, outside
any repository) and the public key to put in localagent/protocol/tessera/inspection.py as COMPANY_KEY."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat  # noqa: E402

from localagent.protocol.identity import x25519_public  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="where to write the private key (never inside a repository)")
    args = parser.parse_args(argv)
    out = Path(args.out)
    key = X25519PrivateKey.generate()
    try:
        with open(out, "xb") as fh:
            fh.write(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    except FileExistsError:
        print(f"Error: {out} already exists; not overwriting a key", file=sys.stderr)
        return 2
    print(f"Private key: {out}  (keep it offline: anyone with it can read every inspected conversation)")
    print(f"Public key, for COMPANY_KEY: {x25519_public(key)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
