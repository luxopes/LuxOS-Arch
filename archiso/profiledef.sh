#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="luxos"
iso_label="LUXOS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="LuxOS"
iso_application="LuxOS Live/Install Medium"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="luxos"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
# konfigurace pro mkarchiso na sestavovacim hostiteli (Arch Linux s pacmanem); live system: airootfs/etc/lux/lux.conf
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
# zstd: rychlejsi start live systemu nez xz
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '19' '-b' '1M')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/.gnupg"]="0:0:700"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/luxos-live-setup"]="0:0:755"
)
