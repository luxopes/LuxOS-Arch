# LuxOS - doplnek mkarchiso pro kazde ISO (container-build.sh ho nacte do kopie mkarchiso pred _build,
# stejne jako mkarchiso-secureboot.sh). Neni samostatny skript - jen obali dve funkce mkarchiso.
#
# 1) /etc/.updated a /var/.updated se stejnym casem jako /usr: live system jinak pri kazdem startu
#    spustil ldconfig.service (ConditionNeedsUpdate=/etc, ~8 s pred basic.target) a dalsi jednotky
#    "po aktualizaci", prestoze ld.so.cache v ISO uz je aktualni (pacstrap, hooky baliku).
# 2) Popisek EFI oddilu "LUXOS" misto "ARCHISO_EFI" (MokManager ho ukazuje v "Enroll key from disk",
#    soubory na USB). Live system oddil hleda podle UUID ISO (archisosearchuuid), ne podle popisku.

LUXOS_EFI_LABEL=LUXOS

eval "$(declare -f _prepare_airootfs_image | sed '1s/^_prepare_airootfs_image/_luxos_orig_prepare_airootfs_image/')"

_prepare_airootfs_image() {
    local d
    for d in etc var; do
        printf '# This file was created by the LuxOS ISO build (like systemd-update-done).\n' \
            >"${pacstrap_dir}/${d}/.updated"
        touch -r "${pacstrap_dir}/usr" "${pacstrap_dir}/${d}/.updated"
    done
    _msg_info "LuxOS: /etc/.updated and /var/.updated match /usr (no ldconfig at every live start)"
    _luxos_orig_prepare_airootfs_image "$@"
}

eval "$(declare -f _make_efibootimg | sed '1s/^_make_efibootimg/_luxos_label_orig_make_efibootimg/')"

_make_efibootimg() {
    _luxos_label_orig_make_efibootimg "$@"
    mlabel -i "${efibootimg}" "::${LUXOS_EFI_LABEL}" ||
        _msg_warning "LuxOS: could not set the EFI partition label"
}
