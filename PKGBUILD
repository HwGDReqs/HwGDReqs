pkgname=hwgdreqs
pkgver=1.7.0
pkgrel=1
pkgdesc="Geometry Dash level request manager for streamers"
arch=('any')
url="https://github.com/HwGDReqs/HwGDReqs"
license=('GPL-v3')

depends=(
    # System dependencies (all available in official repos)
    'python'
    'pyside6'
    'python-requests'
    'python-cryptography'
    'yt-dlp'
    'python-keyring'
    'python-qrcode'
    'python-websockets'
    'python-pip'  # Keep for pip installs
    'python-hatchling'
)

makedepends=(
    'python-build'
    'python-installer'
    'python-wheel'
    'python-pip'
)

# PyPI packages that aren't in Arch repos
_pip_deps=(
    'pytchat'
    'curl_cffi'
)

# Fixed: GitHub archive extracts to HwGDReqs-1.7.0, not hwgdreqs-1.7.0
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    # The extracted directory is HwGDReqs-1.7.0 (capitalization matters!)
    cd "$srcdir/HwGDReqs-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/HwGDReqs-$pkgver"
    
    # Install the main package
    python -m installer --destdir="$pkgdir" dist/*.whl
    
    # Install pip-only dependencies directly into the package
    python -m pip install \
        --target="$pkgdir/usr/lib/python$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages" \
        --no-deps \
        "${_pip_deps[@]}"
    
    # Install desktop file if it exists
    if [ -f "hwgdreqs.desktop" ]; then
        install -Dm644 hwgdreqs.desktop "$pkgdir/usr/share/applications/hwgdreqs.desktop"
    fi
}
