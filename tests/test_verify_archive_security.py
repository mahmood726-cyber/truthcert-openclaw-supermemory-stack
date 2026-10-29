"""Security regressions: the verification CLI must not trust arbitrary tar members."""

import io
import json
import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.tc import _extract_verified_bundle, cli


def _write_tar(path: Path, entries: list[tuple[str, str]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "directory":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside.txt"
                archive.addfile(info)
            elif kind == "hardlink":
                info.type = tarfile.LNKTYPE
                info.linkname = "../../outside.txt"
                archive.addfile(info)
            else:
                payload = json.dumps({"bundle_id": "synthetic-id", "outcome": "PASS"}).encode()
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))


def test_tarball_verification_uses_isolated_temp_directory(tmp_path):
    archive = tmp_path / "bundle_test.tar.gz"
    _write_tar(archive, [
        ("bundle_test", "directory"),
        ("bundle_test/manifest.json", "file"),
    ])
    result = CliRunner().invoke(
        cli, ["verify", str(archive), "--no-check-signature", "--no-check-scope-lock"]
    )
    assert result.exit_code == 0, result.output
    assert "Verification PASSED" in result.output
    # No writes next to an untrusted input archive.
    assert not (tmp_path / "bundle_test").exists()


@pytest.mark.parametrize(
    "entries",
    [
        [("bundle_test/../../outside.txt", "file")],
        [("/bundle_test/manifest.json", "file")],
        [("bundle_test/attest", "symlink")],
        [("bundle_test/attest", "hardlink")],
        [("different_bundle/manifest.json", "file")],
        [("bundle_test\\\\..\\\\outside.txt", "file")],
        [("bundle_test/./manifest.json", "file")],
        [("bundle_test/manifest.json", "file"), ("bundle_test/manifest.json", "file")],
        [("bundle_test/manifest.json", "file"), ("bundle_test/MANIFEST.json", "file")],
    ],
)
def test_unsafe_tar_member_refused_without_parent_writes(tmp_path, entries):
    archive = tmp_path / "bundle_test.tar.gz"
    sentinel = tmp_path / "outside.txt"
    sentinel.write_text("untouched")
    _write_tar(archive, entries)

    result = CliRunner().invoke(cli, [
        "verify", str(archive), "--no-check-signature", "--no-check-scope-lock"
    ])
    assert result.exit_code != 0
    assert "Unsafe or invalid bundle archive" in result.output
    assert sentinel.read_text() == "untouched"
    assert not (tmp_path / "bundle_test").exists()


def test_archive_member_size_limit_refuses_before_extraction(tmp_path):
    archive_path = tmp_path / "bundle_test.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        huge = tarfile.TarInfo("bundle_test/oversized.json")
        huge.size = 50_000_001
        # A sparse tar header could claim huge size, but the builder must refuse
        # it at the archive metadata boundary before attempting extraction.
        tar.addfile(huge, io.BytesIO(b"0" * 50_000_001))
    with pytest.raises(ValueError, match="extraction limits"):
        _extract_verified_bundle(archive_path, tmp_path / "output")
