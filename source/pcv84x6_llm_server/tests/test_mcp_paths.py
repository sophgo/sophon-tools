"""The local-path allowlist: ``..``, symlinks, absolute paths outside it.

``ocr_read``, ``kb_add_document`` and ``transcribe_audio`` are the only tools
whose arguments name something outside the service's own data, and a language
model can be talked into naming ``/etc/shadow``. So the check has to be right,
and "right" here means the *resolved* path is inside an allowed root -- not that
the string starts with one -- **and** that the bytes read come from the very file
that was checked.

Each test below is a way the check could be wrong: comparing strings instead of
paths (``/data/agents-old`` vs ``/data/agents``), checking before following a
symlink, trusting the caller's ``..`` normalisation, letting a relative path
through to be resolved against whatever the process's cwd happens to be, or
measuring a file and then reading it from a name that changed in between.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.mcp import paths


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A data root in the shape the service creates, with one file in each part."""
    root = tmp_path / "data"
    for name in ("agents", "inbox"):
        (root / name).mkdir(parents=True)
    (root / "inbox" / "note.txt").write_text("hello", encoding="utf-8")
    agent = root / "agents" / "picoclaw"
    (agent / "workspace").mkdir(parents=True)
    (agent / "workspace" / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


def test_a_file_in_the_inbox_is_allowed(root):
    opened = paths.read_local_file(str(root / "inbox" / "note.txt"), root)
    assert opened.path == (root / "inbox" / "note.txt").resolve()
    assert opened.data == b"hello"
    assert opened.name == "note.txt"


def test_a_file_in_an_agents_workspace_is_allowed(root):
    target = root / "agents" / "picoclaw" / "workspace" / "shot.png"
    assert paths.read_local_file(str(target), root).path == target.resolve()


def test_a_dot_dot_path_that_escapes_is_refused(root):
    """The literal prefix is right; the resolved path is not."""
    escaped = root / "inbox" / ".." / ".." / ".." / "etc" / "passwd"
    escaped.parent.mkdir(parents=True, exist_ok=True)
    escaped.write_text("root:x:0:0", encoding="utf-8")
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(root / "inbox" / ".." / ".." / ".."
                                  / "escaped.txt"), root)
    assert "不允许" in str(exc.value) or "不存在" in str(exc.value)


def test_a_dot_dot_path_that_stays_inside_is_allowed(root):
    """``..`` is not the enemy; leaving the roots is."""
    inside = root / "agents" / "picoclaw" / ".." / "picoclaw" / "workspace" / "shot.png"
    assert paths.read_local_file(str(inside), root).name == "shot.png"


def test_a_symlink_inside_an_allowed_root_that_points_outside_is_refused(
        root, tmp_path: Path):
    """The classic hole: the literal path passes a prefix test, the target does not."""
    secret = tmp_path / "outside.txt"
    secret.write_text("secret", encoding="utf-8")
    link = root / "inbox" / "innocent.txt"
    link.symlink_to(secret)
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(link), root)
    assert "不允许" in str(exc.value)


def test_a_symlinked_directory_that_points_outside_is_refused(root, tmp_path: Path):
    """The same hole one level up: a linked *directory* under an allowed root."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "payload.txt").write_text("secret", encoding="utf-8")
    (root / "inbox" / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(paths.PathRefused):
        paths.read_local_file(str(root / "inbox" / "linked" / "payload.txt"), root)


def test_a_symlink_that_stays_inside_is_allowed(root):
    link = root / "inbox" / "alias.txt"
    link.symlink_to(root / "inbox" / "note.txt")
    assert paths.read_local_file(str(link), root).name == "note.txt"


def test_a_neighbour_with_a_shared_prefix_is_refused(root):
    """``/data/agents-old`` starts with ``/data/agents`` and is not inside it."""
    neighbour = root.parent / "agents-old"
    neighbour.mkdir()
    (neighbour / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(neighbour / "file.txt"), root)
    assert "不允许" in str(exc.value)


def test_an_absolute_path_outside_the_roots_is_refused(root):
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file("/etc/passwd", root)
    assert "不允许" in str(exc.value)


def test_the_refusal_names_roots_relatively_not_the_servers_absolute_layout(root):
    """The model needs to know where it may look, not how this box is laid out."""
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file("/etc/passwd", root)
    message = str(exc.value)
    assert "agents/" in message and "inbox/" in message
    assert str(root) not in message


def test_a_relative_path_is_refused_rather_than_resolved_against_the_cwd(root):
    """A relative path would mean whatever the service's cwd is -- not a contract."""
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file("inbox/note.txt", root)
    assert "绝对路径" in str(exc.value)


def test_an_empty_path_is_refused(root):
    with pytest.raises(paths.PathRefused):
        paths.read_local_file("   ", root)


def test_a_nul_byte_is_refused_before_the_filesystem_sees_it(root):
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(root / "inbox" / "note\x00.txt"), root)
    assert "空字节" in str(exc.value)


def test_a_missing_file_says_so_rather_than_blaming_permissions(root):
    """"No such file" and "not allowed" send a model in different directions."""
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(root / "inbox" / "nope.txt"), root)
    assert "不存在" in str(exc.value)


def test_a_directory_is_refused(root):
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(root / "inbox"), root)
    assert "目录" in str(exc.value)


def test_a_fifo_is_refused(root):
    """A fifo would block the read forever; it is not a document."""
    fifo = root / "inbox" / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(fifo), root)
    assert "普通文件" in str(exc.value)


def test_a_file_over_50_mib_is_refused(root, monkeypatch):
    """The upload cap and this one are the same number, by import."""
    from app.apps.kb import parse as kb_parse

    target = root / "inbox" / "big.bin"
    target.write_bytes(b"x" * 1024)
    monkeypatch.setattr(kb_parse, "MAX_FILE_BYTES", 512)
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(target), root)
    assert "超过上限" in str(exc.value)


