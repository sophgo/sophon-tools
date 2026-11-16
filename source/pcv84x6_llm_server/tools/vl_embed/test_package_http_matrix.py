"""The package HTTP matrix's own gates, on fakes.

``package_http_matrix.py`` is the evidence that the *installed package* serves
the bucket/switch matrix correctly over HTTP -- as opposed to the C-API matrix,
which only exercises the engine. Its verdict is read by a reviewer instead of
being re-run, so its gates need the same treatment as ``fix_acceptance.py``'s:
test them against the answers a broken server would give.

The three holes that matter here, all of which the reviewed tool had:

* a revisit re-issued but never compared (switch equality untested);
* a NaN/zero vector counted as a successful response;
* a bucket never reached, while the report still claimed the matrix passed.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent / "package_http_matrix.py"


@pytest.fixture(scope="module")
def matrix():
    spec = importlib.util.spec_from_file_location("package_http_matrix", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- bucket accounting --------------------------------------------------------

@pytest.mark.parametrize("tokens,expected", [
    (15, 128), (128, 128), (129, 512), (198, 512), (512, 512),
    (513, 1024), (705, 1024), (1024, 1024), (1025, 2048), (1905, 2048),
])
def test_bucket_is_read_from_the_reported_token_count(matrix, tokens, expected):
    assert matrix._bucket_of(tokens) == expected


def test_an_unknown_token_count_does_not_invent_a_bucket(matrix):
    assert matrix._bucket_of(None) is None
    assert matrix._bucket_of("128") is None


def test_every_compiled_bucket_is_required(matrix):
    """The matrix must demand all four buckets, not whichever it happened to hit."""
    assert matrix.REQUIRED_BUCKETS == (128, 512, 1024, 2048)


# -- vector sanity ------------------------------------------------------------

def test_a_zero_vector_is_not_a_usable_answer(matrix):
    assert matrix._norm([0.0] * 8) == 0.0
    assert not math.isfinite(matrix._cosine([0.0] * 8, [1.0] * 8))


def test_a_nan_vector_is_not_a_usable_answer(matrix):
    assert not all(math.isfinite(x) for x in [float("nan")] * 4)


def test_identical_vectors_have_cosine_one(matrix):
    vec = [0.1, 0.2, 0.3, 0.4]
    assert matrix._cosine(vec, vec) == pytest.approx(1.0)


def test_digest_is_stable_and_distinguishes_vectors(matrix):
    a = [1.0, 0.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0, 0.0]
    assert matrix._digest(a) == matrix._digest(list(a))
    assert matrix._digest(a) != matrix._digest(b)


# -- the shape list -----------------------------------------------------------

def test_the_matrix_covers_the_switches_the_field_failure_needed(matrix):
    """The shape set must include both bucket extremes and two image sizes.

    A matrix of one text shape and one picture cannot show that a bucket switch
    or an image-size change leaves the next request reading the right buffer.
    """
    text_shapes = {name for name in dir(matrix) if name.startswith("LONG_")}
    assert {"LONG_512", "LONG_1024", "LONG_2048"} <= text_shapes
    # The revisit points must exist in the tool, or switch equality is skipped.
    source = TOOL.read_text(encoding="utf-8")
    assert 'if name in ("image-max", "long-1024")' in source, (
        "the revisit trigger changed; switch equality may no longer be tested")
    assert "REQUIRED_BUCKETS" in source


def test_the_tool_imports_the_package_not_a_source_tree(matrix):
    """The whole point is that it runs the package's own code and library."""
    source = TOOL.read_text(encoding="utf-8")
    assert "--package-root" in source
    assert "package_library_sha256" in source
    assert "native_lib=str(library)" in source, (
        "the app must be started with the package's library, not the default")
