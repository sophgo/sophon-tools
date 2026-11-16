"""Download tags (``--dflag``): tagged install, update detection, one-click update.

The mechanism these tests pin down is how a model is upgraded without a new
service release: the server holds a ``<tag> -> file`` index, the service
downloads *by tag*, and a board that installed yesterday can tell that the file
the tag now names is not the one on its disk.

Three claims, each of which fails silently in production if it is wrong:

* a tag download is never trusted on its own -- the ``<tag>.md5`` sidecar names
  both the digest and the **real file name**, and a tag that serves something
  else is an error rather than an install;
* the fixed URL is a *reported* fallback: an old dfss, a missing tag or no route
  must still produce a working model, and the job message must say which
  transport was used, because that is what an operator has to go on;
* "有新版本" means exactly "the tag names a file this directory does not have",
  computed from a cached index so the catalogue page never waits on the network.

Every test runs against a fake dfss: the real tool needs the vendor's SFTP
servers, and the behaviour under test is this module's, not the tool's.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.core import downloader as dl
from app.core.downloader import (
    DFLAG_MD5_SUFFIX,
    DfssFlags,
    DownloadManager,
    catalog_entry,
    catalog_file_set,
    parse_sidecar,
    update_status,
)

# -- a fake dfss that understands --dflag -----------------------------------
#: ``{tag: (file name, payload)}`` -- exactly what the server's index plus its
#: files would produce. The sidecar is generated from the payload, so a test that
#: changes a body automatically gets a digest that matches it.
Payloads = dict[str, tuple[str, bytes]]


class FakeDfss:
    """A ``run_dfss`` / ``run_dfss_flag`` pair driven by a tag table.

    ``calls`` records ``("flag", tag)`` / ``("url", target)`` so a test can
    assert *how* a file was fetched, which is the part an operator sees.
    """

    def __init__(self, tags: Payloads, *, support_dflag: bool = True,
                 fail_tags: set[str] | None = None,
                 extra_tags: Payloads | None = None) -> None:
        self.tags = tags
        #: Tags with no sidecar beside them: the model is there, the metadata
        #: is not. The catalogue's own digest has to carry the verification.
        self.extra_tags = extra_tags or {}
        self.support_dflag = support_dflag
        self.fail_tags = fail_tags or set()
        self.calls: list[tuple[str, str]] = []

    # -- the two entry points the downloader uses ------------------------
    async def run_flag(self, tag: str, dest_dir: Path, on_line=None):
        self.calls.append(("flag", tag))
        dest_dir = Path(dest_dir)
        if tag in self.fail_tags:
            return 1, [f"ERROR main.cpp:1143: dflag '{tag}' not found in index",
                       "ERROR main.cpp:1405: dflag error"]
        table = dict(self.tags)
        table.update(self.extra_tags)
        for base, (name, body) in list(table.items()):
            if tag == base or tag == base + DFLAG_MD5_SUFFIX:
                if tag.endswith(DFLAG_MD5_SUFFIX):
                    digest = hashlib.md5(body).hexdigest()
                    (dest_dir / (name + ".md5")).write_text(f"{digest}  {name}\n")
                else:
                    (dest_dir / name).write_bytes(body)
                if on_line:
                    on_line(f"[{len(body)} B] 100% [====] 1 MiB/s")
                return 0, ["INFO Download completed."]
        return 1, [f"ERROR main.cpp:1143: dflag '{tag}' not found in index",
                   "ERROR main.cpp:1405: dflag error"]

    async def run_url(self, target: str, dest_dir: Path, on_line=None,
                      bootstrap: bool = True):
        self.calls.append(("url", target))
        name = target.rstrip("/").rsplit("/", 1)[-1]
        for _tag, (fname, body) in self.tags.items():
            if fname == name:
                (Path(dest_dir) / name).write_bytes(body)
                return 0, ["INFO Download completed."]
        return 1, [f"ERROR Cannot download {target} from host"]

    def install(self, monkeypatch) -> "FakeDfss":
        """Wire this fake into the module under test."""
        async def ensure(on_line=None, **_kw):
            return None

        monkeypatch.setattr(dl, "ensure_dfss", ensure)
        monkeypatch.setattr(dl, "run_dfss_flag", self.run_flag)
        monkeypatch.setattr(dl, "run_dfss", self.run_url)
        monkeypatch.setattr(dl, "dfss_dflag_supported",
                            lambda python=None: self.support_dflag)
        return self


def _entry(model_id: str = "qwen3-asr-0.6b") -> dict:
    """A real catalogue entry, copied so a test can edit it."""
    entry = catalog_entry(model_id)
    assert entry is not None
    return json.loads(json.dumps(entry))


@pytest.fixture(autouse=True)
def _models_root(tmp_path):
    """Every test starts with an empty models tree.

    ``check_space`` stats the filesystem through this directory, and the
    downloader installs into it -- creating it here keeps that setup out of
    twenty tests that are about something else.
    """
    (tmp_path / "models").mkdir(exist_ok=True)
    return tmp_path / "models"


def _with_digest(entry: dict, payload: bytes) -> dict:
    """The entry's declared md5 replaced with the payload's own."""
    entry["md5"] = hashlib.md5(payload).hexdigest()
    return entry


# -- sidecar parsing -------------------------------------------------------
def test_a_sidecar_yields_the_digest_and_the_real_file_name():
    """``md5sum``'s format, which is what the publisher writes."""
    parsed = parse_sidecar(
        "8df49b25d6ab7775bb86961c3e407465  qwen3-asr-0.6b_bf16_seq1024_x.bmodel\n")
    assert parsed == ("8df49b25d6ab7775bb86961c3e407465",
                      "qwen3-asr-0.6b_bf16_seq1024_x.bmodel")


def test_a_sidecar_is_read_past_blank_lines_and_a_binary_marker():
    assert parse_sidecar("\n\n  1234567890abcdef1234567890abcdef *m.bmodel  \n") == (
        "1234567890abcdef1234567890abcdef", "m.bmodel")


def test_a_sidecar_without_a_digest_is_rejected():
    """Better no metadata than a digest of the wrong shape used as one."""
    assert parse_sidecar("") is None
    assert parse_sidecar("not a digest  m.bmodel") is None
    assert parse_sidecar("deadbeef  m.bmodel") is None  # too short to be md5


def test_a_sidecar_never_yields_a_path():
    """The name is used to locate a local file; a directory part would escape."""
    parsed = parse_sidecar("1234567890abcdef1234567890abcdef  ../../etc/passwd")
    assert parsed is not None and parsed[1] == "passwd"


# -- downloading one file by tag ------------------------------------------
async def test_a_tag_install_verifies_against_the_sidecar(tmp_path, monkeypatch):
    """The happy path: sidecar first, model second, digest checked, renamed in."""
    entry = _entry()
    body = b"model-bytes" * 100
    fake = FakeDfss({entry["dflag"]: ("real-name.bmodel", body)}).install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    # The *real* file name, not the one the catalogue guessed: a tag is how a
    # new build with a new name reaches a board that never heard of it.
    assert (tmp_path / "models" / entry["id"] / "real-name.bmodel").read_bytes() == body
    assert "标签" in job.message and "md5 校验通过" in job.message
    assert job.transport == "dflag"
    # The sidecar was fetched before the model, from the tag's own name.
    assert fake.calls[0] == ("flag", entry["dflag"] + DFLAG_MD5_SUFFIX)
    assert fake.calls[1] == ("flag", entry["dflag"])


async def test_a_digest_mismatch_installs_nothing(tmp_path, monkeypatch):
    """A tag that serves a truncated file must not become a model."""
    entry = _entry()
    body = b"good" * 100
    fake = FakeDfss({entry["dflag"]: ("m.bmodel", body)}).install(monkeypatch)

    # The sidecar declares the truth; make the *catalogue* disagree, which is
    # the case where the two sources have drifted.
    entry["md5"] = hashlib.md5(b"something else").hexdigest()
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    # Force the tool to a version where the sidecar is not fetched, so this is
    # the catalogue-digest path specifically.
    monkeypatch.setattr(dl, "_fetch_sidecar",
                        _no_sidecar)
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "md5 不匹配" in job.message
    assert not (tmp_path / "models" / entry["id"]).exists()
    assert not (tmp_path / "staging" / job.id).exists()
    assert dm.active_names() == set()


async def _no_sidecar(*_a, **_kw):
    return None


async def test_a_tag_that_serves_a_different_name_than_its_sidecar_is_refused(
        tmp_path, monkeypatch):
    """The index moved between the two requests: neither file is trustworthy.

    Installing the model while checking it against the other build's digest
    would either fail (best case) or, if the two happened to be the same size,
    install a build nobody verified.
    """
    entry = _entry()
    body = b"x" * 64
    fake = FakeDfss({entry["dflag"]: ("m.bmodel", body)}).install(monkeypatch)

    async def lying_sidecar(tag, scratch, on_line):
        return hashlib.md5(body).hexdigest(), "a-different-name.bmodel"

    monkeypatch.setattr(dl, "_fetch_sidecar", lying_sidecar)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "标签可能在下载过程中被改动" in job.message
    assert not (tmp_path / "models" / entry["id"]).exists()


async def test_a_missing_sidecar_falls_back_to_the_catalogue_digest(tmp_path, monkeypatch):
    """The sidecar is an upgrade over the catalogue, not a requirement.

    A publisher who uploaded the model and not the metadata must still get a
    working download -- verified by the digest this release declares.
    """
    entry = _entry()
    body = b"y" * 128
    _with_digest(entry, body)
    # The model tag resolves, the sidecar tag does not.
    fake = FakeDfss({entry["dflag"]: ("m.bmodel", body)},
                    fail_tags={entry["dflag"] + DFLAG_MD5_SUFFIX}).install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert (tmp_path / "models" / entry["id"] / "m.bmodel").read_bytes() == body
    assert ("flag", entry["dflag"] + DFLAG_MD5_SUFFIX) in fake.calls


async def test_a_missing_sidecar_and_no_catalogue_digest_refuses_the_file(tmp_path, monkeypatch):
    """No digest from either source is no verification at all.

    A 1.5 GB bmodel installed on trust is the failure mode every other check
    here exists to prevent.
    """
    entry = _entry()
    entry["md5"] = None
    body = b"z" * 32
    FakeDfss({entry["dflag"]: ("m.bmodel", body)},
             fail_tags={entry["dflag"] + DFLAG_MD5_SUFFIX}).install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "无法校验" in job.message
    assert not (tmp_path / "models" / entry["id"]).exists()


# -- the fallback ----------------------------------------------------------
async def test_an_unknown_tag_falls_back_to_the_fixed_url(tmp_path, monkeypatch):
    """A server without the tag must not cost the operator a download.

    And the job message has to say so: "标签不可用，已使用固定地址" is the
    difference between an operator wondering why an upgrade is not happening
    and knowing the server never published the tag.
    """
    entry = _entry()
    body = b"f" * 200
    _with_digest(entry, body)
    # The URL path serves the catalogue's file name; the tag resolves to nothing.
    fake = FakeDfss({}, fail_tags={entry["dflag"], entry["dflag"] + DFLAG_MD5_SUFFIX})
    fake.tags = {"placeholder": (entry["dfss"].rsplit("/", 1)[-1], body)}
    fake.install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert "标签不可用" in job.message and "固定地址" in job.message
    assert job.transport == "dfss"
    assert ("url", entry["dfss"]) in fake.calls


async def test_a_dfss_without_dflag_never_attempts_a_tag(tmp_path, monkeypatch):
    """An old tool (1.10.8 and earlier) would reject the option outright."""
    entry = _entry()
    body = b"g" * 50
    _with_digest(entry, body)
    fake = FakeDfss({}, support_dflag=False)
    fake.tags = {"placeholder": (entry["dfss"].rsplit("/", 1)[-1], body)}
    fake.install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert all(kind == "url" for kind, _ in fake.calls), fake.calls
    assert "标签不可用" in job.message


async def test_a_tag_that_fails_mid_transfer_falls_back_to_the_fixed_url(tmp_path, monkeypatch):
    """Every non-zero exit is "the tag did not work", so fall back.

    The card lists three causes -- an old dfss, a tag the server does not have,
    a network problem -- and a transfer that dies halfway (a full disk, a route
    that dropped) is the same situation from the download's point of view: the
    tag produced nothing usable. The fixed URL can still complete the install,
    so refusing it would turn a recoverable transport problem into a failed
    download. Only a file that *did* arrive and then failed verification is an
    error (see the digest and name tests).
    """
    entry = _entry()
    body = b"h" * 64
    _with_digest(entry, body)
    fake = FakeDfss({entry["dflag"]: ("m.bmodel", body)}).install(monkeypatch)

    async def broken(tag, dest_dir, on_line=None):
        if tag == entry["dflag"]:
            # A truncated file is left behind on purpose: the fallback must not
            # be able to mistake it for the file the URL download produces.
            (Path(dest_dir) / "m.bmodel").write_bytes(b"half")
            return 1, ["ERROR main.cpp:1300: write failed (No space left on device)"]
        return await fake.run_flag(tag, dest_dir, on_line)

    monkeypatch.setattr(dl, "run_dfss_flag", broken)
    # The fixed URL serves the catalogue's own file name.
    url_name = entry["dfss"].rsplit("/", 1)[-1]
    fake.tags[entry["dflag"]] = (url_name, body)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert "标签不可用" in job.message and "固定地址" in job.message
    assert job.transport == "dfss"
    assert ("url", entry["dfss"]) in fake.calls
    # The truncated file from the failed attempt was not installed.
    assert (tmp_path / "models" / entry["id"] / url_name).read_bytes() == body


async def test_a_tag_that_fails_on_a_disk_that_fills_falls_back(tmp_path, monkeypatch):
    """The same rule for a failure with no output at all (exit 65280 and friends)."""
    entry = _entry()
    body = b"k" * 32
    _with_digest(entry, body)
    fake = FakeDfss({entry["dflag"]: ("m.bmodel", body)},
                    fail_tags={entry["dflag"], entry["dflag"] + DFLAG_MD5_SUFFIX})
    url_name = entry["dfss"].rsplit("/", 1)[-1]
    fake.tags["placeholder"] = (url_name, body)
    fake.install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert job.transport == "dfss"
    assert "标签不可用" in job.message


# -- multi-file entries ---------------------------------------------------
#: How many bmodels ``ppocrv6-medium`` ships: det + three rec tiers + the
#: PP-DocLayout-M segmenter that ``mode: "layout"`` needs. Named rather than
#: spelled as a literal in three tests so adding a sixth file is one edit, and
#: so a reader sees *what* the count is counting.
OCR_FILE_COUNT = 5


async def test_every_file_of_an_ocr_entry_goes_through_its_own_tag(tmp_path, monkeypatch):
    """Every bmodel of the OCR model has its own tag: one job, no bare URL."""
    entry = _entry("ppocrv6-medium")
    files = catalog_file_set(entry)
    assert len(files) == OCR_FILE_COUNT and all(f["dflag"] for f in files)
    tags = {f["dflag"]: (f"served-{i}.bmodel".replace("served", "m"), b"body-%d" % i)
            for i, f in enumerate(files)}
    FakeDfss(tags).install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=files)
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    installed = sorted(p.name for p in (tmp_path / "models" / entry["id"]).iterdir())
    assert installed == sorted(name for name, _ in tags.values())
    assert job.public()["file_count"] == OCR_FILE_COUNT
    assert job.public()["files_done"] == OCR_FILE_COUNT
    assert job.transport == "dflag"


async def test_one_unusable_tag_does_not_stop_the_others(tmp_path, monkeypatch):
    """Per-file fallback, reported as partial: three tags, one fixed URL."""
    entry = _entry("ppocrv6-medium")
    files = catalog_file_set(entry)
    tags = {f["dflag"]: (f"m{i}.bmodel", b"body-%d" % i) for i, f in enumerate(files)}
    dead = files[2]["dflag"]
    fake = FakeDfss(tags, fail_tags={dead}).install(monkeypatch)
    # The URL path has to be able to serve the missing one for the job to finish.
    fake.tags[dead] = (files[2]["dfss"].rsplit("/", 1)[-1], b"body-2")
    _with_digest(files[2], b"body-2")
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=files)
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert "部分文件标签不可用" in job.message


# -- the tag index --------------------------------------------------------
def test_the_index_maps_tags_to_the_file_name_they_point_at():
    flags = DfssFlags()
    flags.tags = {"a": "tools/x/model_v2.bmodel", "b": "tools/x/side.md5"}
    assert flags.tag_filename("a") == "model_v2.bmodel"
    assert flags.tag_filename("missing") is None


async def test_a_refresh_populates_the_cache_and_is_reused(tmp_path, monkeypatch):
    """Ten minutes of cache: the index cannot change faster than the server scans."""
    flags = DfssFlags(ttl_s=600)
    calls = []

    async def fake_run(target, dest_dir, on_line=None, bootstrap=True):
        calls.append(target)
        (Path(dest_dir) / ".dfss_flags").write_text(json.dumps(
            {"t": {"filepath": "tools/x/m.bmodel"}}))
        return 0, ["ok"]

    monkeypatch.setattr(dl, "run_dfss", fake_run)
    assert await flags.refresh() == {"t": "tools/x/m.bmodel"}
    assert await flags.refresh() == {"t": "tools/x/m.bmodel"}
    assert len(calls) == 1, "the second read must come from the cache"
    assert flags.fresh()
    # force=True is what the background refresher uses.
    await flags.refresh(force=True)
    assert len(calls) == 2


async def test_an_offline_board_keeps_the_catalogue_working(tmp_path, monkeypatch):
    """A failed refresh is recorded, not raised: the page must still render."""
    flags = DfssFlags()

    async def dead_run(target, dest_dir, on_line=None, bootstrap=True):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(dl, "run_dfss", dead_run)
    assert await flags.refresh() == {}
    assert flags.error and "network unreachable" in flags.error
    # And a stale-but-present cache survives a failed refresh.
    flags.tags = {"t": "a/m.bmodel"}
    flags.fetched_at = -1e9
    assert await flags.refresh() == {"t": "a/m.bmodel"}


