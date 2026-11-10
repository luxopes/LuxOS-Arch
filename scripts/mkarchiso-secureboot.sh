# LuxOS - Secure Boot v ISO: doplnek mkarchiso (container-build.sh ho nacte do kopie mkarchiso pred _build).
# Neni samostatny skript - jen predefinuje dve funkce mkarchiso (archiso 92+), puvodni zustavaji volane.
#
# Kdyz je v live systemu luxos-secureboot s podepsanym systemd-boot (klic LuxOS), EFI oddil ISO
# (efiboot.img, El Torito i oddil 2 na USB) a adresar EFI v ISO 9660 dostanou:
#   EFI/BOOT/BOOTx64.EFI = shimx64.efi (Fedora, podepsany Microsoftem - firmware s klici Microsoftu ho spusti)
#   EFI/BOOT/grubx64.efi = systemd-boot podepsany klicem LuxOS (shim spousti grubx64.efi ze sveho adresare)
#   EFI/BOOT/mmx64.efi   = MokManager (shim ho spusti sam, kdyz klic LuxOS jeste neni v MOK)
#   /LUXOS_ENROLL_THIS_KEY.cer = certifikat LuxOS jako prvni soubor EFI oddilu (MokManager: Enroll key from disk)
# Jadro v ISO uz je podepsane (balik linux-luxos podepsal spravce, scripts/sb-sign.sh). Nepodepsany
# systemd-boot (napr. sestaveni bez klice) = ISO jako driv, bez shim (varovani v logu).

LUXOS_SB_LIB_REL=usr/lib/luxos/secureboot
LUXOS_SB_CERT_REL=usr/share/luxos/secureboot/luxos-secureboot.pem
LUXOS_SB_KEYFILE=LUXOS_ENROLL_THIS_KEY.cer

_luxos_sb_ready() {  # podepsany systemd-boot + shim v live systemu?
    local lib=${pacstrap_dir}/${LUXOS_SB_LIB_REL} cert=${pacstrap_dir}/${LUXOS_SB_CERT_REL}
    [[ -e $lib/shimx64.efi && -e $lib/mmx64.efi && -e $lib/systemd-bootx64.efi && -e $cert ]] || return 1
    if ! sbverify --cert "$cert" "$lib/systemd-bootx64.efi" >/dev/null 2>&1; then
        _msg_warning "luxos-secureboot: systemd-boot is NOT signed with the LuxOS key - ISO without Secure Boot support"
        return 1
    fi
}

eval "$(declare -f _make_common_bootmode_uefi.systemd-boot_copy_files |
        sed '1s/^_make_common_bootmode_uefi.systemd-boot_copy_files/_luxos_orig_sdboot_copy_files/')"
eval "$(declare -f _make_bootmode_uefi.systemd-boot | sed '1s/^_make_bootmode_uefi.systemd-boot/_luxos_orig_make_sdboot/')"

_make_common_bootmode_uefi.systemd-boot_copy_files() {
    _luxos_orig_sdboot_copy_files "$@"
    # mkarchiso predava "x64" (soubor BOOTx64.EFI) - prepsat presne ten, ne pridat BOOTX64.EFI vedle
    [[ ${1^^} == X64 ]] || return 0
    _luxos_sb_ready || return 0
    local lib=${pacstrap_dir}/${LUXOS_SB_LIB_REL}
    _msg_info "Secure Boot: shim (Microsoft-signed) + systemd-boot signed with the LuxOS key + MokManager"
    install -m 0644 -- "$lib/systemd-bootx64.efi" "${isofs_dir}/EFI/BOOT/grubx64.efi"
    install -m 0644 -- "$lib/mmx64.efi" "${isofs_dir}/EFI/BOOT/mmx64.efi"
    install -m 0644 -- "$lib/shimx64.efi" "${isofs_dir}/EFI/BOOT/BOOT${1}.EFI"
    openssl x509 -in "${pacstrap_dir}/${LUXOS_SB_CERT_REL}" -outform DER -out "${isofs_dir}/${LUXOS_SB_KEYFILE}"
}

eval "$(declare -f _make_efibootimg | sed '1s/^_make_efibootimg/_luxos_orig_make_efibootimg/')"

# Certifikat do korene EFI oddilu (MokManager vidi jen FAT, ne ISO 9660) jako PRVNI polozku adresare:
# v "Enroll key from disk" je pak hned nahore a staci Enter (poradi = poradi zapisu do FAT).
_make_efibootimg() {
    _luxos_orig_make_efibootimg "$@"
    [[ -e ${isofs_dir}/${LUXOS_SB_KEYFILE} ]] || return 0
    mcopy -i "${efibootimg}" "${isofs_dir}/${LUXOS_SB_KEYFILE}" "::/${LUXOS_SB_KEYFILE}"
}

_make_bootmode_uefi.systemd-boot() {
    _luxos_orig_make_sdboot "$@"
    [[ -e ${isofs_dir}/${LUXOS_SB_KEYFILE} ]] || return 0
    mdir -i "${efibootimg}" "::/EFI/BOOT" | grep -i grubx64 >/dev/null ||
        _msg_error "Secure Boot files missing in efiboot.img" 1
    mdir -b -i "${efibootimg}" "::/" | head -n1 | grep -q "${LUXOS_SB_KEYFILE}" ||
        _msg_warning "Secure Boot: ${LUXOS_SB_KEYFILE} is not the first file on the EFI partition"
}
