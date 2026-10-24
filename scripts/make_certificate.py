"""Generate a dedicated, short-lived local CA and a server certificate. Never installs trust."""

import argparse
import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def make_certificates(address, directory):
    address = ipaddress.ip_address(address)
    if not (address.is_private or address.is_loopback):
        raise ValueError("Specificare l'IP della rete locale, non un indirizzo pubblico.")
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / name for name in ("rootCA.crt", "rootCA-key.pem", "server.pem", "server-key.pem")]
    if any(path.exists() for path in paths):
        raise ValueError(
            "Certificati già presenti: usare una nuova directory, senza sovrascrivere le chiavi."
        )
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "StereoLab Local Development CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "StereoLab")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=60))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(address),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    for path, data in [
        (paths[0], ca.public_bytes(serialization.Encoding.PEM)),
        (
            paths[1],
            ca_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
        ),
        (paths[2], cert.public_bytes(serialization.Encoding.PEM)),
        (
            paths[3],
            server_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
        ),
    ]:
        with path.open("xb") as handle:
            handle.write(data)
    return cert


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="IPv4 LAN del computer, es. 192.168.1.10")
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "certs")
    args = parser.parse_args()
    make_certificates(args.ip, args.directory)
    print(f"Creati i certificati in {args.directory.resolve()}")
    print("Installare e rendere attendibile SOLO rootCA.crt sui propri dispositivi.")
    print("Non condividere rootCA-key.pem o server-key.pem. La fiducia non viene installata automaticamente.")
