"""The packaging scripts: what they ship, and the rules the deb must obey.

Two layers of checking here.

1. **Static**, against the sources: the version has one home, the maintainer
   scripts are POSIX sh with `set -e` and no unguarded variable, purge does not
   delete the data directory, prerm never SIGKILLs, and the deb's payload comes
   from the same tree as the tarball. These run everywhere, including a build
   host with no dpkg.

2. **Built artefact**, against `dist/*.deb` when one exists. Skipped otherwise:
   building needs the board's engine library and the tokenizer config, which are
   not in git. The lifecycle test that actually installs, upgrades, removes and
   purges the package is ``scripts/test_deb.sh`` -- it needs docker, so it is a
   tool rather than a pytest case.

The reason for checking text at all: every rule here was broken or nearly broken
while writing the scripts. `apt purge` deleting 20 GB of models, or a maintainer
script dying on an unset variable, is not something to find out on a customer's
board.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
MAINTAINER = ("preinst", "prerm", "postinst", "postrm")


def _deb_path() -> Path | None:
    debs = sorted((ROOT / "dist").glob("cv84x6-llm-server_*_arm64.deb"))
    return debs[-1] if debs else None


# -- version has one home --------------------------------------------------

def test_version_comes_from_one_place():
    """`app/__init__.py` is the only source; the packaging reads it."""
    init = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__ = "([^"]+)"', init).group(1)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version

    deb = (SCRIPTS / "package_deb.sh").read_text(encoding="utf-8")
    assert "app/__init__.py" in deb, "package_deb.sh must read the version from app/"
    # A literal version in either packaging script would be a second source.
    for name in ("package.sh", "package_deb.sh"):
        src = (SCRIPTS / name).read_text(encoding="utf-8")
        assert not re.search(r'VERSION=\d+\.\d+', src), f"{name} hardcodes a version"


def test_console_version_matches_the_service():
    """The console's package.json is the second copy; a release must sync it.

    `web/package.json` is not read at runtime (the API reports the version), so
    this cannot be a correctness bug -- but a console labelled 0.6.8 inside a
    0.6.9 deb is a confusing thing to hand an operator.
    """
    import json
    init = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__ = "([^"]+)"', init).group(1)
    pkg = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "web" / "package-lock.json").read_text(encoding="utf-8"))
    assert pkg["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version


# -- the same payload for both formats -------------------------------------

def test_package_sh_can_stage_without_tarring():
    """The deb wraps package.sh's tree, so the two formats cannot drift.

    If package_deb.sh grew its own copy of "what goes in a release", the deb and
    the tarball would diverge the first time a file was added to one of them.
    """
    src = (SCRIPTS / "package.sh").read_text(encoding="utf-8")
    assert "--stage)" in src, "package.sh lost its --stage output"
    assert "staged " in src
    deb = (SCRIPTS / "package_deb.sh").read_text(encoding="utf-8")
    assert "--stage" in deb, "package_deb.sh does not reuse package.sh's tree"
    assert "scripts/package.sh" in deb


def test_package_sh_still_produces_a_tarball_by_default():
    """--stage is additive; the tarball flow has to keep working."""
    src = (SCRIPTS / "package.sh").read_text(encoding="utf-8")
    assert 'tar -C "$STAGE" -czf' in src
    assert ".tar.gz.sha256" in src


def test_the_ocr_prerequisites_are_vendored_or_borrowed_explicitly():
    """The OCR path needs three things the chat path does not.

    Each is a different decision, and this is where the decision is written down
    so a future "tidy up the vendor list" cannot quietly undo one:

    * ``pyclipper`` -- vendored, because nothing on the device ships it and DB's
      unclip cannot work without it;
    * ``numpy`` -- vendored, because the OCR arithmetic is numpy;
    * OpenCV -- **not** vendored. The device's sophon-opencv is used instead
      (``/opt/sophon/sophon-opencv-latest/opencv-python``), the same policy as
      ffmpeg: the SDK owns the build, and shipping a second one would be a
      different library with a different ``minAreaRect``.
    """
    src = (SCRIPTS / "package.sh").read_text(encoding="utf-8")
    # sophon-tools adaptation: every vendored wheel's version is read from
    # requirements-vendor-lock.txt (the single version source). The assertion
    # pins the COMMAND (--no-deps + lockfile read), and for numpy additionally
    # the 1.x policy: the lockfile itself is checked to pin numpy==1.*.
    lock = (ROOT / "requirements-vendor-lock.txt").read_text(encoding="utf-8")
    assert "--no-deps \"$(grep -oE '^pyclipper==" in src, "pyclipper must be vendored from the lockfile"
    assert '--no-deps "$NUMPY_SPEC"' in src, "numpy must be vendored"
    # ...and pinned below 2: the device's cv2.so is built against the numpy 1
    # C ABI, so a numpy 2 vendor breaks `import cv2` and with it every OCR model.
    numpy_lock = re.search(r"^numpy==([^#\s]+)", lock, re.M)
    assert numpy_lock and numpy_lock.group(1).startswith("1."), numpy_lock
    assert "grep -oE '^numpy==" in src, \
        "numpy version must come from the lockfile"
    assert 'numpy-1.*.dist-info' in src, "the build must refuse a numpy 2 vendor"
    # And the model config the OCR worker reads.
    assert "ppocr_v6/ppocr.json" in src
    assert "ppocr_v6/ppocr_keys_v1.txt" in src
    # OpenCV must not be vendored: a ``pip install --target "$D/vendor"`` of it
    # would mean somebody reversed the decision above. Tested on the commands,
    # not on the word -- the comment above explains the policy and necessarily
    # names it.
    installs = [line for line in src.splitlines()
                if "pip install" in line or "--no-deps" in line]
    assert not any("opencv" in line.lower() for line in installs), (
        "OpenCV must come from the device's Sophon SDK, not from the package")
    # The three wheels are checked in a loop, so the assertion is on the loop and
    # its member list rather than on three separate commands.
    assert 'compgen -G "$D/vendor/$required_pkg*"' in src, (
        "a missing vendored wheel must fail the build")
    assert 'for required_pkg in tokenizers pyclipper numpy' in src, (
        "the wheel check must cover every wheel the OCR path needs")


def test_the_ocr_pipeline_imports_the_devices_opencv():
    """The other half of the policy: the code has to actually look there.

    A path list in the module is what makes "we do not vendor OpenCV" a working
    arrangement rather than an omission -- without it the worker would fail at
    import on a board where the SDK's OpenCV is exactly where it has always been.
    """
    from app.engine.ocr_ppocr import OPENCV_DIRS

    assert any("/opt/sophon/sophon-opencv" in path for path in OPENCV_DIRS), OPENCV_DIRS


# -- maintainer scripts ----------------------------------------------------

def _strip_comments(text: str) -> str:
    """Shell source with comment lines removed.

    The rules below are about what a script *does*. Every script here explains
    in a comment why it does not SIGKILL, so matching raw text would fail on the
    explanation rather than the code.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _script_body(name: str) -> str:
    """The body of a maintainer script as the generator writes it, comments kept.

    This is the source *verbatim*, shebang included: the built copy needs a
    .deb, and reading the generator means the rules are checked on every run
    rather than only when someone has built one. The placeholders (@PKG@) are
    still in place, which is fine -- no rule below depends on their value.

    Comments are deliberately not removed here. The shebang is a comment line,
    so a stripped body can never be checked for it; use `_script_code` for the
    behaviour rules, which are about what the script *does*.
    """
    src = (SCRIPTS / "package_deb.sh").read_text(encoding="utf-8")
    marker = f"<<'{name.upper()}'"
    body = src.split(marker, 1)[1]
    # The heredoc ends at a line that is exactly the delimiter.
    lines = body.splitlines()[1:]  # drop the "| write_script <name>" half-line
    out = []
    for line in lines:
        if line.strip() == name.upper():
            break
        out.append(line)
    return "\n".join(out)


