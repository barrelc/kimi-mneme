"""Tests for mneme.updater module."""

from mneme.updater import _version_greater


class TestVersionGreater:
    def test_major_version(self):
        assert _version_greater("3.0.0", "2.0.0")
        assert not _version_greater("2.0.0", "3.0.0")

    def test_minor_version(self):
        assert _version_greater("2.1.0", "2.0.0")
        assert not _version_greater("2.0.0", "2.1.0")

    def test_patch_version(self):
        assert _version_greater("2.0.1", "2.0.0")
        assert not _version_greater("2.0.0", "2.0.1")

    def test_equal_versions(self):
        assert not _version_greater("2.0.10", "2.0.10")

    def test_different_length(self):
        assert _version_greater("2.0.10", "2.0.9")
        assert not _version_greater("2.0.9", "2.0.10")
