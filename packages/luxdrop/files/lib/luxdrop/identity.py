"""LuxDrop - identita zarizeni: klic ECDSA P-256 a self-signed certifikat X.509.

Otisk (fingerprint) = SHA-256 z DER SubjectPublicKeyInfo verejneho klice
(v Jave cert.getPublicKey().getEncoded()). Pripina se otisk klice, ne certifikat.
"""
import datetime
import hashlib
import os

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from . import proto

KEY_FILE = "identity-key.pem"
CERT_FILE = "identity-cert.pem"


def data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "luxdrop")


def ensure_private_dir(path):
    """Vytvori adresar 0700 a odmitne symlink (cizi podstrceny adresar)."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    st = os.lstat(path)
    if not os.path.isdir(path) or os.path.islink(path):
        raise RuntimeError("%s is not a directory" % path)
    if st.st_uid != os.getuid():
        raise RuntimeError("%s is not owned by the current user" % path)
    if st.st_mode & 0o077:
        os.chmod(path, 0o700)


def write_private(path, data):
    """Atomicky zapis souboru s pravy 0600."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


def spki_fingerprint(public_key):
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).digest()


def cert_fingerprint(cert_der):
    """Otisk z certifikatu v DER; vyhodi ProtocolError, kdyz neni platny klic P-256."""
    try:
        cert = x509.load_der_x509_certificate(cert_der)
        key = cert.public_key()
    except Exception as e:  # noqa: BLE001 - jakakoli chyba parsovani = neplatny certifikat
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "invalid certificate: %s" % e) from None
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "certificate key must be ECDSA P-256")
    return spki_fingerprint(key), key


def verify_signature(public_key, signature, message):
    try:
        public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


class Identity:
    def __init__(self, key, cert, key_path, cert_path):
        self.key = key
        self.cert = cert
        self.key_path = key_path
        self.cert_path = cert_path
        self.cert_der = cert.public_bytes(serialization.Encoding.DER)
        self.fp = spki_fingerprint(key.public_key())
        self.id = proto.short_id(self.fp)

    def sign(self, message):
        return self.key.sign(message, ec.ECDSA(hashes.SHA256()))

    @classmethod
    def load_or_create(cls, directory=None):
        directory = directory or data_dir()
        ensure_private_dir(directory)
        key_path = os.path.join(directory, KEY_FILE)
        cert_path = os.path.join(directory, CERT_FILE)
        if os.path.exists(key_path) and os.path.exists(cert_path):
            for p in (key_path, cert_path):
                if os.stat(p).st_mode & 0o077:
                    os.chmod(p, 0o600)
            with open(key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
            with open(cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
            if spki_fingerprint(cert.public_key()) != spki_fingerprint(key.public_key()):
                raise RuntimeError("identity certificate does not match the key in %s" % directory)
            return cls(key, cert, key_path, cert_path)
        key = ec.generate_private_key(ec.SECP256R1())
        fp = spki_fingerprint(key.public_key())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LuxDrop " + proto.short_id(fp))])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=365 * 100))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        write_private(key_path, key.private_bytes(serialization.Encoding.PEM,
                                                  serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
        write_private(cert_path, cert.public_bytes(serialization.Encoding.PEM))
        return cls(key, cert, key_path, cert_path)