def _script_code(name: str) -> str:
    """`_script_body` with the comments removed -- what the script executes."""
    return _strip_comments(_script_body(name))


def _maintainer_script_from_deb(name: str) -> str | None:
    """The script as the package ships it, so placeholders are already filled.

    Returns None when there is no built package to inspect; those assertions are
    covered against the generator, so skipping here loses no coverage.
    """
    deb = _deb_path()
    if deb is None or shutil.which("dpkg-deb") is None:
        return None
    control = ROOT / ".pytest-deb-control"
    if control.exists():
        shutil.rmtree(control)
    subprocess.check_call(["dpkg-deb", "--control", str(deb), str(control)],
                          stdout=subprocess.DEVNULL)
    try:
        path = control / name
        return path.read_text(encoding="utf-8") if path.exists() else None
    finally:
        shutil.rmtree(control, ignore_errors=True)


def _packaged_script(name: str) -> tuple[str, str]:
    """(body, where it came from) for a maintainer script.

    The .deb's copy wins when one has been built -- that is the text the board
    actually runs, placeholders already substituted. On a clean checkout there
    is no package, so the generator stands in: same rules, every run.
    """
    shipped = _maintainer_script_from_deb(name)
    if shipped is not None:
        return shipped, "deb"
    return _script_body(name), "source"


@pytest.mark.parametrize("name", MAINTAINER)
def test_maintainer_scripts_are_posix_sh(name):
    """`#!/bin/sh` on Ubuntu is dash. Bashisms fail at the worst moment."""
    body, _ = _packaged_script(name)
    assert body.startswith("#!/bin/sh"), f"{name} is not #!/bin/sh"
    assert "set -e" in body, f"{name} does not set -e"
    for bashism in ("[[", "]]", "function ", "local ", "source "):
        assert bashism not in _strip_comments(body), f"{name} uses a bashism: {bashism}"


def test_the_shebang_rule_still_runs_without_a_built_package(monkeypatch):
    """The clean-checkout path, spelled out.

    `dist/` is gitignored and building the package needs the board's libraries,
    so on a fresh checkout the generator is the only text there is. That is
    where a comment-stripped body used to be handed to a `startswith("#!/bin/sh")`
    assertion -- which can never pass, because the shebang *is* a comment.
    """
    monkeypatch.setattr(f"{__name__}._deb_path", lambda: None)
    for name in MAINTAINER:
        body, origin = _packaged_script(name)
        assert origin == "source", f"{name} still went looking for a package"
        assert body.splitlines()[0] == "#!/bin/sh", f"{name} lost its shebang"


def test_a_built_package_still_wins_over_the_generator(monkeypatch):
    """With a deb present the rules read the shipped text, not the generator.

    The substitution step is where a placeholder could survive into the package,
    so the built copy must stay the thing under test when there is one.
    """
    shipped = "#!/bin/sh\nset -e\n"
    monkeypatch.setattr(f"{__name__}._maintainer_script_from_deb",
                        lambda name: shipped)
    assert _packaged_script("postinst") == (shipped, "deb")


def test_maintainer_scripts_quote_every_expansion():
    """Unquoted `$VAR` in a maintainer script is how a path with a space (or an
    empty variable) becomes a deletion of the wrong thing."""
    for name in MAINTAINER:
        code = _script_code(name)
        for line in code.splitlines():
            stripped = line.strip()
            # Assignments legitimately use a bare name on the left.
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", stripped):
                continue
            # Drop every double-quoted span, then see if a $VAR is left over.
            outside = re.sub(r'"[^"]*"', '""', line)
            for match in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*)", outside):
                name_ = match.group(1)
                # `case "$X" in`, `${X:-y}` and `$(...)` are not expansions
                # that need quoting here.
                around = outside[max(0, match.start() - 1):match.end() + 1]
                if around.startswith('"') or around.startswith("{"):
                    continue
                pytest.fail(f"{name}: unquoted ${name_} in: {line.strip()!r}")


