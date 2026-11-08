# Maintainer: Maxime Gauduin <alucryd@archlinux.org>
# Contributor: Ner0 <darkelfdarkelf666@yahoo.co.uk>
# Contributor: dcelasun <dcelasun@gmail.com>

pkgname=plank
pkgver=0.11.89
pkgrel=6
pkgdesc='Elegant, simple, clean dock'
arch=(x86_64)
url=https://launchpad.net/plank
license=(GPL3)
depends=(
  atk
  bamf
  cairo
  gdk-pixbuf2
  glib2
  glibc
  gnome-menus
  gtk3
  libgee
  libwnck3
  libx11
  libxfixes
  libxi
  pango
)
makedepends=(
  git
  vala
)
source=(git+https://github.com/ricotz/plank.git#tag=${pkgver})
b2sums=('edaaff7a113a14799c32badc0f686748e08a81a904ca09300db145ad3dac3ad915a188ae5366141c7d253be537542c0c3535806b423967ba02f18abc7a20b460')

prepare() {
  cd plank
  git cherry-pick -n 5967798a47ba8835ae100c01a8d647d2f9a2412f
  sed 's/0.19.6/0.20/' -i configure.ac
  NOCONFIGURE=1 ./autogen.sh
}

build() {
  cd plank
  ./configure \
    --prefix=/usr \
    --sysconfdir=/etc \
    --disable-apport
  sed -i -e 's/ -shared / -Wl,-O1,--as-needed\0/g' libtool
  make
}

package() {
  make DESTDIR="${pkgdir}" -C plank install
}

# vim: ts=2 sw=2 et:
