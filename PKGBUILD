pkgname=hwgdreqs
pkgver=1.6.1
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

source=("$pkgname-$pkgver.tar.gz::$url/archive/$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$srcdir/$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/$pkgname-$pkgver"
    
    # Install the main package
    python -m installer --destdir="$pkgdir" dist/*.whl
    
    # Install pip-only dependencies directly into the package
    # This uses Python's site-packages in the package directory
    python -m pip install \
        --target="$pkgdir/usr/lib/python$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages" \
        --no-deps \
        "${_pip_deps[@]}"
    
    # Install desktop file
    install -Dm644 hwgdreqs.desktop "$pkgdir/usr/share/applications/hwgdreqs.desktop"
}
