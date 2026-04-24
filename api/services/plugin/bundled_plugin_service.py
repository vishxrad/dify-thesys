"""Install repo-bundled local plugins into newly created tenants.

This service makes the "bundled plugin" workflow reproducible for source-based
Docker stacks. Instead of depending on a plugin having been installed manually
inside a long-lived plugin-daemon volume, a tenant can bootstrap the plugin
directly from a local path that ships with the repo image.

Configured paths may point to either:
- a prebuilt ``.difypkg`` archive, or
- an unpacked plugin directory that should be zipped on the fly.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from pathlib import Path

from configs import dify_config
from core.plugin.entities.plugin_daemon import PluginInstallTaskStatus
from services.plugin.plugin_service import PluginService

logger = logging.getLogger(__name__)


class BundledPluginInstallError(RuntimeError):
    """Raised when a configured bundled plugin cannot be installed for a tenant."""


class BundledPluginService:
    """Package and install local repo plugins for a tenant.

    The installation runs through the normal plugin service so tenant scoping,
    verification rules, and plugin-daemon compatibility checks stay centralized.
    """

    EXCLUDED_PARTS = frozenset({".venv", "__pycache__", ".pytest_cache"})
    EXCLUDED_SUFFIXES = frozenset({".pyc"})

    @classmethod
    def install_for_tenant(cls, tenant_id: str) -> None:
        """Install every configured bundled plugin for the provided tenant.

        Each configured package is attempted independently. In strict mode the
        first failure is raised after aborting the remaining installs. In
        non-strict mode every failure is logged and installation continues so a
        single bad package does not block tenant setup.
        """
        strict = dify_config.PLUGIN_AUTO_INSTALL_STRICT

        for configured_path in dify_config.PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES:
            try:
                plugin_path = cls._resolve_path(configured_path)
                package = cls._load_plugin_package(plugin_path)

                logger.info(
                    "Auto-installing bundled plugin from %s for tenant %s", plugin_path, tenant_id
                )

                upload_response = PluginService.upload_pkg(tenant_id, package)
                install_response = PluginService.install_from_local_pkg(
                    tenant_id,
                    [upload_response.unique_identifier],
                    skip_redecode=True,
                )
                cls._wait_for_installation(
                    tenant_id=tenant_id,
                    task_id=install_response.task_id,
                    plugin_unique_identifier=upload_response.unique_identifier,
                    plugin_path=plugin_path,
                    all_installed=install_response.all_installed,
                )
            except Exception as exc:
                err = exc if isinstance(exc, BundledPluginInstallError) else BundledPluginInstallError(
                    f"Failed to auto-install bundled plugin from {configured_path} "
                    f"for tenant {tenant_id}: {exc}"
                )
                if strict:
                    raise err from exc
                logger.exception(
                    "Non-strict bundled plugin install failed for %s (tenant %s)",
                    configured_path,
                    tenant_id,
                )

    @classmethod
    def _resolve_path(cls, configured_path: str) -> Path:
        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            # Relative paths depend on the worker CWD at request time, which is
            # not predictable across deployment setups. Require absolute paths
            # so misconfiguration fails fast instead of silently resolving to
            # the wrong directory.
            raise BundledPluginInstallError(
                f"Configured bundled plugin path must be absolute: {configured_path}"
            )

        return path.resolve()

    @classmethod
    def _load_plugin_package(cls, plugin_path: Path) -> bytes:
        """Load a plugin archive from disk or build one from a plugin directory."""
        if not plugin_path.exists():
            raise BundledPluginInstallError(f"Configured plugin path does not exist: {plugin_path}")

        if plugin_path.is_file():
            return plugin_path.read_bytes()

        if not plugin_path.is_dir():
            raise BundledPluginInstallError(f"Configured plugin path is neither a file nor a directory: {plugin_path}")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(plugin_path.rglob("*")):
                if not file_path.is_file():
                    continue

                relative_path = file_path.relative_to(plugin_path)
                if any(part in cls.EXCLUDED_PARTS for part in relative_path.parts):
                    continue
                if file_path.suffix in cls.EXCLUDED_SUFFIXES:
                    continue

                archive.write(file_path, relative_path.as_posix())

        return buffer.getvalue()

    @classmethod
    def _wait_for_installation(
        cls,
        tenant_id: str,
        task_id: str,
        plugin_unique_identifier: str,
        plugin_path: Path,
        all_installed: bool,
    ) -> None:
        if all_installed:
            logger.info("Bundled plugin %s already installed for tenant %s", plugin_unique_identifier, tenant_id)
            return

        if not task_id:
            raise BundledPluginInstallError(
                f"Plugin install task for {plugin_path} did not return a task_id for tenant {tenant_id}"
            )

        deadline = time.monotonic() + dify_config.PLUGIN_AUTO_INSTALL_TIMEOUT
        while time.monotonic() < deadline:
            task = PluginService.fetch_install_task(tenant_id, task_id)
            if task.status == PluginInstallTaskStatus.Success:
                logger.info("Bundled plugin %s installed for tenant %s", plugin_unique_identifier, tenant_id)
                return

            if task.status == PluginInstallTaskStatus.Failed:
                messages = [
                    plugin.message
                    for plugin in task.plugins
                    if plugin.plugin_unique_identifier == plugin_unique_identifier and plugin.message
                ]
                message = "; ".join(messages) if messages else f"Plugin task {task_id} failed"
                raise BundledPluginInstallError(message)

            time.sleep(1)

        raise BundledPluginInstallError(
            f"Timed out waiting for bundled plugin {plugin_path} to install for tenant {tenant_id}"
        )
