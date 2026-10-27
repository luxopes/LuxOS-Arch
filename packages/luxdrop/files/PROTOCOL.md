# LuxDrop protocol, version 1

LuxDrop sends files and folders between two devices on the same local network. Every
connection is end-to-end encrypted and authenticated. LuxDrop speaks two protocols:

* **Part A – the LuxDrop protocol** (sections 1–13) between LuxOS computers: TLS 1.3,
  pinned keys and a 6-digit verification code (SAS). This is the most secure option and
  LuxOS always prefers it when both sides are LuxOS.
* **Part B – LocalSend protocol v2** (section 14) for the LocalSend app on Android,
  phones and tablets, Windows, other Linux systems and so on. See section 15 for the
  security model of both.

This document has enough detail to
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

### 4.1 Cipher suites

* Every implementation MUST support `TLS_AES_256_GCM_SHA384`. The other TLS 1.3 suites
  (`TLS_CHACHA20_POLY1305_SHA256`, `TLS_AES_128_GCM_SHA256`) MAY be enabled.
* **Server (receiver):** chooses by its own order (OpenSSL `SSL_OP_CIPHER_SERVER_PREFERENCE`)
  with `TLS_AES_256_GCM_SHA384` first, so it picks AES-256-GCM whenever the client offers it,
  whatever the client's order. LuxOS uses the order AES-256-GCM, ChaCha20-Poly1305,
  AES-128-GCM.
* **Client (sender):** offers `TLS_AES_256_GCM_SHA384` first. LuxOS on Python 3.15 and newer
  offers only this suite, because a receiver on Android without AES hardware (BoringSSL)
  prefers ChaCha20 as a server.
* A peer MAY refuse to continue after the handshake if a different suite was negotiated. The
  LuxOS Companion app for Android does this: it accepts only `TLS_AES_256_GCM_SHA384`.
  Android cannot disable single TLS 1.3 suites, so the app checks the result instead.

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
| `trusted` | allowed; auto-accepted ("Quick save") or asked | `error not_trusted`, without asking the user |
| `everyone` (default since LuxDrop 1.0.0-2) | allowed | the user must Accept after comparing the SAS |

`everyone` can also be limited in time (`luxdrop mode everyone --minutes 10`, at most 10
minutes, then back to `trusted`). Without a limit it stays on, like LocalSend's "receive"
switch – every transfer from an unknown device still needs an explicit Accept.
The same policy applies to LocalSend senders (section 14).

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

LuxDrop needs incoming **TCP 47923** (LuxDrop, setting `port`), **TCP and UDP 53317**
(LocalSend HTTPS server and multicast discovery, setting `localsend_port`) and
**UDP 5353** (mDNS, Avahi). LuxOS ships no firewall by default, so nothing has to be done.
If you enable one, open the ports **only for private networks** (home/work), never on
public Wi-Fi. The package ships a firewalld service and a ufw application profile:

```
# firewalld: only in the home zone (assign your home Wi-Fi/LAN connection to it)
sudo firewall-cmd --permanent --zone=home --add-service=luxdrop && sudo firewall-cmd --reload

# ufw: only from private address ranges
sudo ufw allow from 192.168.0.0/16 to any app LuxDrop
sudo ufw allow from 10.0.0.0/8 to any app LuxDrop

# nftables (/etc/nftables.conf, inside table inet filter, chain input)
ip saddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 } tcp dport { 47923, 53317 } accept
ip saddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 } udp dport { 53317, 5353 } accept
```

The multicast group 224.0.0.167 is link-local (never routed), so discovery only works in
the local network segment. Without multicast (for example on guest Wi-Fi with client
isolation), use "Scan the local network" or "Connect by address".

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
* As a server, Android (BoringSSL) cannot be told which TLS 1.3 suite to prefer. With AES
  hardware it follows the client's order; without it, it prefers ChaCha20 (section 4.1).
* The LuxOS Companion app (from version 0.3.0) implements this part: it sends one file to a
  computer whose full key fingerprint the user enters, and it receives up to 16 files
  (no folders, at most 1 GiB) while its 10-minute receive mode is on. It announces itself
  over mDNS only while receiving.