def test_prerm_never_force_kills():
    """The NPU worker must be stopped with SIGTERM.

    SIGKILL on a worker that is mapping weights can hang the TPU until the board
    is rebooted. The unit sets ``KillMode=process`` (workers are not signalled by
    systemd at all; the service's own shutdown unloads them with SIGTERM and
    waits), and ``TimeoutStopSec`` gives that shutdown room -- so no signal
    number may appear here at all.
    """
    prerm = _script_code("prerm")
    for forced in ("-9", "SIGKILL", "kill -", "--force"):
        assert forced not in prerm, f"prerm force-kills ({forced})"
    assert "systemctl stop cv84x6-llm" in prerm
    # A failed stop must not abort the dpkg operation.
    assert "||" in prerm


def test_postrm_purge_does_not_delete_the_data_directory():
    """`apt purge` removes the program. Models and keys are not the program.

    This is the single most destructive thing these scripts could get wrong: the
    data directory holds tens of GB of models, the API keys every client uses and
    the console password hash.
    """
    postrm = _script_code("postrm")
    # The only rm -rf is inside the printed hint for the operator. Look for an
    # executed one: a bare `rm -rf` at the start of a command position.
    for line in postrm.splitlines():
        stripped = line.strip()
        if stripped.startswith("rm -rf"):
            pytest.fail(f"postrm executes a tree deletion: {stripped!r}")
    assert "rm -rf $DATA_DIR" in postrm, "purge lost its deletion hint"
    assert "rm -f \"$ENV_FILE\"" in postrm, "purge should drop the configuration"
    # It must read the real data location rather than assume the default.
    assert "CV84X6_DATA_DIR" in postrm
    assert "/data/cv84x6_llm_server" in postrm  # only as the fallback
    # And it must tell the operator how to delete the data themselves.
    assert "rm -rf $DATA_DIR" in postrm


def test_postrm_remove_keeps_the_configuration():
    """`apt remove` must keep server.env: it is the only record of where the
    data went, so a reinstall needs it."""
    postrm = _script_code("postrm")
    remove_branch = postrm.split('if [ "$ACTION" = remove ]')[1].split("fi")[0]
    assert "rm -f" not in remove_branch, "remove must not delete server.env"
    assert "Kept" in remove_branch or "kept" in remove_branch


def test_postinst_refuses_to_run_as_root():
    """A missing service user is a hard stop, not a silent `root`.

    Falling back to root would give every agent the operator installs root on
    the board. That is not a choice a postinst gets to make.
    """
    postinst = _script_code("postinst")
    assert "does not exist" in postinst
    assert "exit 1" in postinst, "a missing user must fail the configure"
    assert "refusing to fall back to root" in postinst


def test_postinst_does_not_leave_dpkg_half_configured():
    """A failed *start* is reported, not turned into a configure failure.

    dpkg treats a non-zero postinst as "package is broken" and blocks every
    later apt operation. The files are in place by then, so the right outcome is
    a configured package plus a journalctl hint.
    """
    postinst = _script_code("postinst")
    # Everything after the start attempt, including the recovery hint (which
    # itself mentions `systemctl start`, so this must be a one-shot split).
    tail = postinst.split("systemctl start cv84x6-llm", 1)[1]
    assert "journalctl -u cv84x6-llm" in tail, "no journalctl hint on a failed start"
    # The hint block ends with `exit 0`: dpkg must consider the package
    # configured even though the service did not come up.
    assert re.search(r"^exit 0$", tail, re.M), "the start-failure path must exit 0"


def test_postinst_reuses_install_sh_in_place():
    """One implementation of "configure the service", not two."""
    postinst = _script_code("postinst")
    assert "install.sh" in postinst
    assert "--in-place" in postinst
    assert "--no-start" in postinst


def test_install_sh_has_an_in_place_mode():
    src = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    assert "--in-place)" in src
    # In place, it must not rsync the tree onto itself.
    assert 'rsync -a --delete --exclude' in src
    # The last occurrence is the one in the program-tree section, not the
    # libsophon warning earlier in the file.
    in_place_branch = src.split('if [ "$IN_PLACE" = 1 ]; then')[-1].split("else")[0]
    assert "rsync" not in in_place_branch, "in-place mode must not copy the tree"
    # It must still fix ownership: dpkg unpacks as root:root, the service is not.
    assert "chown -R" in in_place_branch


