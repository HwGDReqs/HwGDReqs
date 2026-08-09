pkgname=hwgdreqs
pkgver=0.26.1
pkgrel=1
pkgdesc="Geometry Dash level request manager for streamers"
arch=('any')
url="https://github.com/HwGDReqs/HwGDReqs"
license=('MIT')

depends=(
    'python'
    'pyside6'
    'python-requests'
    'python-cryptography'
    'yt-dlp'
    'python-pip'
)

makedepends=(
    'python-build'
    'python-installer'
    'python-wheel'
    'python-pip'
)

source=("$pkgname-$pkgver.tar.gz::$url/archive/$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$srcdir/$pkgname-$pkgver"
    
    pip install --user pytchat
    
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/$pkgname-$pkgver"
    
    pip install --prefix="$pkgdir/usr" pytchat
    
    install -Dm644 hwgdreqs.desktop "$pkgdir/usr/share/applications/hwgdreqs.desktop"
}