async def test_a_malformed_index_is_rejected_rather_than_half_read(tmp_path, monkeypatch):
    """A truncated JSON body must not be mistaken for "no tags"."""
    flags = DfssFlags()

    async def bad_run(target, dest_dir, on_line=None, bootstrap=True):
        (Path(dest_dir) / ".dfss_flags").write_text('{"t": {"filepath": ')
        return 0, ["ok"]

    monkeypatch.setattr(dl, "run_dfss", bad_run)
    assert await flags.refresh() == {}
    assert flags.error


def test_the_terminal_download_does_not_wait_for_the_index():
    """``schedule_refresh`` returns the cache immediately, always.

    The catalogue route calls it on every page load; making it await the
    download is what would turn a dead dfss route into a hanging console.
    """
    flags = DfssFlags()
    flags.tags = {"t": "a/m.bmodel"}
    flags.fetched_at = 1e18  # fresh
    assert flags.schedule_refresh() == {"t": "a/m.bmodel"}


# -- "有新版本" ------------------------------------------------------------
def _installed(tmp_path: Path, model_id: str, *names: str) -> Path:
    directory = tmp_path / "models" / model_id
    directory.mkdir(parents=True)
    for name in names:
        (directory / name).write_bytes(b"x")
    return directory


def test_a_matching_name_is_up_to_date(tmp_path):
    entry = _entry("qwen3-asr-0.6b")
    directory = _installed(tmp_path, entry["id"], "m_v2.bmodel")
    flags = DfssFlags()
    flags.tags = {entry["dflag"]: "tools/x/m_v2.bmodel"}
    status = update_status(entry, directory, flags)
    assert status is not None
    assert status["update_available"] is False
    assert status["latest_file"] == "m_v2.bmodel"


def test_a_different_name_means_an_update(tmp_path):
    """The published name changed: the tag now points at a build we do not have."""
    entry = _entry("qwen3-asr-0.6b")
    directory = _installed(tmp_path, entry["id"], "m_v1.bmodel")
    flags = DfssFlags()
    flags.tags = {entry["dflag"]: "tools/x/m_v2.bmodel"}
    status = update_status(entry, directory, flags)
    assert status["update_available"] is True
    assert status["latest_file"] == "m_v2.bmodel"
    assert status["missing_files"] == ["m_v2.bmodel"]


def test_one_stale_file_of_a_set_means_an_update(tmp_path):
    """All but one current is still not the released build."""
    entry = _entry("ppocrv6-medium")
    files = catalog_file_set(entry)
    names = [f"a{i}.bmodel" for i in range(OCR_FILE_COUNT)]
    directory = _installed(tmp_path, entry["id"], *names[:-1])
    flags = DfssFlags()
    flags.tags = {f["dflag"]: f"tools/x/{name}"
                  for f, name in zip(files, names)}
    status = update_status(entry, directory, flags)
    assert status["update_available"] is True
    assert status["missing_files"] == [names[-1]]
    assert status["latest_files"] == names


def test_a_directory_missing_only_the_layout_model_reports_an_update(tmp_path):
    """The four-file installs already on boards must show "有新版本".

    This is the case the card asks to confirm: a device that installed
    ``ppocrv6-medium`` before layout mode existed holds det + three rec tiers
    and nothing else. The update check compares *names from the tag index*
    against the directory, so a directory that is missing the layout bmodel is
    stale by exactly that one file -- provided the tag index knows the tag,
    which is why the card makes uploading it a prerequisite.
    """
    entry = _entry("ppocrv6-medium")
    files = catalog_file_set(entry)
    layout_file = files[-1]
    assert layout_file["dflag"] == "cv84x6_llm_ppdoclayout-m"
    legacy = [f for f in files if f is not layout_file]
    directory = _installed(tmp_path, entry["id"],
                           *[f["dfss"].rsplit("/", 1)[-1] for f in legacy])
    flags = DfssFlags()
    flags.tags = {f["dflag"]: f"tools/cv84x6_llm_server/"
                              f"{f['dfss'].rsplit('/', 1)[-1]}"
                  for f in files}
    status = update_status(entry, directory, flags)
    assert status is not None
    assert status["update_available"] is True
    assert status["missing_files"] == [
        layout_file["dfss"].rsplit("/", 1)[-1]]


def test_no_index_means_no_claim(tmp_path):
    """None, not False: a check that could not run must not read as "up to date"."""
    entry = _entry("qwen3-asr-0.6b")
    directory = _installed(tmp_path, entry["id"], "m.bmodel")
    assert update_status(entry, directory, DfssFlags()) is None


def test_a_vendor_entry_without_a_tag_is_not_checked(tmp_path):
    """The reranker is still the vendor's file; there is no tag to compare.

    The embedding model used to be the example here too. Since MYS-2696 it is
    our own build (seq2048), published under /tools/ with a tag, so it is the
    reranker -- and only the reranker -- that still exercises this path.
    """
    entry = _entry("bge-reranker-v2-m3")
    assert "dflag" not in entry
    directory = _installed(tmp_path, entry["id"], "m.bmodel")
    flags = DfssFlags()
    flags.tags = {"cv84x6_llm_unrelated": "x/y.bmodel"}
    assert update_status(entry, directory, flags) is None


def test_the_embedding_model_is_now_offered_as_an_update(tmp_path):
    """A board holding the seq8192 build sees "有新版本" for the seq2048 one.

    This is the MYS-2696 upgrade path end to end at the catalogue level: the
    entry carries a tag, the tag names a file the board does not have, and
    ``update_status`` reports it. Before this change the entry had no tag at all
    (it was the vendor's file), so an installed board could never be offered the
    new build.
    """
    entry = _entry("qwen3-embedding-0.6b")
    assert entry["dflag"] == "cv84x6_llm_qwen3-embedding-0.6b"
    installed = "qwen3-embedding-0.6b_bf16_seq8192_bm1684x2_4core_static_20260920_184312.bmodel"
    directory = _installed(tmp_path, entry["id"], installed)
    flags = DfssFlags()
    flags.tags = {
        entry["dflag"]:
            "tools/cv84x6_llm_server/"
            "qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel",
    }
    status = update_status(entry, directory, flags)
    assert status is not None, "the new build must be offered"
    assert status["update_available"] is True, status