## 14. Part B – LocalSend protocol v2

LuxDrop implements the receiving and the sending side of the
[LocalSend protocol v2](https://github.com/localsend/protocol) (v2.2, compatible with
apps that speak 2.0/2.1). It was tested against the official Rust implementation
(`localsend` crate, the core of the LocalSend app): transfers in both directions,
text messages, PIN, decline and multicast discovery.

### 14.1 Identity and TLS

* LuxDrop uses its own identity (section 2) also for LocalSend: the same self-signed
  P-256 certificate. The **LocalSend fingerprint** is SHA-256 of the whole certificate in
  DER, as 64 uppercase hex characters (official test vector: the certificate in
  `tests/test_localsend_unit.py` → `4BADDE53…52FA`).
* HTTPS only, on **TCP 53317**, TLS 1.2 or 1.3, ALPN `http/1.1`. Plain HTTP LocalSend
  devices (encryption turned off in LocalSend) are shown as "Unencrypted" and nothing is
  sent to or accepted from them.
* **Server:** asks for a client certificate (mTLS) but accepts any one; the sender's
  identity is the fingerprint of the certificate it proved with the TLS handshake.
  Current LocalSend apps (1.18+) always present one. Older apps send none – such a
  sender is shown as "identity not verified" and can never be trusted or quick-saved.
* **Client:** presents the LuxDrop certificate (current LocalSend requires mTLS) and
  checks the receiver's certificate fingerprint right after the handshake, before any
  data is sent. The expected value comes from discovery; for a trusted device the pinned
  key (SHA-256 of SPKI) must also match. A mismatch aborts with `key_mismatch`.

### 14.2 Discovery

* Multicast UDP **224.0.0.167:53317**, JSON:
  `{"alias","version":"2.2","deviceModel":"LuxOS","deviceType":"desktop","fingerprint",
  "port","protocol":"https","download":false,"announce":true,"announcement":true}`.
  `announcement` is the v1 name of `announce`. LuxDrop adds
  `"luxdrop":{"v":1,"id":"<16 hex>","port":47923}`; other apps ignore unknown fields.
* LuxDrop announces 3× (after 0.1 s, 0.5 s, 2 s) at start and on "Refresh", on every
  IPv4 interface.
* On a foreign announcement LuxDrop answers with `POST /api/localsend/v2/register` to
  the announcing device (pinned to the announced fingerprint). If that fails it answers
  with a multicast message with `announce:false` (v2.0/2.1 fallback). While receiving is
  off, it only remembers the device and does not register.
* `POST /register` to LuxDrop is accepted only when the claimed fingerprint equals the
  client certificate's fingerprint (otherwise ignored, like LocalSend). Without a client
  certificate LuxDrop verifies the device by its own `/register` request back to the
  sender's address.
