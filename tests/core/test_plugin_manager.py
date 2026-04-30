import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_scaffold_creates_expected_structure(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    assert (plugin_dir / "pyproject.toml").exists()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "myplug" / "__init__.py").exists()
    assert (plugin_dir / "myplug" / "cli.py").exists()
    assert (plugin_dir / "myplug" / "core.py").exists()


def test_scaffold_pyproject_has_entry_point(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    content = (plugin_dir / "pyproject.toml").read_text()
    assert '[project.entry-points."swap.plugins"]' in content
    assert 'myplug = "myplug.cli:cli"' in content


def test_scaffold_pyproject_has_correct_package_name(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    content = (plugin_dir / "pyproject.toml").read_text()
    assert 'name = "swap-myplug"' in content


def test_scaffold_raises_if_dir_exists(tmp_path):
    from swap.core import plugin_manager
    plugin_manager.scaffold("myplug", tmp_path, "First")
    with pytest.raises(FileExistsError):
        plugin_manager.scaffold("myplug", tmp_path, "Second")


def test_scaffold_cli_template_has_group(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    cli_content = (plugin_dir / "myplug" / "cli.py").read_text()
    assert '@click.group(name="myplug")' in cli_content
    assert "def cli():" in cli_content


def test_scaffold_core_has_no_cli_imports(tmp_path):
    from swap.core import plugin_manager
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, "A test plugin")
    core_content = (plugin_dir / "myplug" / "core.py").read_text()
    assert "click" not in core_content
    assert "questionary" not in core_content


def test_is_installed_false_for_unknown():
    from swap.core import plugin_manager
    with patch("swap.core.plugin_manager.get_installed_plugins", return_value={}):
        assert plugin_manager.is_installed("ghost") is False


def test_is_installed_true_for_known():
    from swap.core import plugin_manager
    with patch("swap.core.plugin_manager.get_installed_plugins", return_value={"ssh": "swap-ssh"}):
        assert plugin_manager.is_installed("ssh") is True


def test_install_runs_uv_pip_install(tmp_path):
    from swap.core import plugin_manager
    registry_data = {"install": "swap-myplug", "package": "swap-myplug"}
    with patch("swap.core.registry.get_plugin", return_value=registry_data):
        with patch("swap.core.plugin_manager.subprocess.run") as mock_run:
            plugin_manager.install("myplug")
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "uv" in cmd
    assert "swap-myplug" in cmd


def test_install_raises_if_not_in_registry():
    from swap.core import plugin_manager
    with patch("swap.core.registry.get_plugin", return_value=None):
        with pytest.raises(ValueError, match="not found in registry"):
            plugin_manager.install("ghost")


def test_uninstall_raises_if_not_installed():
    from swap.core import plugin_manager
    with patch("swap.core.plugin_manager.get_installed_plugins", return_value={}):
        with pytest.raises(ValueError, match="not installed"):
            plugin_manager.uninstall("ghost")


def test_uninstall_runs_uv_pip_uninstall():
    from swap.core import plugin_manager
    with patch("swap.core.plugin_manager.get_installed_plugins", return_value={"myplug": "swap-myplug"}):
        with patch("swap.core.plugin_manager.subprocess.run") as mock_run:
            plugin_manager.uninstall("myplug")
    cmd = mock_run.call_args[0][0]
    assert "uv" in cmd
    assert "uninstall" in cmd
    assert "swap-myplug" in cmd


def test_scaffold_pyproject_handles_quotes_in_description(tmp_path):
    from swap.core import plugin_manager
    import tomllib
    plugin_dir = plugin_manager.scaffold("myplug", tmp_path, 'A plugin with "quotes" and \\backslashes')
    # The pyproject.toml must be valid TOML (parseable)
    with open(plugin_dir / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert "quotes" in data["project"]["description"]