def test_install_sh_warns_instead_of_dying_without_libsophon_in_place():
    """dpkg cannot satisfy libsophon from any apt source.

    Dying there would leave the package half-configured over a precondition no
    apt command can fix. The tarball flow still refuses, because there a human
    is watching the output and can install the vendor package.
    """
    src = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    assert "libsophon-current" in src
    block = src.split("libsophon not found at /opt/sophon/libsophon-current")[0]
    assert '"$IN_PLACE" = 1' in block, "libsophon must be fatal only for the tarball flow"


def test_install_sh_does_not_touch_a_host_without_systemd():
    """A container or build host has no systemd; `systemctl` under `set -e`
    would abort a configure that is otherwise complete."""
    src = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    assert "/run/systemd/system" in src
    # The daemon-reload/enable must be inside the guard, not before it.
    guard = src.split('if [ -d /run/systemd/system ]; then')[1].split("else")[0]
    assert "systemctl daemon-reload" in guard
    assert "systemctl enable" in guard


# -- the built artefact ----------------------------------------------------

@pytest.mark.parametrize("field,expected", [
    ("Package", "cv84x6-llm-server"),
    ("Architecture", "arm64"),
    ("Section", "misc"),
    ("Priority", "optional"),
])
def test_deb_control_has_the_required_fields(field, expected):
    deb = _deb_path()
    if deb is None:
        pytest.skip("no built .deb")
    out = subprocess.check_output(["dpkg-deb", "-f", str(deb), field], text=True).strip()
    assert out == expected


def test_deb_depends_on_real_packages():
    """Every dependency must exist under that exact name in Ubuntu jammy.

    `python3.10-minimal` provides /usr/bin/python3.10 but `python3.10` is the
    package an operator would name; both exist in jammy, and the wider one is
    the right dependency. A typo here makes the package uninstallable.
    """
    deb = _deb_path()
    if deb is None:
        pytest.skip("no built .deb")
    depends = subprocess.check_output(["dpkg-deb", "-f", str(deb), "Depends"], text=True)
    names = {re.split(r"[\s(]", d.strip())[0] for d in depends.split(",")}
    known = {
        "python3.10", "systemd", "curl", "rsync", "libjpeg-turbo8",
        "zlib1g", "libstdc++6", "libc6",
    }
    assert names <= known, f"unknown dependency name(s): {names - known}"
    # libsophon is the vendor runtime and is in no apt source: it must not be a
    # hard dependency, or the package could never be configured offline.
    assert not any("libsophon" in n for n in names)


def test_deb_installs_under_the_documented_prefix():
    deb = _deb_path()
    if deb is None:
        pytest.skip("no built .deb")
    contents = subprocess.check_output(["dpkg-deb", "-c", str(deb)], text=True)
    assert "/opt/sophgo/cv84x6_llm_server/app/main.py" in contents
    assert "/opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so" in contents
    assert "/opt/sophgo/cv84x6_llm_server/web/dist/index.html" in contents
    assert "/opt/sophgo/cv84x6_llm_server/etc/server.env" not in contents, \
        "server.env must not ship: postinst generates it and keeps the operator's"


def test_deb_version_matches_the_service():
    deb = _deb_path()
    if deb is None:
        pytest.skip("no built .deb")
    init = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__ = "([^"]+)"', init).group(1)
    got = subprocess.check_output(["dpkg-deb", "-f", str(deb), "Version"], text=True)
    assert got.strip() == version
    assert version in deb.name


def test_install_sh_does_not_require_sudo_to_drop_privileges():
    """A root postinst has no reason to depend on sudo.

    `sudo -u` was the only way install.sh switched to the service user, so a
    minimal image without sudo failed the whole configure with "no Python 3.10
    found" -- the interpreter check runs as that user. runuser is util-linux and
    always present; sudo is not a Depends of this package.
    """
    src = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    fn = src.split("as_user() {", 1)[1].split("\n}", 1)[0]
    assert "runuser" in fn, "as_user does not use runuser"
    assert "sudo" in fn, "as_user lost its sudo fallback"
    # runuser must be tried before sudo, not after.
    assert fn.index("runuser") < fn.index("sudo")
    # And there must be a branch for an image with neither.
    assert fn.count("else") >= 2