def test_a_tag_the_index_does_not_know_is_not_a_verdict(tmp_path):
    """A tag still being scanned must not make every board report an update."""
    entry = _entry("qwen3-asr-0.6b")
    directory = _installed(tmp_path, entry["id"], "m.bmodel")
    flags = DfssFlags()
    flags.tags = {"some-other-tag": "a/m.bmodel"}
    assert update_status(entry, directory, flags) is None


# -- the seq512 short-text档 is a second entry, not an update to the first ---
def test_the_two_embedding_builds_have_separate_tags(tmp_path):
    """Repointing one tag must not move a board onto the other build.

    The seq512 档 (MYS-2706) is *optional*, and the failure this guards against
    is specific: sharing the seq2048 tag would make every board that presses
    "有新版本" silently swap its embedding model for the shorter graph, which
    turns every 1000-character chunk into a split-and-pool. Two tags, two
    entries, and neither is an update of the other.
    """
    long_entry = _entry("qwen3-embedding-0.6b")
    short_entry = _entry("qwen3-embedding-0.6b-seq512")
    assert long_entry["dflag"] == "cv84x6_llm_qwen3-embedding-0.6b"
    assert short_entry["dflag"] == "cv84x6_llm_qwen3-embedding-0.6b-seq512"
    assert long_entry["dflag"] != short_entry["dflag"]

    # A board holding the seq2048 build, with the index naming exactly that file
    # for its own tag, is up to date -- the seq512 tag is not consulted at all
    # (``update_status`` reads the entry's own tags only).
    directory = _installed(tmp_path, long_entry["id"],
                           "qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel")
    flags = DfssFlags()
    flags.tags = {
        long_entry["dflag"]:
            "tools/cv84x6_llm_server/"
            "qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel",
        short_entry["dflag"]:
            "tools/cv84x6_llm_server/"
            "qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel",
    }
    status = update_status(long_entry, directory, flags)
    assert status is not None
    assert status["update_available"] is False, (
        "the sibling build must not read as an update")
    assert "seq512" not in (status["latest_file"] or "")


# -- one-click update -----------------------------------------------------
async def _installed_entry(tmp_path: Path, model_id: str = "qwen3-asr-0.6b"):
    """An installed model holding the old build, plus the entry for it."""
    entry = _entry(model_id)
    old_name = "old-build.bmodel"
    _installed(tmp_path, model_id, old_name)
    return entry, tmp_path / "models" / model_id / old_name


async def test_an_update_replaces_the_old_build(tmp_path, monkeypatch):
    """The directory must end up holding one build, not two.

    Two bmodels side by side is a directory ``discover_models`` resolves by
    name -- so which weights load would depend on spelling.
    """
    entry, old = await _installed_entry(tmp_path)
    new_body = b"n" * 256
    FakeDfss({entry["dflag"]: ("new-build.bmodel", new_body)}).install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_update(entry)
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    directory = tmp_path / "models" / entry["id"]
    assert sorted(p.name for p in directory.iterdir()) == ["new-build.bmodel"]
    assert (directory / "new-build.bmodel").read_bytes() == new_body
    assert not old.exists()
    assert "已删除旧文件" in job.message


async def test_a_failed_update_leaves_the_installed_build_alone(tmp_path, monkeypatch):
    """The old model is still the model: no half-upgraded directory."""
    entry, old = await _installed_entry(tmp_path)
    body = b"q" * 64
    _with_digest(entry, body)
    fake = FakeDfss({entry["dflag"]: ("new-build.bmodel", body)},
                    fail_tags={entry["dflag"], entry["dflag"] + DFLAG_MD5_SUFFIX})
    fake.install(monkeypatch)
    # And the fixed URL is dead too, so nothing can arrive.
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_update(entry)
    await dm._tasks[job.id]

    assert job.state == "error"
    assert old.read_bytes() == b"x"
    assert sorted(p.name for p in old.parent.iterdir()) == ["old-build.bmodel"]
    assert dm.active_names() == set()


async def test_an_update_is_locked_while_it_runs(tmp_path, monkeypatch):
    """The download lock is what keeps a load off the file being swapped."""
    entry, _old = await _installed_entry(tmp_path)
    release = asyncio.Event()
    entered = asyncio.Event()

    async def slow_flag(tag, dest_dir, on_line=None):
        entered.set()
        await release.wait()
        if tag.endswith(DFLAG_MD5_SUFFIX):
            (Path(dest_dir) / "new-build.bmodel.md5").write_text(
                f"{hashlib.md5(b'n').hexdigest()}  new-build.bmodel\n")
        else:
            (Path(dest_dir) / "new-build.bmodel").write_bytes(b"n")
        return 0, ["ok"]

    async def ensure(on_line=None, **_kw):
        return None

    monkeypatch.setattr(dl, "ensure_dfss", ensure)
    monkeypatch.setattr(dl, "run_dfss_flag", slow_flag)
    monkeypatch.setattr(dl, "dfss_dflag_supported", lambda python=None: True)

    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_update(entry)
    await asyncio.wait_for(entered.wait(), 5)
    assert dm.active_names() == {entry["id"]}
    assert dm.get(job.id).state in ("pending", "running")
    release.set()
    await dm._tasks[job.id]
    assert job.state == "done", job.message
    assert dm.active_names() == set()


def test_an_entry_without_a_tag_cannot_be_updated(tmp_path):
    """A vendor model has nothing to update *to*; say so rather than 500.

    The reranker, not the embedding model: see the test above for why.
    """
    entry = _entry("bge-reranker-v2-m3")
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    with pytest.raises(ValueError) as excinfo:
        dm.start_update(entry)
    assert "下载标签" in str(excinfo.value)
    assert dm.list() == []


# -- the API ---------------------------------------------------------------
def _app(tmp_path, monkeypatch):
    from app.main import create_app

    app = create_app(data_dir=tmp_path / "data", models_dir=tmp_path / "models",
                     backend_kind="mock", web_dir=tmp_path / "web")
    return app


def _login(client):
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200