* HTTP fallback scan of the local `/24` subnets – **only on request** ("Scan the local
  network", `luxdrop devices --scan`), only private (RFC 1918) networks, max. 48
  parallel requests with a 1 s timeout.
* A LocalSend device that carries the `luxdrop` field is a LuxOS computer: the UI shows
  it once and sends with the LuxDrop protocol (Part A, SAS + pinning).
* `GET /api/localsend/v2/info` and `/api/localsend/v1/info` (old apps probe v1) answer
  with the device info.

### 14.3 Receiving (`POST /prepare-upload`, `/upload`, `/cancel`)

1. `prepare-upload?pin=…` – with a PIN set, untrusted senders must give it: `401` when
   missing or wrong; after 3 wrong attempts from one IP `429` for 5 minutes.
2. Policy (section 7): `off` → `403`; `trusted` and an untrusted sender → `403` without
   asking.
3. The body is validated (max. 8 MiB JSON, 100 000 files, sizes 0…2^53, optional SHA-256
   as 64 hex). File names may contain `/` (folders). They are normalized to NFC, `\` is
   treated as `/`, control and bidi characters become `_`, empty and `.` components are
   dropped, components over 255 bytes are shortened; **absolute paths, `~`, drive
   letters and `..` reject the whole request with `400`**. Collisions (also case and
   NFC/NFD) get " (2)". A file name that is also a folder of another file → `400`.
4. Only one session at a time (`409` while another one waits or runs). Disk space:
   `free − total` must stay ≥ 256 MiB, otherwise `507`.
5. A single `text/plain` file with `preview` is a **text message**: it is shown
   (with a Copy button) and the answer is `204` – nothing is saved.
6. Otherwise the user must Accept (dialog with device name and type, file list, total
   size) – unless the sender's key is trusted and "Quick save" is on. Decline/timeout
   (120 s) → `403`. If the sender closes the connection or calls `/cancel` meanwhile,
   the dialog closes.
7. Accept → `200 {"sessionId": uuid4, "files": {fileId: token}}` (tokens: 192 random
   bits, compared in constant time).
8. `upload?sessionId&fileId&token` must come from the same IP, with the right token, once
   per file (up to 3 attempts after a broken connection). The body (Content-Length or
   chunked) is written to `<download folder>/.luxdrop-partial/ls-<random>.part`
   (`O_EXCL|O_NOFOLLOW`, 0600). More data than announced → `400`; size or SHA-256
   mismatch → `400`/`422` and the part is deleted. A verified file is moved into place
   with `link()`/`unlink()` (never overwrites; `name (1).ext` …), folders are created
   with `mkdirat` + `O_NOFOLLOW`. The file mode is 0644, `metadata.modified` sets mtime.
9. `/cancel` from the sender's IP ends the session; the receiver's Cancel ends it and
   sends `POST /cancel?sessionId=…` to the sender's server.

Received files go to `~/Downloads/LuxDrop` (XDG download folder + `LuxDrop`), or the
folder chosen in Settings.

### 14.4 Sending

`prepare-upload` with all files (relative paths with `/` for folders, SHA-256, MIME type,
mtime) → on `401` the user is asked for the receiver's PIN → `204` = nothing to send
(message) / `403` declined / `409` busy / `429` too many PIN attempts → for every
accepted file `upload` with `Content-Length`. Cancel closes the connection and sends
`/cancel`. Text is sent as one `text/plain` file with `preview` (shown as a message by
LocalSend). LocalSend cannot transfer empty folders; they are skipped.

## 15. Security model

| | LuxOS ↔ LuxOS (Part A) | LuxOS ↔ LocalSend (Part B) |
|-|-|-|
| Encryption | TLS 1.3 only | TLS 1.2/1.3 (HTTPS); plain-HTTP peers refused |
| Receiver identity | pinned key; first contact: 6-digit SAS on both screens | certificate fingerprint from discovery, checked before sending; pinned key for trusted devices |
| Sender identity | ECDSA signature inside TLS + SAS | client certificate (mTLS) of current LocalSend apps; old apps: unverified |
| Man-in-the-middle on first contact | detected by the SAS (10⁻⁶ chance per attempt) | **not detectable** – LocalSend has no verification code (trust on first use) |
| Incoming transfer | always needs Accept, unless pinned + Quick save | always needs Accept, unless pinned (via mTLS) + Quick save; optional PIN |
| Integrity | SHA-256 of every file | TLS + SHA-256 when the sender provides it (LuxDrop always does) |

Why both protocols: LocalSend's model protects against passive eavesdropping and against
a device that changes its key later, but on first contact an active attacker in the same
network could pose as the other device, because there is no code to compare. LuxDrop's
own protocol closes this gap with the SAS, so it stays the default between LuxOS
computers; LocalSend is used only for devices that cannot speak it. Trusting a LocalSend
device ("Trust this device" in the accept dialog, off by default) pins the key of its
client certificate; afterwards a different key with the same name is not trusted and the
dialog warns about it.

## 16. Part C – shared folders ("Connect to Computer")

A LuxOS computer can let another LuxOS computer browse chosen folders, so that Files shows
local and remote folders side by side and drag & drop copies between them. Instead of a new
file protocol, LuxDrop tunnels **SFTP** (the OpenSSH SFTP protocol, version 3) through a TLS
connection authenticated exactly like Part A. No `sshd` and no system configuration are needed.

```
 client (Alice)                                   sharing computer (Bob, port 47924)
 mDNS browse _luxdrop-files._tcp  ─────────────▶  announced only while sharing is on
 TLS 1.3, ALPN "luxdrop-files/1"  ◀───────────▶  same identity certificate as Part A
 hello / auth (section 6.1)        ◀───────────▶  auth_ok
 open {write}                     ─────────────▶  ask the owner (unless "Always" was given)
 [Alice compares the code]                        [Bob compares the code, Allow once / Always / Deny]
                                  ◀─────────────  opened {write, shares} | reject {code}
 start                            ─────────────▶  spawn sftp-server in a sandbox
 raw SFTP stream                  ◀───────────▶  raw SFTP stream (no more frames)
```

* Service type `_luxdrop-files._tcp`, TXT as in section 3, default port **47924**.
  ALPN `luxdrop-files/1`; a Part A client cannot talk to it by mistake.
* Messages before `start` use the framing of section 5. `open.write` (bool) asks for
  write access. `opened.write` is the access actually granted, `opened.shares` lists the
  top-level folder names. `reject.code` is `declined`, `timeout`, `busy` or `sharing_off`.
* The code (SAS, section 6.2) is computed with the connecting computer as the client.
  It is shown on both screens unless the other side's key is already pinned (trusted
  devices of Part A).
* After `start` both sides relay raw bytes between TLS and the SFTP endpoints.

### 16.1 Server side

* Sharing is **off** by default. `luxdrop share on` (or Settings › Share folders) enables
  the user service `luxdrop-files.service` and, the first time, shares only the **Public**
  folder (`XDG_PUBLICSHARE_DIR`, created if missing).
* Only folders inside the home folder (not hidden ones, not inside hidden ones) or on
  external drives (`/run/media`, `/media`, `/mnt`) can be shared. Sharing the whole home
  folder needs an extra confirmation, and its hidden entries (`.ssh`, keyring, settings,
  the LuxDrop key) are masked: empty read-only directories or `/dev/null`. The top level of a
  shared home folder stays read-only even with write access; only its non-hidden
  subfolders are bound writable.
* Every connection from a device without an "Always" grant asks the owner: **Allow once**
  (this connection only), **Always allow** (stored in `~/.local/share/luxdrop/file-access.json`)
  or **Deny** (the same device is then refused for 5 minutes without asking). One request
  at a time, 120 s timeout, at most 8 connections.
* Access is **read-only** unless the client asked for write access and the owner ticked
  "Also allow changes" (unchecked by default; notification buttons never grant write).
* For each connection `sftp-server` (OpenSSH) runs inside **bubblewrap**: new user, PID,
  network, IPC and mount namespaces, no capabilities, empty environment, `/usr` read-only,
  a minimal `/etc/passwd`, and the shared folders bound under `/share/<name>`. Nothing
  else of the disk exists in the sandbox, so `..`, absolute paths and symlinks cannot
  reach other files. `/` and `/share` are read-only; read-only access binds the folders
  read-only **and** runs `sftp-server -R`. `symlink` and `hardlink` requests are refused.
* Turning sharing off, removing a device or taking away its write access closes its open
  connections within a few seconds.

### 16.2 Client side

* `luxdrop connect` (or the "Connect to Computer" app) connects, shows the code, waits for
  the owner and runs `sshfs -o passive` (FUSE) on a socket pair relayed to the TLS
  connection. The mount point is `$XDG_RUNTIME_DIR/luxdrop-files/<name>` with options
  `follow_symlinks,noexec,nosuid,nodev` (and `ro` when read-only). A bookmark appears in the
  Files sidebar; a Files window opens split in two (remote | home).
* TCP keepalive and `TCP_USER_TIMEOUT` detect a dead connection within about 45 s; the
  mount, the bookmark and the entry in `connections.json` are then removed, so a vanished
  computer does not freeze Files or terminals.
* A pinned (trusted) computer that presents a different key is refused with
  `key_mismatch`, as in Part A.
