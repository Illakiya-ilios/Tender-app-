"""Property-based tests for ``tender_app.evaluation.intake`` (zip-slip safety)."""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tender_app.evaluation import intake


# ---------------------------------------------------------------------------
# Strategies for hostile zip entry names.
# ---------------------------------------------------------------------------

# A safe path component: no separators, no traversal, no NUL.
_safe_component = st.text(
    alphabet=st.characters(
        min_codepoint=48,
        max_codepoint=122,
        whitelist_categories=("Ll", "Lu", "Nd"),
    ),
    min_size=1,
    max_size=8,
)


def _nested_name(parts: list[str]) -> str:
    return "/".join(parts)


# Normal, well-behaved relative entry names (possibly nested).
normal_names = st.lists(_safe_component, min_size=1, max_size=3).map(_nested_name)

# Names with one or more leading "../" traversal segments.
traversal_names = st.builds(
    lambda depth, parts: "../" * depth + _nested_name(parts),
    st.integers(min_value=1, max_value=4),
    st.lists(_safe_component, min_size=1, max_size=2),
)

# Absolute-style names (posix root and Windows drive/backslash).
absolute_names = st.sampled_from(
    [
        "/etc/passwd",
        "/tmp/evil.txt",
        "/evil.txt",
        "C:\\evil.txt",
        "C:\\Windows\\system32\\evil.dll",
        "\\\\server\\share\\evil.txt",
    ]
)

# Mixed traversal + nested (e.g. "foo/../../bar/evil.txt").
mixed_names = st.builds(
    lambda a, depth, b: _nested_name(a) + "/" + "../" * depth + _nested_name(b),
    st.lists(_safe_component, min_size=1, max_size=2),
    st.integers(min_value=1, max_value=4),
    st.lists(_safe_component, min_size=1, max_size=2),
)

entry_name = st.one_of(normal_names, traversal_names, absolute_names, mixed_names)


# Feature: bid-evaluation, Property 1: For any zip archive containing entries with arbitrary names (including ../ traversal and absolute paths), every file written by intake.extract_bid resolves inside the run's bid directory, and any entry that would escape is rejected.
# deadline=None: each example does real zip + filesystem I/O in a fresh temp
# dir, which is far slower (and noisier) than Hypothesis' default 200ms deadline.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(names=st.lists(entry_name, min_size=1, max_size=6, unique=True))
def test_extract_bid_confines_files_to_bid_directory(names):
    # Validates Requirements 1.6.
    # A fresh temp dir per example (Hypothesis reuses function-scoped tmp_path
    # across examples, so we allocate our own).
    workspace = Path(tempfile.mkdtemp(prefix="ziptest_"))
    try:
        run_dir = workspace / "run"
        run_dir.mkdir()
        bid_id = "bid1"

        # Build a real zip on disk containing all the (possibly hostile) entries.
        zip_path = workspace / "hostile.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i, name in enumerate(names):
                # Unique payload so we can detect any escaped write.
                zf.writestr(name, f"payload-{i}".encode())

        result = intake.extract_bid([zip_path], bid_id, run_dir)

        bid_dir = Path(result.bid_dir).resolve()
        expected_bid_dir = (run_dir / bid_id).resolve()
        assert bid_dir == expected_bid_dir

        # (a) Every file under bid_dir resolves inside bid_dir.
        for f in bid_dir.rglob("*"):
            if f.is_file():
                resolved = f.resolve()
                assert resolved == bid_dir or bid_dir in resolved.parents, (
                    f"file {resolved} escaped bid dir {bid_dir}"
                )

        # (b) No file was written outside bid_dir anywhere under the workspace
        #     (walk the whole workspace; only the zip and files inside bid_dir
        #     are permitted). This catches any escaped sibling like 'evil.txt'.
        for f in workspace.rglob("*"):
            if not f.is_file():
                continue
            resolved = f.resolve()
            if resolved == zip_path.resolve():
                continue
            assert bid_dir in resolved.parents or resolved == bid_dir, (
                f"escaped file written outside bid dir: {resolved}"
            )

        # Discovered PDF paths (if any) must also be inside bid_dir.
        for p in result.pdf_paths:
            rp = Path(p).resolve()
            assert bid_dir in rp.parents or rp == bid_dir
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
