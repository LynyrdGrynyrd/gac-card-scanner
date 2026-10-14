"""Create a self-signed HTTPS certificate so phones on the office Wi-Fi can use the camera (browsers only allow
camera/file capture features on https:// or localhost). Writes certs/cert.pem and certs/key.pem.
Phones will show a one-time "not private" warning for a self-signed certificate: tap Advanced -> Proceed.
For no warning at all, use mkcert instead (https://github.com/FiloSottile/mkcert):
    mkcert -install && mkcert -cert-file certs/cert.pem -key-file certs/key.pem localhost <this-computer-ip>"""
import datetime, ipaddress, os, socket, sys
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

def lan_ips():
    ips = {"127.0.0.1"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ips.add(s.getsockname()[0]); s.close()
    except Exception: pass
    try:
        for i in socket.gethostbyname_ex(socket.gethostname())[2]: ips.add(i)
    except Exception: pass
    return sorted(ips)

def main(out="certs"):
    os.makedirs(out, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GAC Card Scanner (local)"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Greater Akron Chamber pilot")])
    host = socket.gethostname()
    san = [x509.DNSName("localhost"), x509.DNSName(host)] + [x509.IPAddress(ipaddress.ip_address(i)) for i in lan_ips()]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825)).add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(key, hashes.SHA256()))
    with open(os.path.join(out, "key.pem"), "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    with open(os.path.join(out, "cert.pem"), "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))
    print("Created certs/cert.pem and certs/key.pem")
    print("On a phone on the same Wi-Fi, open one of:")
    for i in lan_ips():
        if i != "127.0.0.1": print(f"   https://{i}:8765")
    print("(Expect a one-time security warning for a self-signed certificate.)")
if __name__ == "__main__": main(*sys.argv[1:])
