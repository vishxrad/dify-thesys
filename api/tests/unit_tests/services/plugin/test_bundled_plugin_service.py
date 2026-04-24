"""Tests for services.plugin.bundled_plugin_service."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.plugin.entities.plugin_daemon import PluginInstallTaskStartResponse, PluginInstallTaskStatus
from services.plugin.bundled_plugin_service import BundledPluginInstallError, BundledPluginService


def _write_plugin_fixture(plugin_dir: Path) -> None:
    (plugin_dir / "provider").mkdir(parents=True)
    (plugin_dir / "provider" / "provider.py").write_text("value = 1\n")
    (plugin_dir / "manifest.yaml").write_text("name: Thesys\n")


class TestBundledPluginService:
    def test_load_plugin_package_ignores_cache_artifacts(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "thesys"
        _write_plugin_fixture(plugin_dir)
        (plugin_dir / "__pycache__").mkdir()
        (plugin_dir / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")
        (plugin_dir / ".pytest_cache").mkdir()
        (plugin_dir / ".pytest_cache" / "state").write_text("ignored")
        (plugin_dir / ".venv").mkdir()
        (plugin_dir / ".venv" / "ignored.py").write_text("ignored")

        package_bytes = BundledPluginService._load_plugin_package(plugin_dir)

        with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
            assert sorted(archive.namelist()) == ["manifest.yaml", "provider/provider.py"]

    @patch("services.plugin.bundled_plugin_service.time.sleep")
    @patch("services.plugin.bundled_plugin_service.dify_config")
    @patch("services.plugin.bundled_plugin_service.PluginService")
    def test_install_for_tenant_waits_for_success(
        self,
        mock_plugin_service: MagicMock,
        mock_config: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        plugin_dir = tmp_path / "thesys"
        _write_plugin_fixture(plugin_dir)

        mock_config.PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES = [str(plugin_dir)]
        mock_config.PLUGIN_AUTO_INSTALL_TIMEOUT = 2
        mock_config.PLUGIN_AUTO_INSTALL_STRICT = True
        mock_plugin_service.upload_pkg.return_value.unique_identifier = "local/thesys:0.1.0@checksum"
        mock_plugin_service.install_from_local_pkg.return_value = PluginInstallTaskStartResponse(
            all_installed=False,
            task_id="task-123",
        )
        mock_plugin_service.fetch_install_task.side_effect = [
            MagicMock(status=PluginInstallTaskStatus.Running),
            MagicMock(status=PluginInstallTaskStatus.Success),
        ]

        BundledPluginService.install_for_tenant("tenant-1")

        upload_args = mock_plugin_service.upload_pkg.call_args[0]
        assert upload_args[0] == "tenant-1"
        assert isinstance(upload_args[1], bytes)
        mock_plugin_service.install_from_local_pkg.assert_called_once_with(
            "tenant-1",
            ["local/thesys:0.1.0@checksum"],
            skip_redecode=True,
        )
        assert mock_plugin_service.fetch_install_task.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("services.plugin.bundled_plugin_service.time.sleep")
    @patch("services.plugin.bundled_plugin_service.dify_config")
    @patch("services.plugin.bundled_plugin_service.PluginService")
    def test_install_for_tenant_raises_when_task_fails(
        self,
        mock_plugin_service: MagicMock,
        mock_config: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        plugin_dir = tmp_path / "thesys"
        _write_plugin_fixture(plugin_dir)

        mock_config.PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES = [str(plugin_dir)]
        mock_config.PLUGIN_AUTO_INSTALL_TIMEOUT = 2
        mock_config.PLUGIN_AUTO_INSTALL_STRICT = True
        mock_plugin_service.upload_pkg.return_value.unique_identifier = "local/thesys:0.1.0@checksum"
        mock_plugin_service.install_from_local_pkg.return_value = PluginInstallTaskStartResponse(
            all_installed=False,
            task_id="task-456",
        )
        mock_plugin_service.fetch_install_task.return_value = MagicMock(
            status=PluginInstallTaskStatus.Failed,
            plugins=[
                MagicMock(
                    plugin_unique_identifier="local/thesys:0.1.0@checksum",
                    message="signature mismatch",
                ),
            ],
        )

        with pytest.raises(BundledPluginInstallError, match="signature mismatch"):
            BundledPluginService.install_for_tenant("tenant-1")

        mock_sleep.assert_not_called()

    @patch("services.plugin.bundled_plugin_service.dify_config")
    def test_resolve_path_rejects_relative_paths(self, mock_config: MagicMock) -> None:
        mock_config.PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES = ["relative/plugin/path"]
        mock_config.PLUGIN_AUTO_INSTALL_STRICT = True

        # Relative paths are a misconfiguration, surfaced as the underlying
        # BundledPluginInstallError so the caller can react.
        with pytest.raises(BundledPluginInstallError, match="must be absolute"):
            BundledPluginService.install_for_tenant("tenant-1")

    @patch("services.plugin.bundled_plugin_service.time.sleep")
    @patch("services.plugin.bundled_plugin_service.dify_config")
    @patch("services.plugin.bundled_plugin_service.PluginService")
    def test_non_strict_mode_continues_past_failures(
        self,
        mock_plugin_service: MagicMock,
        mock_config: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path,
    ) -> None:
        ok_dir = tmp_path / "ok"
        _write_plugin_fixture(ok_dir)

        mock_config.PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES = [
            str(tmp_path / "missing"),  # raises load error
            str(ok_dir),                # still gets installed
        ]
        mock_config.PLUGIN_AUTO_INSTALL_TIMEOUT = 2
        mock_config.PLUGIN_AUTO_INSTALL_STRICT = False

        mock_plugin_service.upload_pkg.return_value.unique_identifier = "local/ok:0.1.0@checksum"
        mock_plugin_service.install_from_local_pkg.return_value = PluginInstallTaskStartResponse(
            all_installed=True,
            task_id="",
        )

        BundledPluginService.install_for_tenant("tenant-1")

        mock_plugin_service.upload_pkg.assert_called_once()
        mock_plugin_service.install_from_local_pkg.assert_called_once()
