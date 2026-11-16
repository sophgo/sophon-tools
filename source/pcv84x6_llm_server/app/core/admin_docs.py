"""The committed offline documentation assets: what they are, and how big.

The files in ``app/static/docs/`` are third-party bundles (Swagger UI, ReDoc)
committed to the repository because the board is offline -- see
``app/static/docs/README.md`` for their versions and licences. This module
records the sizes and sha256 digests so a test can prove:

* the assets the service actually serves are the ones this build was verified
  against (a truncated copy or a stray partial download fails immediately rather
  than producing a blank page on a customer's board);
* nothing in ``app/static/docs`` is unreferenced (a bundle nobody serves is
  2 MB of repository for nothing).

The service is not validating these at boot -- that would be a boot-time cost and
a boot-time failure mode in exchange for a check the test suite already does --
but ``tests/test_admin_docs.py`` calls :func:`verify` and fails the build.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "static" / "docs"


@dataclass(frozen=True)
class VendoredAsset:
    name: str
    filename: str
    version: str
    license: str
    sha256: str
    bytes: int
    media_type: str

    @property
    def path(self) -> Path:
        return DOCS_DIR / self.filename


#: Digest and size as committed. Regenerate (and re-run the offline browser
#: check) when upgrading upstream: see app/static/docs/README.md.
VENDORED_ASSETS: tuple[VendoredAsset, ...] = (
    VendoredAsset(
        name="swagger-ui-bundle", filename="swagger-ui-bundle.js",
        version="swagger-ui-dist 5.17.14", license="Apache-2.0",
        sha256="c2e4a9ef08144839ff47c14202063ecfe4e59e70a4e7154a26bd50d880c88ba1",
        bytes=1452753, media_type="application/javascript; charset=utf-8"),
    VendoredAsset(
        name="swagger-ui-standalone-preset", filename="swagger-ui-standalone-preset.js",
        version="swagger-ui-dist 5.17.14", license="Apache-2.0",
        sha256="33b7a6f5afcac4902fdf93281be2d2e12db15f241d384606e6e6d17745b7f86f",
        bytes=230293, media_type="application/javascript; charset=utf-8"),
    VendoredAsset(
        name="swagger-ui-css", filename="swagger-ui.css",
        version="swagger-ui-dist 5.17.14", license="Apache-2.0",
        sha256="40170f0ee859d17f92131ba707329a88a070e4f66874d11365e9a77d232f6117",
        bytes=152071, media_type="text/css; charset=utf-8"),
    VendoredAsset(
        name="redoc-standalone", filename="redoc.standalone.js",
        version="redoc 2.1.5", license="MIT",
        sha256="be5c3330c8c35b8fceb29a5b7552ad45bffc2fd9494fe2e1a82fa94179eb5f8f",
        bytes=907625, media_type="application/javascript; charset=utf-8"),
)

#: The licence texts, also committed (Apache-2.0 and MIT both require the notice
#: to travel with the binary). Not served; present in the release tree.
LICENSE_FILES = ("LICENSE-swagger-ui.txt", "LICENSE-redoc.txt")

#: Served names -> media type. ``app/main.py`` serves exactly this set; an asset
#: added here but not there (or the reverse) fails the document test.
SERVED: dict[str, str] = {asset.filename: asset.media_type for asset in VENDORED_ASSETS}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify() -> list[str]:
    """Problems with the committed assets: [] when everything checks out."""
    problems: list[str] = []
    for asset in VENDORED_ASSETS:
        path = asset.path
        if not path.is_file():
            problems.append(f"{asset.filename}: missing (expected {asset.bytes} bytes)")
            continue
        size = path.stat().st_size
        if size != asset.bytes:
            problems.append(f"{asset.filename}: {size} bytes, expected {asset.bytes}")
        actual = digest(path)
        if actual != asset.sha256:
            problems.append(f"{asset.filename}: sha256 {actual}, expected {asset.sha256}")
    for name in LICENSE_FILES:
        if not (DOCS_DIR / name).is_file():
            problems.append(f"{name}: missing licence text")
    known = {a.filename for a in VENDORED_ASSETS} | set(LICENSE_FILES) | {"README.md"}
    for path in sorted(DOCS_DIR.iterdir()):
        if path.name not in known:
            problems.append(f"{path.name}: in app/static/docs but not in VENDORED_ASSETS")
    return problems
