# Wi-Fi QR codes

LuxOS can show the current Wi-Fi network as a QR code, so a phone joins it by scanning, and it can
join a network by scanning a Wi-Fi QR code with the computer's camera. Both are in `luxos-desktop`.

## Share your Wi-Fi

- Control Center › **Share Wi-Fi with QR Code…** (under the tiles, shown while you are connected to
  Wi-Fi), or the app **Wi-Fi QR Code** in Launchpad / Search, or run `luxos-wifi-qr`.
- The window shows the QR code, the network name and the password (hidden, the eye icon shows it).
  The copy button puts the QR code image into the clipboard (paste it into a document or chat).
- The password is read from NetworkManager (`nmcli --show-secrets`). For networks saved for the
  whole computer NetworkManager may refuse to give it out; then the window says so and **Show
  Password…** asks for the administrator password (`pkexec nmcli`). Cancelling keeps the window open.
- Company or school networks (802.1X, `wpa-eap`) cannot be shared with a QR code; the window says
  so.
- Not connected to Wi-Fi: "Not connected to Wi-Fi" and the scan button.

The code uses the common format understood by Android and iPhone cameras:
`WIFI:T:WPA;S:<name>;P:<password>;H:true;;` with `T` = `WPA` (WPA/WPA2), `SAE` (WPA3), `WEP` or
`nopass`, and `\`, `;`, `,`, `:` and `"` escaped with a backslash. Names with non-ASCII letters are
encoded as UTF-8 (ECI 26).

## Join a network by scanning

- Control Center › **Join Wi-Fi with QR Code…** (shown when Wi-Fi is on but not connected),
  **Join a Network with a QR Code…** in the Wi-Fi QR Code window, the Launchpad action of the same
  name, or `luxos-wifi-qr --scan` (which runs `luxos-camera --scan-wifi`).
- The Camera opens in scan mode ("Join Wi-Fi with QR Code"): hold the code in front of the camera.
  Mirrored and inverted codes work. A QR code that is not a Wi-Fi network shows "This QR code is not
  a Wi-Fi network." for a moment.
- After a code is found, LuxOS asks "Join the Wi-Fi network “name”?". **Join** runs
  `nmcli device wifi connect <name> password <password>` (plus `hidden yes` for hidden networks);
  the result is "Connected to “name”" or the error from NetworkManager with **Try Again**.
- Camera errors (no camera, camera used by another app, no permission) are the same as in the
  Camera app, see [apps.md](apps.md#camera).

## Under the hood

- QR codes are drawn and read by the `zxing-cpp` library (`libZXing`, C API through Python ctypes),
  a small dependency of `luxos-desktop`; module `/usr/lib/luxos/python/luxos_qr.py`.
- If the library is missing the window shows "QR codes are not available" and how to install it
  (`lux install zxing-cpp`).
