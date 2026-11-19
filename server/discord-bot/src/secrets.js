"use strict";
// Rozpoznani tajnych udaju v textu: klice LuxAI, tokeny Discordu, GitHubu, AWS, privatni klice, "password: ..."
// Zpravy s nimi bot neposila modelu; z hlaseni chyb je pred odeslanim e-mailem odstrani.

const PATTERN = String.raw`\blux-[A-Za-z0-9_-]{32,}|\b[MNO][A-Za-z\d_-]{23,27}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}|\bgh[pousr]_[A-Za-z0-9]{36}|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)|\b(password|passwd|heslo|token|secret|api[_ -]?key)\s*[:=]\s*\S{4,}`;

const SECRET_RE = new RegExp(PATTERN, "i");

function redact(text) {
  return String(text).replace(new RegExp(PATTERN, "gi"), "[redacted]");
}

module.exports = { SECRET_RE, redact };
