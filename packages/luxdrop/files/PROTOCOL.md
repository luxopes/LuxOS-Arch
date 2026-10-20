# LuxDrop protocol, version 1

LuxDrop sends files and folders between two devices on the same local network. Every
connection is end-to-end encrypted and authenticated. This document has enough detail to
write a compatible client, for example for Android in Kotlin or Java. You need only the
standard library: `SSLSocket`, `KeyPairGenerator` (EC P-256), `Signature`
(`SHA256withECDSA`), `MessageDigest` (SHA-256), `NsdManager` and a JSON parser.

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.
Byte strings are written in hex. `||` means concatenation.

## 1. Overview

```
 sender (TLS client)                                receiver (TLS server, port 47923)
 ───────────────────                                ─────────────────────────────────
 mDNS browse _luxdrop._tcp  ─────────────────────▶  mDNS announce (TXT v, id, name)
 TCP connect, TLS 1.3 (ALPN "luxdrop/1")  ◀──────▶  self-signed certificate (P-256)
 check pinned key fingerprint (if pinned)
 hello {cert, commit=SHA256(nonce_c)}     ───────▶
                                          ◀───────  hello {nonce_s}
 auth {nonce_c, sig}                      ───────▶  verify commitment and signature
                                          ◀───────  auth_ok {trusted}      (or error)
 offer {files, dirs}                      ───────▶  user accepts and compares the code
 [the sender's user compares the code]    ◀───────  accept {resume} / reject
 file {index, offset} + DATA frames …     ───────▶  write to a temp file, SHA-256
 end                                      ───────▶  verify every SHA-256, move into place
                                          ◀───────  result {ok, saved}
```

## 2. Identity

* Every device has one long-term identity key: **ECDSA on curve P-256 (secp256r1)**.
  The key is generated on first run. The device also makes a self-signed X.509
  certificate for it: CN = `LuxDrop <id>`, signature SHA-256 with ECDSA, a validity of
  100 years, and `BasicConstraints CA=false`. Peers do not check validity dates.
* **Fingerprint** `fp` = SHA-256 of the DER-encoded *SubjectPublicKeyInfo* of the public
  key (32 bytes). In Java this is
  `MessageDigest.getInstance("SHA-256").digest(cert.getPublicKey().getEncoded())`.
  Pinning uses the key fingerprint, not the whole certificate.
* **Device ID** `id` = the first 8 bytes of `fp` as lowercase hex (16 characters). It is
  only a label, used for display and mDNS. Security decisions MUST use the full `fp`.
* For display, the fingerprint is grouped as 16 blocks of 4 uppercase hex characters.
* Linux keeps these files in `~/.local/share/luxdrop/` (directory 0700, files 0600):
  `identity-key.pem` (PKCS#8, unencrypted), `identity-cert.pem`, `trusted.json` (pinned
  peers) and `history.json`. On Android, keep the key in the Android Keystore. A P-256
  key there can sign with `SHA256withECDSA` and act as the TLS server key.

## 3. Discovery (mDNS / DNS-SD)

* Service type: `_luxdrop._tcp`. Domain: `local`. Port: the TCP port of the receiver,
  **47923** by default.
* Instance name: `<device name> (<first 6 characters of id>)`, at most 63 bytes.
* TXT records:
  * `v=1`: protocol version.
  * `id=<16 hex>`: device ID.
  * `name=<device name>`: UTF-8, at most 63 characters.
* A device announces itself only while it is willing to receive, that is when its mode
  is not `off`.
* Ignore records whose `v` is unknown or whose `id` is not 16 hex characters. Collapse
  records that share an `id` into one device, and prefer IPv4.
  An IPv6 link-local address needs a scope (`%iface`).
* mDNS data is **not trusted**. It only says where to connect. Identity comes from
  TLS (section 4) together with pinning or the SAS (section 6).
* Android: use `NsdManager.discoverServices("_luxdrop._tcp", PROTOCOL_DNS_SD, …)`, then
  `resolveService`. The TXT values are in `NsdServiceInfo.getAttributes()`. To announce,
  use `registerService` with the same TXT values.
* You can also connect by hand to `IP:port`, without mDNS.

## 4. Transport: TLS 1.3

* TCP, then **TLS 1.3 only**. Older versions MUST be refused. There is no plaintext
  mode and no fallback.
* ALPN: the client offers `luxdrop/1` and the server selects it. If ALPN is negotiated
  but differs from `luxdrop/1`, abort. An implementation without ALPN MAY skip it, and
  the version is still checked in `hello`.
* **Server (receiver)** presents its self-signed identity certificate. It does **not**
  request a TLS client certificate. The client proves its identity inside the tunnel
  (section 5).
