# Secure Boot: first start

LuxOS starts with **Secure Boot on**. Do not turn it off. On the very first start from the LuxOS USB
stick the computer asks once to trust the LuxOS key; it takes less than a minute and nothing has to be
typed. Use the arrow keys and **Enter**. Why and how it works: [Secure Boot](secure-boot.html).

## 1. Start from the USB stick

Plug in the LuxOS USB stick and choose it in the boot menu of the computer (often **F12**, **F11**,
**F8** or **Esc** right after switching on). A blue screen appears: **Verification failed: (0x1A)
Security Violation**. This is expected the first time. Press **Enter** (OK).

![shim: Verification failed, OK](/assets/secureboot/sb-01-verification-failed.webp)

## 2. Press any key

"Press any key to perform MOK management" counts down from 10 seconds. Press **Space** (any key).
If the time runs out, the blue screen from step 1 comes back – just try again.

![MokManager: Press any key to perform MOK management](/assets/secureboot/sb-02-press-any-key.webp)

The blue **MokManager** menu **Perform MOK management** opens. Press the down arrow once to
**Enroll key from disk** and press **Enter**.

![MokManager: Enroll key from disk](/assets/secureboot/sb-02-mok-menu.webp)

## 3. Choose the USB stick

Choose the LuxOS USB stick (labelled **ARCHISO_EFI**, usually the only item) and press **Enter**.

![MokManager: choose the disk](/assets/secureboot/sb-03-select-disk.webp)

## 4. Choose the LuxOS key

**LUXOS_ENROLL_THIS_KEY.cer** is the first item: press **Enter**.

![MokManager: LUXOS_ENROLL_THIS_KEY.cer](/assets/secureboot/sb-04-select-file.webp)

## 5. Continue and confirm

Choose **Continue**, then **Yes** to "Enroll the key(s)?".

![MokManager: Continue](/assets/secureboot/sb-05-continue.webp)

![MokManager: Enroll the key(s)? Yes](/assets/secureboot/sb-06-confirm.webp)

## 6. Reboot

Choose **Reboot**. The computer starts again from the USB stick.

![MokManager: Reboot](/assets/secureboot/sb-07-reboot.webp)

## 7. LuxOS starts with Secure Boot on

The LuxOS boot menu appears for a moment and the live system starts. Install LuxOS as usual – the installed system
starts directly, because the key is already in the computer. In a terminal, `mokutil --sb-state`
shows `SecureBoot enabled`.

![LuxOS live desktop with Secure Boot on](/assets/secureboot/sb-08-live-desktop.webp)

## If the computer refuses the USB stick

If the firmware shows "Secure Boot violation" or "Image failed to verify" before the blue screen,
the computer has the Microsoft 3rd-party certificate turned off (some "Secured-core" laptops). In the
firmware settings, on the Security or Secure Boot page, turn on **Allow Microsoft 3rd Party UEFI CA**
and try again. Secure Boot stays on. More in [Secure Boot](secure-boot.html#troubleshooting).