def test_the_catalogue_reports_an_available_update(tmp_path, monkeypatch):
    """End to end: the tag moved, the board notices on the catalogue page."""
    from fastapi.testclient import TestClient

    models = tmp_path / "models"
    _installed(tmp_path, "qwen3-asr-0.6b", "old-build.bmodel")
    entry = _entry("qwen3-asr-0.6b")
    app = _app(tmp_path, monkeypatch)
    app.state.downloads.flags.tags = {entry["dflag"]: "tools/x/new-build.bmodel"}
    app.state.downloads.flags.fetched_at = 1e18  # fresh, so nothing is fetched
    with TestClient(app) as client:
        _login(client)
        rows = {r["id"]: r for r in client.get("/api/catalog").json()["models"]}
    row = rows["qwen3-asr-0.6b"]
    assert row["installed"] is True
    assert row["update_available"] is True
    assert row["latest_file"] == "new-build.bmodel"


def test_the_catalogue_says_nothing_when_it_cannot_check(tmp_path, monkeypatch):
    """No index -> the field is absent, not ``false``.

    A row claiming "up to date" because the network was down is worse than a
    row saying nothing at all.
    """
    from fastapi.testclient import TestClient

    _installed(tmp_path, "qwen3-asr-0.6b", "m.bmodel")
    app = _app(tmp_path, monkeypatch)

    async def dead(target, dest_dir, on_line=None, bootstrap=True):
        raise RuntimeError("offline")

    monkeypatch.setattr(dl, "run_dfss", dead)
    with TestClient(app) as client:
        _login(client)
        rows = {r["id"]: r for r in client.get("/api/catalog").json()["models"]}
    row = rows["qwen3-asr-0.6b"]
    assert "update_available" not in row
    assert "latest_file" not in row
    # And the page answered rather than failing.
    assert row["installed"] is True


def test_updating_a_loaded_model_is_refused_with_409(tmp_path, monkeypatch):
    """A worker has the bmodel mapped; replacing it is corruption, not upgrade."""
    from fastapi.testclient import TestClient

    _installed(tmp_path, "qwen3-asr-0.6b", "m.bmodel")
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _login(client)
        app.state.models.refresh()
        info = app.state.models.get("qwen3-asr-0.6b")
        info.loaded = True
        info.operation = "loading"
        r = client.post("/api/models/qwen3-asr-0.6b/update")
        assert r.status_code == 409, r.text
        assert "卸载" in r.json()["detail"]