* **Client (sender)**:
  * MUST NOT check the certificate chain or the hostname. The certificate is
    self-signed. Use a custom `X509TrustManager` that accepts the chain, then check the
    key fingerprint yourself.
  * After the handshake, compute `fp_s` from the peer certificate
    (`session.getPeerCertificates()[0]`). The key MUST be EC P-256.
  * **Pinning:** if the user picked a device that is already trusted (from mDNS
    `id` or the trusted list), the client knows that device's pinned `fp`. If
    `fp_s != pinned fp`, the client MUST close the connection at once, send nothing,
    and report `key_mismatch` ("someone may be impersonating the device"). It MUST NOT
    fall back to SAS pairing. To pair again, the user first removes the device from
    the trusted list.
  * The TLS 1.3 `CertificateVerify` message proves that the server holds the private
    key of the certificate. Every TLS stack checks it, whatever trust manager you use.
* The application uses no session resumption or 0-RTT.

## 5. Framing

All application data inside TLS is a sequence of frames:

```
+--------+----------------------+-----------------+
| type   | length (uint32, BE)  | payload         |
| 1 byte | 4 bytes              | length bytes    |
+--------+----------------------+-----------------+
```

| type | name | payload | maximum length |
|------|------|---------|----------------|
| `0x4A` (`'J'`) | JSON | UTF-8 JSON object with a string field `"type"` | 16 MiB |
| `0x44` (`'D'`) | DATA | raw file bytes | 1 MiB (senders use 256 KiB) |

* Any other frame type, or a length over the limit, is `protocol_error`. The receiver
  rejects it before reading the payload.
* JSON MUST be an object. Unknown fields MUST be ignored. Integers are file sizes and
  offsets: use 64-bit (`long`), at most 2^53.
* Byte values in JSON (`nonce`, `commit`, `sha256`) are lowercase hex, 64 characters.
  `cert` and `sig` are standard base64 with padding.

Test vectors:

```
JSON {"type":"end"}  -> 4a0000000e7b2274797065223a22656e64227d
DATA "abc"           -> 4400000003616263
```

### Message types (JSON `type`)

| type | direction | fields |
|------|-----------|--------|
| `hello` | C→S | `proto`=1, `name`, `id`, `cert` (base64 DER of the client certificate), `commit` (hex, SHA-256(nonce_c)) |
| `hello` | S→C | `proto`=1, `name`, `id`, `nonce` (hex, 32 random bytes = nonce_s) |
| `auth` | C→S | `nonce` (hex nonce_c), `sig` (base64 DER ECDSA signature) |
| `auth_ok` | S→C | `trusted` (bool: whether the receiver has already pinned the client) |
| `offer` | C→S | `transfer_id` (hex), `files` [ {`path`, `size`, `sha256`, `exec`} ], `dirs` [path], `total` |
| `accept` | S→C | `resume` [ {`index`, `offset`} ] (only entries with offset > 0) |
| `reject` | S→C | `code`, `message` |
| `file` | C→S | `index`, `offset`; then exactly `size - offset` bytes in DATA frames |
| `end` | C→S | – |
| `result` | S→C | `ok` (bool), `saved` [top-level names as saved] or `code`, `failed` [index] |
| `cancel` | C→S | `reason` |
| `error` | both | `code`, `message`. After it the sender of `error` closes the connection |

## 6. Authentication and the verification code (SAS)

### 6.1 Client authentication

1. The client makes a random `nonce_c` (32 bytes) and sends `hello` with its
   certificate and `commit = SHA-256(nonce_c)`.
2. The server reads the client certificate and computes `fp_c` (the key MUST be P-256).
   It replies with `hello` and a fresh random `nonce_s` (32 bytes).
3. The client signs
   `M = "LUXDROP-AUTH-v1" || fp_s || fp_c || nonce_s || nonce_c` (15 + 4×32 = 143 bytes)
   with its identity key, using ECDSA P-256 with SHA-256 and a DER-encoded signature
   (Java `Signature.getInstance("SHA256withECDSA")`). It sends `auth {nonce=nonce_c, sig}`.
4. The server checks `SHA-256(nonce_c) == commit` in constant time, then checks the
   signature against the public key from the client certificate. If either check
   fails, it replies `error auth_failed` and closes.

The signature covers the server's key fingerprint and its fresh nonce. It cannot be
replayed, and it cannot be relayed to another receiver. Only the holder of the client
private key can produce it, so a stolen certificate alone is useless.

### 6.2 Short authentication string

Both sides compute:

```
h   = SHA-256("LUXDROP-SAS-v1" || fp_c || fp_s || nonce_c || nonce_s)
SAS = uint64_big_endian(h[0..8]) mod 1 000 000, zero-padded to 6 digits
```

The code is shown as `123 456` (3 + 3 digits).