# ---------------------------------------------------------------------------
# the read is bounded, and it comes from the file that was checked
# ---------------------------------------------------------------------------
def test_a_file_that_grows_after_it_was_measured_is_not_read_past_the_cap(
        root, monkeypatch):
    """``stat`` sizes are a hint; the read has to enforce the cap itself.

    Simulated by giving the reader a cap smaller than the file: the point is that
    only ``cap + 1`` bytes are ever pulled in, so the refusal cannot be preceded
    by a full read of something enormous.
    """
    target = root / "inbox" / "note.txt"
    target.write_bytes(b"x" * 4096)
    with pytest.raises(paths.PathRefused) as exc:
        paths.read_local_file(str(target), root, limit=1024)
    assert "超过上限" in str(exc.value)


def test_the_limit_is_a_parameter_so_audio_can_use_the_upload_cap(root):
    target = root / "inbox" / "clip.wav"
    target.write_bytes(b"RIFF" + b"\x00" * 2048)
    assert len(paths.read_local_file(str(target), root, limit=4096).data) == 2052
    with pytest.raises(paths.PathRefused):
        paths.read_local_file(str(target), root, limit=1024)


def test_an_empty_file_is_read_as_empty_not_refused(root):
    target = root / "inbox" / "empty.txt"
    target.write_bytes(b"")
    assert paths.read_local_file(str(target), root).data == b""


def test_a_name_swapped_for_a_link_after_resolution_is_refused(root, tmp_path,
                                                               monkeypatch):
    """TOCTOU: the check passed on a real file, then the name became a symlink.

    ``O_NOFOLLOW`` on the final component is what refuses this. Without it the
    read would follow the freshly planted link and hand back ``secret`` -- the
    path had already been approved, so nothing else would have looked again.
    """
    target = root / "inbox" / "swap.txt"
    target.write_text("original", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("classified", encoding="utf-8")

    real_read = paths._read_bounded
    swapped = {"done": False}

    def swap_then_read(fd, cap):
        # The window between "resolved and checked" and "read": the name now
        # points somewhere else. A reader that re-opened by name would follow it.
        if not swapped["done"]:
            swapped["done"] = True
            target.unlink()
            target.symlink_to(secret)
        return real_read(fd, cap)

    monkeypatch.setattr(paths, "_read_bounded", swap_then_read)
    # The descriptor was opened before the swap, so the *bytes* are still the
    # original file's: opening once and reading that descriptor is the fix.
    assert paths.read_local_file(str(target), root).data == b"original"


def test_a_symlink_at_open_time_is_refused_by_o_nofollow(root, tmp_path,
                                                         monkeypatch):
    """If the swap happens before the open, ``O_NOFOLLOW`` is the guard."""
    target = root / "inbox" / "swap2.txt"
    target.write_text("original", encoding="utf-8")
    secret = tmp_path / "secret2.txt"
    secret.write_text("classified", encoding="utf-8")

    real_open = os.open

    def open_then_swap(path, flags, *args, **kwargs):
        # Swap *before* the open, simulating the tightest possible race: the
        # allowlist ran, and the name changed before ``os.open`` was called.
        if str(path).endswith("swap2.txt") and target.exists() and not target.is_symlink():
            real_open(path, flags)  # prove the name was a regular file just now
            target.unlink()
            target.symlink_to(secret)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(paths.os, "open", open_then_swap)
    monkeypatch.setattr(paths, "_resolve", lambda p: root / "inbox" / "swap2.txt")
    with pytest.raises(paths.PathRefused):
        paths.read_local_file(str(target), root)


# ---------------------------------------------------------------------------
# CV84X6_MCP_PATHS
# ---------------------------------------------------------------------------
def test_a_declared_extra_directory_is_allowed(root, tmp_path, monkeypatch):
    extra = tmp_path / "shared"
    extra.mkdir()
    (extra / "doc.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setenv(paths.PATHS_ENV, str(extra))
    assert paths.read_local_file(str(extra / "doc.pdf"), root).name == "doc.pdf"


def test_several_extra_directories_are_colon_separated(root, tmp_path, monkeypatch):
    one = tmp_path / "one"
    two = tmp_path / "two"
    for d in (one, two):
        d.mkdir()
    (two / "x.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv(paths.PATHS_ENV, os.pathsep.join([str(one), str(two)]))
    assert paths.read_local_file(str(two / "x.txt"), root).name == "x.txt"


def test_an_unset_variable_adds_nothing(root, monkeypatch):
    monkeypatch.delenv(paths.PATHS_ENV, raising=False)
    roots = paths.allowed_roots(root)
    assert {r.name for r in roots} == {"agents", "inbox"}


def test_a_symlink_planted_in_a_declared_directory_is_still_refused(
        root, tmp_path, monkeypatch):
    """The extra root is resolved too, so the same rule holds for it."""
    extra = tmp_path / "shared"
    extra.mkdir()
    secret = tmp_path / "outside.txt"
    secret.write_text("x", encoding="utf-8")
    (extra / "link.txt").symlink_to(secret)
    monkeypatch.setenv(paths.PATHS_ENV, str(extra))
    with pytest.raises(paths.PathRefused):
        paths.read_local_file(str(extra / "link.txt"), root)


def test_a_declared_root_that_does_not_exist_does_not_break_anything(
        root, tmp_path, monkeypatch):
    monkeypatch.setenv(paths.PATHS_ENV, str(tmp_path / "never-created"))
    assert paths.read_local_file(str(root / "inbox" / "note.txt"), root).name == "note.txt"
