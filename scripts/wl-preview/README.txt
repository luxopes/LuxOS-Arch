LuxOS 1.1.0 - nahled desktopu na Waylandu (zkusebni VM)
=======================================================

Co to je
--------
LuxOS z repozitare LuxOS (aplikace, vzhled, pisma, ikony) a k tomu novy desktop na Waylandu
z vetve wayland-1.1: spravce oken luxwm (libluxcomp), horni lista luxos-bar, Dock luxos-dock,
oznameni luxos-notify, zamek obrazovky luxos-lock, Launchpad/Hledani luxos-launchpad a plocha
luxos-backdrop (tapeta, nabidka plochy pravym tlacitkem) s widgety luxos-widgets.
Vse bezi jen uvnitr VM v okne QEMU, nic z noveho desktopu nebezi ve vasi relaci.

Spusteni
--------
  ./start.sh             normalni spusteni (-vga std, bez 3D akcelerace)
  ./start.sh --virtio    graficka karta virtio-vga (taky bez 3D, bez virgl)
  ./start.sh --reset     zahodit vsechny zmeny ve VM a zacit od cisteho obrazu
                         (lze i spolu: ./start.sh --reset --virtio)
  ./start.sh --tablet    mys jen pres usb-tablet (bez vmmouse QEMU)

VM ma 6 GB RAM a 4 jadra. Zmeny se ukladaji do disk.qcow2, cisty obraz base.qcow2 se nemeni.
Mys se z okna QEMU uvolni pres Ctrl+Alt+G.

Prihlaseni
----------
Start jako nainstalovany system: splash LuxOS (Plymouth) od initramfs, splash skonci az pod hotovou
prihlasovaci obrazovkou (bez cerne mezery a textove konzole).
Po startu prihlasovaci obrazovka LuxOS (greetd, luxos-greeter v LSL pod luxwm, bez X serveru).
Uzivatel luxos, heslo luxos. Vlevo dole volba relace: LuxOS (Wayland, vychozi) nebo LuxOS (X11)
(puvodni Xfce); volba se pamatuje pro kazdeho uzivatele. Na starych kartach NVIDIA (470 a starsi)
a po relaci na Waylandu, ktera skoncila do 10 s od startu, je vybrana LuxOS (X11) sama.
Odhlaseni (nabidka LuxOS > Odhlasit) vrati prihlasovaci obrazovku.
Relace na Waylandu: luxos-wayland-session spusti luxwm a v nem luxos-session.target (lista, Dock,
oznameni, zamek, Launchpad, tapeta, widgety, agent polkitu jako uzivatelske sluzby). Pad listy ci
Docku systemd hned opravi, pad kompozitoru ukonci relaci a vrati prihlasovaci obrazovku.

Konzole: Ctrl+Alt+F2 (v QEMU pres nabidku View nebo Ctrl+Alt+Shift+F2), prihlaseni luxos/luxos.
Zpet do grafiky Ctrl+Alt+F1.
Log spravce oken: ~/.local/state/luxos/luxwm.log, sluzby shellu: journalctl --user -b,
prihlasovaci obrazovka: sudo journalctl -b -u greetd

Klavesnice: cestina a anglictina, prepinani Alt+Shift (ve VM klavesu Super/Cmd zachyti QEMU
jen kdyz je mys v okne zachycena).

Zkratky (luxwm.conf, Super = klavesa Windows/Cmd)
-------------------------------------------------
  Super+T, Ctrl+Alt+T        Terminal
  Super+Space                Hledani
  Super+A                    Launchpad
  Super+E                    Soubory (Thunar)
  Alt+Tab, Alt+Shift+Tab     prepinani oken (pustit Alt = potvrdit, Esc = zrusit)
  Super+Tab                  totez
  Alt+` (klavesa pod Esc)    okna aktualni aplikace
  Ctrl+Super+Sipka vlevo/vpravo   predchozi/dalsi plocha (4 plochy, prejezd jako v macOS)
  Ctrl+Super+1..4            plocha 1-4
  Ctrl+Super+Shift+Sipka / 1..4   presunout okno na jinou plochu
  Super+Q, Alt+F4            zavrit okno
  Super+M, Super+H, Super+Dolu    minimalizovat
  Super+Nahoru               maximalizovat
  Super+Vlevo / Super+Vpravo pulka obrazovky vlevo/vpravo
  Ctrl+Super+F, F11          cela obrazovka
  Super+D                    ukazat plochu
  Super+. , Ctrl+Super+Space emoji
  Ctrl+Shift+Esc             Monitor aktivity
  Zamknout: nabidka LuxOS v liste > Zamknout obrazovku (loginctl lock-session)

Na zkouseni
-----------
  Terminal, Soubory (Thunar), Firefox, Textovy editor a dalsi aplikace LuxOS z Docku nebo Launchpadu
  gtk3-demo                  ukazka prvku GTK
  xeyes                      aplikace X11 (bezi pres XWayland, spusti se sam pri prvni X11 aplikaci)
  notify-send "Ahoj" "Text"  bublina oznameni vpravo nahore
  loginctl lock-session      zamek obrazovky (odemknout heslem luxos)

Zname chybi / omezeni nahledu
-----------------------------
  - Prihlasovaci obrazovka je jen na prvnim monitoru (ostatni maji barvu pozadi); rozlozeni
    klavesnice se na ni prepina zkratkou (Alt+Shift), klik na cip rozlozeni nic nedela.
  - Aplikace z Pythonu (Nastaveni ...) bezi pres XWayland nebo GTK na Waylandu podle toho, co umi;
    snimek obrazovky, emoji, Monitory (Super+P) a klavesnice uz jsou na Waylandu v LSL.
  - Rozlozeni klavesnice se bere z /etc/vconsole.conf pri startu relace, ne zive z locale1.
  - Bez zvuku (VM nema zvukovou kartu).
  - Navrat k LightDM (X11 prihlaseni): sudo lux remove luxos-greetd a restart.

Znovu postavit obraz (vetev wayland-1.1)
---------------------------------------------
  LUXOS_SIGNING_DIR=none ./build.sh one lsl wlroots0.20 luxcomp luxwm luxos-desktop luxos-greetd luxos-greeter \
      luxos-sandbox luxos-i18n luxos-themes luxos-docs luxos-guard luxos-firewall
  scripts/wl-preview/build-image.sh $(ls out/single/*.pkg.tar.zst | grep -v -- -debug-)
  (vsechny baliky z vetve: LSL 0.11.1, preklady shellu na Waylandu, rohy oken s vlastnim zahlavim, sandbox)