The commitment order is what makes 6 digits enough. The client commits to `nonce_c`
before it sees `nonce_s`, and the server sends `nonce_s` before `nonce_c` is revealed.
So neither side, and no man in the middle who runs two separate sessions, can steer
the code. A MITM matches both codes with probability 10⁻⁶ per attempt, and every
attempt needs a user to accept. Implementations MUST keep this order:
`commit` → `nonce_s` → `nonce_c`.

### 6.3 When the code must be checked

* **Receiver:** if `fp_c` is not pinned, the receiver MUST show the SAS in its accept
  dialog and require an explicit **Accept**. The text says to accept only if the
  sender shows the same code. A "Trust this device" option, on by default, pins `fp_c`
  after acceptance. If `fp_c` is not pinned but the sender's name equals the name of a
  trusted device, the dialog MUST show a warning.
* **Sender:** if `fp_s` is not pinned, the sender MUST show the same code and ask
  "Does the receiver show the same code?". File data is sent only after its user
  confirms, *and* after the receiver accepts. If confirmed with "remember", `fp_s` is
  pinned with the receiver's name and address.
* If both sides have pinned each other, no code is shown. The receiver MAY accept
  automatically; this is a setting, on by default.

### 6.4 Test vectors

```
fp_c    = 000102…1f   (bytes 0x00..0x1f)
fp_s    = 202122…3f   (bytes 0x20..0x3f)
nonce_c = 404142…5f   (bytes 0x40..0x5f)
nonce_s = 606162…7f   (bytes 0x60..0x7f)

commit = SHA-256(nonce_c)
       = ca2a4fe727faaecf16ecd130a86e0885c5540c05375340445071c0657555fd42
h      = SHA-256("LUXDROP-SAS-v1" || bytes 0x00..0x7f)
       = b4ce752405cc515c9fc75e547d6fc0990047150aa573f1a570e26efdf90399b9
uint64(b4ce752405cc515c) mod 1e6 = 972316   ->  SAS "972 316"
SHA-256(M) for M = "LUXDROP-AUTH-v1" || fp_s || fp_c || nonce_s || nonce_c
       = fd7b03b3fe7cd8c0b3bfe91aa59b45d417def06238c32519240127c3959d2987

fp_c = 00×32, fp_s = ff×32, nonce_c = 11×32, nonce_s = 22×32  ->  SAS "757504"
```

`"LUXDROP-SAS-v1"` is ASCII, 14 bytes: `4c555844524f502d5341532d7631`.

## 7. Who may send (receiver policy)

The receiver checks its policy after successful authentication:

| mode | trusted (pinned) sender | unknown sender |
|------|-------------------------|----------------|
| `off` | `error receiving_off` | `error receiving_off` |
| `trusted` (default) | allowed; auto-accepted or asked | `error not_trusted`, without asking the user |
| `everyone` (10 minutes, then back to `trusted`) | allowed | the user must Accept after comparing the SAS |

Other rules:

* At most 3 requests may wait for a decision at once; more get `busy`. At most 8
  connections are open at once. An offer whose temporary files (section 8.2) are
  already being received over another connection also gets `busy`.
* A request expires after 120 s and is rejected with `timeout`.
* While the receiver waits for the user, the sender may give up. It either sends
  `cancel` or closes the connection. The receiver MUST then close the dialog and
  treat the request as cancelled.

## 8. Transfer

### 8.1 Offer

