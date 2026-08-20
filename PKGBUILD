pkgname=hwgdreqs
pkgver=1.7.0
pkgrel=1
pkgdesc="Geometry Dash level request manager for streamers"
arch=('any')
url="https://github.com/HwGDReqs/HwGDReqs"
license=('GPL-v3')

depends=(
    'python'
    'pyside6'
    'python-requests'
    'python-cryptography'
    'yt-dlp'
    'python-keyring'
    'python-qrcode'
    'python-websockets'
    'python-pip'
)

makedepends=(
    'python-build'
    'python-installer'
    'python-wheel'
    'python-pip'
    'python-hatchling'
)

_pip_deps=(
    'pytchat'
    'curl_cffi'
)

# Add icon to sources - downloaded separately
source=(
    "$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/$pkgver.tar.gz"
    "hwgdreqs.png::$url/raw/main/assets/logo.png"
)
sha256sums=(
    'SKIP'
    'EAA11BDC7B229C0107D387E7AC1826846966201F9CAF866AF0F02C137227CAB6'
)

build() {
    cd "$srcdir/HwGDReqs-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/HwGDReqs-$pkgver"
    
    python -m installer --destdir="$pkgdir" dist/*.whl
    
    python -m pip install \
        --target="$pkgdir/usr/lib/python$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages" \
        --no-deps \
        "${_pip_deps[@]}"
    
    if [ -f "hwgdreqs.desktop" ]; then
        install -Dm644 hwgdreqs.desktop "$pkgdir/usr/share/applications/hwgdreqs.desktop"
    fi
    
    if [ -f "$srcdir/hwgdreqs.png" ]; then
        install -Dm644 "$srcdir/hwgdreqs.png" "$pkgdir/usr/share/icons/hicolor/256x256/apps/hwgdreqs.png"
        install -Dm644 "$srcdir/hwgdreqs.png" "$pkgdir/usr/share/pixmaps/hwgdreqs.png"
    fi
}