def test_install_sh_warns_about_libsophon_in_place_and_dies_for_the_tarball():
    src = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    block = src.split("libsophon-current/lib", 1)[1].split("fi\nfi", 1)[0]
    assert "warning: libsophon not found" in block
    assert 'die "libsophon not found' in block


def test_deb_md5sums_match_the_payload():
    """`dpkg -V` checks these; a wrong format makes every file unverifiable.

    dpkg looks each path up literally under /, so a leading "./" (what `find .`
    prints) or a one-space separator silently breaks verification for the whole
    package -- `dpkg -V` then reports nothing even after a file is corrupted.
    """
    import hashlib
    import tempfile
    deb = _deb_path()
    if deb is None:
        pytest.skip("no built .deb")
    import os
    root = tempfile.mkdtemp()
    control = Path(root + "-ctl")
    subprocess.check_call(["dpkg-deb", "-x", str(deb), root])
    subprocess.check_call(["dpkg-deb", "--control", str(deb), str(control)])
    lines = (control / "md5sums").read_text().splitlines()
    assert lines, "no md5sums"

    listed = set()
    for line in lines:
        # Exactly "<32 hex><two spaces><path>".
        m = re.fullmatch(r"([0-9a-f]{32})  (.+)", line)
        assert m, f"bad md5sums line: {line!r}"
        digest, path = m.groups()
        assert not path.startswith("./"), f"path has a leading ./: {path!r}"
        full = os.path.join(root, path)
        assert os.path.exists(full), f"listed but not shipped: {path}"
        assert hashlib.md5(Path(full).read_bytes()).hexdigest() == digest, path
        listed.add(path)

    on_disk = {
        os.path.relpath(os.path.join(d, f), root)
        for d, _, files in os.walk(root) for f in files
    }
    assert on_disk == listed, f"unlisted shipped files: {sorted(on_disk - listed)}"
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(control, ignore_errors=True)


def test_stale_file_scan_collates_both_lists_the_same_way():
    """`comm` needs identically collated inputs, and these come from two
    different programs.

    The first deb install removes files under the prefix that dpkg does not own
    (a pre-deb install was made by install.sh). The comparison is `comm -13`
    over `dpkg-query -L` and `find` output. Under a UTF-8 locale those can sort
    differently, and the failure mode is not "misses a stale file" but "lists a
    live one as stale" -- this runs as root, so that direction matters.
    """
    postinst = _script_code("postinst")
    assert "comm -13" in postinst, "the stale-file diff is gone"
    # Every command in the pipeline that sorts or compares must pin the locale.
    for line in postinst.splitlines():
        if "sort" in line or "comm -13" in line:
            assert "LC_ALL=C" in line, f"unpinned collation: {line.strip()!r}"


def test_postrm_removes_the_unit_even_without_systemd():
    """The unit file must not survive a remove on a host with no systemd.

    install.sh writes the unit whenever it runs, including on a container or a
    rescue boot where /run/systemd/system is absent. If postrm only deletes it
    inside that guard, a remove there leaves an orphan unit pointing at a prefix
    with no program in it -- and the next boot on a real systemd would try to
    start it. The systemctl calls need a running manager; deleting the file does
    not.
    """
    postrm = _script_code("postrm")
    # Anchored on code, not the section comment (strip_comments removes those).
    section = postrm.split('case "$ACTION" in', 1)[1]
    rm_at = section.index("rm -f /etc/systemd/system/cv84x6-llm.service")
    # The guard that wraps disable/stop must close before the rm.
    disable_at = section.index("systemctl disable")
    guard_close = section.index("\nfi\n", disable_at)
    assert guard_close < rm_at, "the unit rm is still inside the systemd guard"
    # And the guarded part still exists for disable/stop.
    assert "systemctl disable" in section[:guard_close]
    assert "systemctl stop" in section[:guard_close]