def test_updating_a_model_that_is_not_on_disk_is_404(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _login(client)
        r = client.post("/api/models/qwen3-asr-0.6b/update")
        assert r.status_code == 404


def test_updating_a_model_outside_the_catalogue_is_400(tmp_path, monkeypatch):
    """An operator's hand-imported model has no tag, so there is nothing to fetch."""
    from fastapi.testclient import TestClient

    _installed(tmp_path, "my-own-model", "m.bmodel")
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _login(client)
        app.state.models.refresh()
        r = client.post("/api/models/my-own-model/update")
        assert r.status_code == 400, r.text
        assert "下载目录" in r.json()["detail"]


def test_the_update_route_downloads_and_swaps(tmp_path, monkeypatch):
    """Through HTTP: the job is accepted, then the directory holds the new build."""
    from fastapi.testclient import TestClient

    entry = _entry("qwen3-asr-0.6b")
    _installed(tmp_path, entry["id"], "old-build.bmodel")
    old = tmp_path / "models" / entry["id"] / "old-build.bmodel"
    new_body = b"z" * 512
    FakeDfss({entry["dflag"]: ("new-build.bmodel", new_body)}).install(monkeypatch)

    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        _login(client)
        app.state.models.refresh()
        r = client.post(f"/api/models/{entry['id']}/update")
        assert r.status_code == 200, r.text
        job_id = r.json()["job"]["id"]
        state = {}
        for _ in range(200):
            jobs = {j["id"]: j for j in client.get("/api/downloads").json()["jobs"]}
            state = jobs[job_id]
            if state["state"] in ("done", "error", "cancelled"):
                break
            import time as _time
            _time.sleep(0.02)
    assert state["state"] == "done", state["message"]
    directory = tmp_path / "models" / entry["id"]
    assert sorted(p.name for p in directory.iterdir()) == ["new-build.bmodel"]
    assert not old.exists()


# -- what the manager is told once the swap lands --------------------------
async def test_an_update_rescans_so_a_load_names_the_file_that_exists(tmp_path, monkeypatch):
    """The old name is gone; a manager still listing it would load nothing.

    Modelled on the real defect risk: ``ModelInfo.bmodel_files`` is what the
    worker's command line is built from, and it is refreshed by a scan. An
    update renames the file, so without a rescan a load in the window between
    the swap and the console's next poll hands the worker a deleted path.
    """
    entry, _old = await _installed_entry(tmp_path)
    FakeDfss({entry["dflag"]: ("new-build.bmodel", b"n" * 32)}).install(monkeypatch)
    rescanned: list[str] = []
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    dm.on_installed = rescanned.append
    job = dm.start_update(entry)
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert rescanned == [entry["id"]]


async def test_a_directory_that_vanishes_mid_update_is_not_resurrected(tmp_path, monkeypatch):
    """A model deleted while its upgrade downloads must stay deleted."""
    entry, _old = await _installed_entry(tmp_path)
    release = asyncio.Event()
    entered = asyncio.Event()

    async def slow_flag(tag, dest_dir, on_line=None):
        entered.set()
        await release.wait()
        if tag.endswith(DFLAG_MD5_SUFFIX):
            (Path(dest_dir) / "new-build.bmodel.md5").write_text(
                f"{hashlib.md5(b'n').hexdigest()}  new-build.bmodel\n")
        else:
            (Path(dest_dir) / "new-build.bmodel").write_bytes(b"n")
        return 0, ["ok"]

    async def ensure(on_line=None, **_kw):
        return None

    monkeypatch.setattr(dl, "ensure_dfss", ensure)
    monkeypatch.setattr(dl, "run_dfss_flag", slow_flag)
    monkeypatch.setattr(dl, "dfss_dflag_supported", lambda python=None: True)

    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_update(entry)
    await asyncio.wait_for(entered.wait(), 5)
    import shutil as _shutil
    _shutil.rmtree(tmp_path / "models" / entry["id"])
    release.set()
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "消失了" in job.message
    assert not (tmp_path / "models" / entry["id"]).exists()


# -- the event loop stays responsive while a digest is computed -------------
# A 20 GB bmodel takes over a minute to hash. The service runs one asyncio
# loop that also serves /api/catalog, the model status poll and every streamed
# generation in the other models, so a digest read inline is an outage for all
# of them -- not a slow page. These tests fail if any call site hashes inline.
async def test_a_digest_does_not_block_the_event_loop(tmp_path, monkeypatch):
    """While a large file is hashed, other coroutines keep running."""
    entry = _entry()
    body = b"b" * 1024
    FakeDfss({entry["dflag"]: ("m.bmodel", body)}).install(monkeypatch)

    import hashlib as _hashlib
    import threading
    import time as _time

    real_md5 = dl._md5_file

    def slow_md5(path, chunk=1 << 20):
        # A real read, then a deliberate pause in the worker thread: the point
        # is whether the loop is free while this runs, not the hash itself.
        _time.sleep(0.3)
        return real_md5(path, chunk)

    monkeypatch.setattr(dl, "_md5_file", slow_md5)

    ticks: list[float] = []

    async def ticker() -> None:
        while True:
            ticks.append(_time.monotonic())
            await asyncio.sleep(0.01)

    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    beat = asyncio.create_task(ticker())
    try:
        job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
        await dm._tasks[job.id]
    finally:
        beat.cancel()
        try:
            await beat
        except asyncio.CancelledError:
            pass

    assert job.state == "done", job.message
    # Measured against the 0.3 s the hash took: an inline hash would let exactly
    # zero ticks through during it.
    assert len(ticks) >= 10, f"the loop only ran {len(ticks)} times while hashing"
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert max(gaps) < 0.25, f"a {max(gaps):.2f}s stall means the hash ran inline"


async def test_the_hash_itself_runs_off_the_loop_thread(tmp_path):
    """``md5_file_async`` is a thread hop, not a coroutine that pretends to be one."""
    import threading

    target = tmp_path / "m.bmodel"
    target.write_bytes(b"payload")
    caller = threading.get_ident()
    seen: list[int] = []
    real = dl._md5_file

    def recording(path, chunk=1 << 20):
        seen.append(threading.get_ident())
        return real(path, chunk)

    dl._md5_file = recording
    try:
        digest = await dl.md5_file_async(target)
    finally:
        dl._md5_file = real
    assert digest == hashlib.md5(b"payload").hexdigest()
    assert seen and seen[0] != caller, "the digest ran on the event loop thread"



# -- an upgrade never falls back to the fixed URL --------------------------
# The fixed URL is this release's address for a file. An update asks a
# different question -- "what does the tag serve *now*" -- so answering it with
# the fixed URL can install the build that is already there and, when the
# installed copy is newer than this release knew about, replace it with an older
# one. The job must fail with that said, and the disk must not move.
async def test_an_update_refuses_the_fixed_url_and_keeps_the_installed_build(
        tmp_path, monkeypatch):
    entry, old = await _installed_entry(tmp_path)
    body = b"old-build-bytes"
    _with_digest(entry, body)
    # The tag is gone from the server; the fixed URL still serves the release's
    # file -- which is exactly the trap.
    fake = FakeDfss({}, fail_tags={entry["dflag"], entry["dflag"] + DFLAG_MD5_SUFFIX})
    fake.tags = {"placeholder": (entry["dfss"].rsplit("/", 1)[-1], body)}
    fake.install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_update(entry)
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "无法更新" in job.message
    assert "固定地址" in job.message
    # Nothing was downloaded over the URL, and the old file is untouched.
    assert ("url", entry["dfss"]) not in fake.calls
    assert old.read_bytes() == b"x"
    assert sorted(p.name for p in old.parent.iterdir()) == ["old-build.bmodel"]


async def test_an_update_does_not_downgrade_a_newer_installed_build(
        tmp_path, monkeypatch):
    """The bad outcome this rule exists for: newest on disk, tag unreachable.

    Without the refusal the Upgrade step would download the fixed URL's older
    file, delete the newer one, report success, and the catalogue would go on
    saying ``update_available`` -- the board losing bytes it already had.
    """
    entry = _entry()
    newer = "build-20261104.bmodel"
    directory = _installed(tmp_path, entry["id"], newer)
    older = entry["dfss"].rsplit("/", 1)[-1]
    fake = FakeDfss({}, fail_tags={entry["dflag"], entry["dflag"] + DFLAG_MD5_SUFFIX})
    fake.tags = {"placeholder": (older, b"older")}
    fake.install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_update(entry)
    await dm._tasks[job.id]

    assert job.state == "error"
    # Refused as "cannot update", not as a digest mismatch: the point is that
    # the older file was never fetched, so the message must not be about it.
    assert "无法更新" in job.message
    assert ("url", entry["dfss"]) not in fake.calls
    assert sorted(p.name for p in directory.iterdir()) == [newer]


async def test_a_partial_tag_outage_stops_the_whole_update(tmp_path, monkeypatch):
    """One file without a tag is enough: a mixed set is not a released build."""
    entry = _entry("ppocrv6-medium")
    files = catalog_file_set(entry)
    directory = _installed(tmp_path, entry["id"], "stale-det.bmodel")
    tags = {files[0]["dflag"]: ("new-det.bmodel", b"d"),
            files[1]["dflag"]: ("new-rec320.bmodel", b"r"),
            files[2]["dflag"]: ("new-rec640.bmodel", b"r"),
            files[3]["dflag"]: ("new-rec1600.bmodel", b"r")}
    fake = FakeDfss(tags, fail_tags={files[2]["dflag"]})
    for f in files:
        fake.tags.setdefault(f["dfss"].rsplit("/", 1)[-1], ("unused", b""))
    fake.install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_update(entry)
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "无法更新" in job.message
    # The half-fetched files went with the staging directory, not into models/.
    assert sorted(p.name for p in directory.iterdir()) == ["stale-det.bmodel"]
    assert dm.active_names() == set()


# -- a plain download onto an installed model replaces it ------------------
async def test_a_download_onto_an_older_build_replaces_it(tmp_path, monkeypatch):
    """Clicking download after the tag moved must not leave two builds.

    ``discover_models`` resolves a directory by file name, so the old build
    sitting beside the new one means the loader runs the old weights while the
    console is told the download succeeded -- and ``update_available`` stays
    true for the file that was just fetched.
    """
    entry = _entry()
    directory = _installed(tmp_path, entry["id"], "old-build.bmodel")
    new_body = b"n" * 128
    FakeDfss({entry["dflag"]: ("new-build.bmodel", new_body)}).install(monkeypatch)
    rescanned: list[str] = []
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    dm.on_installed = rescanned.append
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert sorted(p.name for p in directory.iterdir()) == ["new-build.bmodel"]
    assert (directory / "new-build.bmodel").read_bytes() == new_body
    assert "已替换旧文件 old-build.bmodel" in job.message
    assert rescanned == [entry["id"]], "the renamed bmodel needs a rescan"


async def test_a_download_keeps_what_is_not_a_bmodel(tmp_path, monkeypatch):
    """A tokenizer or config directory beside the bmodel is the operator's."""
    entry = _entry()
    directory = _installed(tmp_path, entry["id"], "old-build.bmodel")
    (directory / "tokenizer_config.json").write_text("{}")
    (directory / "sub").mkdir()
    (directory / "sub" / "chat_template.jinja").write_text("x")
    FakeDfss({entry["dflag"]: ("new-build.bmodel", b"n")}).install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert (directory / "tokenizer_config.json").is_file()
    assert (directory / "sub" / "chat_template.jinja").is_file()
    assert sorted(p.name for p in directory.glob("*.bmodel")) == ["new-build.bmodel"]


async def test_a_first_install_replaces_nothing_and_says_nothing(
        tmp_path, monkeypatch):
    """The replacement branch must be silent when the directory was empty."""
    entry = _entry()
    FakeDfss({entry["dflag"]: ("new-build.bmodel", b"n")}).install(monkeypatch)
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    job = dm.start_dfss(entry["dfss"], entry["id"], files=[entry])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert "已替换旧文件" not in job.message


def test_a_failed_exdev_copy_leaves_no_part_file(tmp_path, monkeypatch):
    """An interrupted cross-filesystem install must not litter models/<id>/.

    The ``.part`` is created inside the model directory, not in the staging
    tree that the job's cleanup removes, so nothing else would ever delete it.
    """
    entry = _entry()
    dm = DownloadManager(tmp_path / "models", tmp_path / "staging")
    source = tmp_path / "staging-file.bmodel"
    source.write_bytes(b"x")
    job = dl.DownloadJob(id="j", kind="dfss", target="t", name=entry["id"])
    dm.jobs[job.id] = job

    def no_space(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(dl.shutil, "copyfile", no_space)
    real_replace = os.replace

    def replace(src, dst):
        if str(src).endswith(".part"):
            # The rename into place is the one that would have made the copy
            # atomic; it never happens, so the .part is the only trace.
            raise OSError(errno.EIO, "Input/output error")
        # Staging on another filesystem: the direct rename cannot work.
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(dl.os, "replace", replace)
    with pytest.raises(OSError):
        dm._install(job, source)
    directory = tmp_path / "models" / entry["id"]
    assert list(directory.iterdir()) == [], "the .part file was left behind"
    # And the source file is still in staging, where the job's cleanup finds it.
    assert source.exists()


# -- the index refresh is cheap when it fails ------------------------------
async def test_a_failed_refresh_is_not_retried_on_every_poll(tmp_path, monkeypatch):
    """An offline board must not run dfss behind every catalogue page load."""
    flags = DfssFlags(ttl_s=600, retry_ttl_s=2.0)
    calls: list[str] = []

    async def dead(target, dest_dir, on_line=None, bootstrap=True):
        calls.append(target)
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(dl, "run_dfss", dead)
    for _ in range(5):
        assert await flags.refresh() == {}
    assert len(calls) == 1, f"the failure was retried {len(calls)} times"

    # Once the retry TTL passes, one more attempt is made -- and still no more.
    flags.failed_at -= 3.0
    await flags.refresh()
    assert len(calls) == 2
    await flags.refresh()
    assert len(calls) == 2


async def test_an_empty_index_is_cached_too(tmp_path, monkeypatch):
    """A server with no tags is an answer, not a failure to retry forever."""
    flags = DfssFlags()
    calls: list[str] = []

    async def empty(target, dest_dir, on_line=None, bootstrap=True):
        calls.append(target)
        (Path(dest_dir) / ".dfss_flags").write_text("{}")
        return 0, ["ok"]

    monkeypatch.setattr(dl, "run_dfss", empty)
    assert await flags.refresh() == {}
    assert flags.fresh()
    assert await flags.refresh() == {}
    assert len(calls) == 1


async def test_the_index_refresh_never_installs_dfss(tmp_path, monkeypatch):
    """Refresh runs behind a console page; pip is minutes the page cannot spend."""
    flags = DfssFlags()
    seen: list[bool] = []

    async def record(target, dest_dir, on_line=None, bootstrap=True):
        seen.append(bootstrap)
        raise RuntimeError("no dfss here")

    monkeypatch.setattr(dl, "run_dfss", record)
    await flags.refresh()
    assert seen == [False]
    assert flags.error, "a refresh that could not run must say so"


# -- cancelled subprocesses do not become orphans --------------------------
async def test_a_cancelled_help_probe_kills_its_process(tmp_path, monkeypatch):
    """``wait_for`` cancelling the probe must not leave the interpreter running."""
    killed: list[int] = []

    class SlowProc:
        pid = 4242
        returncode = None

        async def communicate(self):
            await asyncio.sleep(3600)

        async def wait(self):
            return 0

        def kill(self):
            killed.append(self.pid)

    async def fake_exec(*_a, **_kw):
        return SlowProc()

    monkeypatch.setattr(dl.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(dl, "_terminate_tree", _record_termination(killed))
    task = asyncio.create_task(dl._dfss_help("/usr/bin/python3"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert killed, "the probe was left running after cancellation"


def _record_termination(killed: list[int]):
    async def terminate(proc):
        killed.append(proc.pid)
    return terminate