* `files[i].path` is a relative path that uses `/` as separator and is in Unicode NFC.
  The receiver MUST reject the whole offer with `invalid_offer` if any path:
  * is empty, starts with `/` or `~`, or contains `\`, NUL, a control character
    (< 0x20, 0x7F–0x9F), a bidirectional control character (U+061C, U+200E, U+200F,
    U+202A–U+202E, U+2066–U+2069) or invalid UTF-8;
  * has an empty component, `.` or `..`;
  * has a component over 255 bytes, is over 4096 bytes in total, or has more than 64
    components;
  * is a duplicate, is both a file and a directory, or lies under a path that is a
    file.

  An offer is also rejected if `size` is not an integer from 0 to 2^53, if `sha256` is
  not 64 hex characters, if there are more than 100 000 entries, or if both lists are
  empty.
* `dirs` lists every directory, including empty ones.
* The sender skips symbolic links, devices, FIFOs and sockets inside folders and never
  follows symlinks there. A top-level item the user picked explicitly may be a symlink
  to a regular file or directory. The receiver never creates links or special files.
* `exec`: true sets the file mode to 0755; otherwise 0644.

### 8.2 Accept and resume

* The receiver checks free space: `free - (total - already received)` must stay at or
  above 256 MiB, otherwise `reject no_space`.
* Partial data is stored in `<download folder>/.luxdrop-partial/` (0700, opened with
  `O_NOFOLLOW`). Each file is named
  `hex(SHA-256(fp_c || 0x00 || path || 0x00 || sha256 || 0x00 || decimal(size)))[0..40] + ".part"`.
  A part therefore matches only the same sender, path, content and size.
* `accept.resume` gives, for each file with an existing part, its size as `offset`. A
  file whose offset equals its size has already arrived and is not sent again.

### 8.3 Data

* The sender sends files in increasing `index` order. Each file is a `file
  {index, offset}` message followed by exactly `size - offset` bytes in DATA frames.
  Files where `offset == size` are skipped, and empty files need no message.
* The receiver opens the part with `O_NOFOLLOW`, truncates it to `offset`, hashes the
  existing prefix and then appends.
* Between frames the sender MAY send `cancel`. The receiver keeps the parts, so the
  transfer can resume later. The receiver cancels by closing the connection.
* Then the sender sends `end`.

### 8.4 Verification and final placement

* The receiver checks SHA-256 and size for **every** file. If any file fails, nothing
  is placed. The receiver deletes the failing parts and keeps the good ones for a
  retry. It replies `result {ok:false, code:"hash_mismatch", failed:[…]}`.
* If all files are good, the receiver places each top-level entry under a free name:
  `name`, `name (1)`, `name (2)` and so on. Existing files are never overwritten.
  Directories are created with `mkdirat` and opened with
  `O_DIRECTORY|O_NOFOLLOW`. Files are moved with `link()` and `unlink()`, which fails
  if the target exists, or with `rename()` after a check on file systems without hard
  links. Then the receiver replies `result {ok:true, saved:[…]}`.
* Received files therefore appear only after verification, all at once.

## 9. Error codes

| code | meaning |
|------|---------|
| `declined` | the receiver's user declined |
| `timeout` | no decision within 120 s |
| `busy` | too many pending requests |
| `not_trusted` | mode "Trusted devices only" and the sender is not pinned |
| `receiving_off` | the receiver is off |
| `too_large` | the offer is over the receiver's limit (reserved) |
| `no_space` | not enough disk space |
| `invalid_offer` | unsafe path, duplicate, wrong size or hash format, or too many files |
| `auth_failed` | bad certificate, commitment or signature |
| `proto_version` | unsupported protocol version or ALPN |
| `protocol_error` | malformed frame, unexpected message, more data than announced |
| `hash_mismatch` | SHA-256 or size check failed |
| `cancelled` | cancelled by the sender or the receiver |
| `internal` | unexpected error, such as an I/O error |
| `key_mismatch` | (local, sender only) the peer key differs from the pinned one |
| `sas_rejected` | (local and `cancel.reason`) the sender's user did not confirm the code |

## 10. Versioning

* `hello.proto` is an integer, and this document describes `1`. A peer that sees a
  different value MUST reply `error proto_version` and close.
* ALPN carries the version too (`luxdrop/1`), and so does the mDNS TXT `v`.
* Compatible extensions only add JSON fields or message types that the other side
  never has to answer. Unknown fields are ignored. Any incompatible change gets a new
  number (`2`, `luxdrop/2`, `LUXDROP-…-v2` labels).

## 11. Timeouts

| phase | timeout |
|-------|---------|
| TLS handshake, `hello` and `auth` | 20 s |
| Data (between frames) | 60 s |
| Waiting for the receiver's decision (sender side) | 150 s |
| `result` after `end` (the receiver verifies hashes) | max(60 s, 30 s + 1 s per 50 MB) |

## 12. Firewall

LuxDrop needs incoming **TCP 47923**, which is the default and can be changed with
`port` in `~/.config/luxdrop/settings.json`. It also needs **UDP 5353** (mDNS, Avahi).
LuxOS ships no firewall by default. If you enable one:

```
# nftables (/etc/nftables.conf, inside table inet filter, chain input)
tcp dport 47923 accept
udp dport 5353 accept

# ufw
sudo ufw allow 47923/tcp
sudo ufw allow 5353/udp

# firewalld
sudo firewall-cmd --permanent --add-port=47923/tcp --add-service=mdns && sudo firewall-cmd --reload
```

## 13. Notes for an Android implementation

* **Server:** create an `SSLContext` with a `KeyManager` holding the P-256 key and the
  self-signed certificate. Call `SSLServerSocket.setEnabledProtocols({"TLSv1.3"})`
  (API 29+) and do not request client authentication. For ALPN, use
  `SSLParameters.setApplicationProtocols({"luxdrop/1"})`.
* **Client:** use an `X509TrustManager` whose `checkServerTrusted` does not throw, then
  compute `fp_s` from `getPeerCertificates()[0]` after `startHandshake()`. Enable only
  `TLSv1.3`.
* Signature: `Signature.getInstance("SHA256withECDSA")`. Its output is DER and matches
  this protocol.
* Write received data to app storage and verify it before moving it to the Downloads
  collection (`MediaStore`). Apply the same path rules as in section 8.1.
* Reuse the vectors from section 6.4 as unit tests.
