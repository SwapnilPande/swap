from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def isolated_swap_home(tmp_path, monkeypatch):
    from swap.core import config
    monkeypatch.setattr(config, "SWAP_HOME", tmp_path)
    return tmp_path


def test_data_dir_prints_path(isolated_swap_home):
    from swap.builtin.plugins.cli import cli

    runner = CliRunner()
    with patch("swap.builtin.plugins.cli.plugin_manager.is_installed", return_value=True):
        result = runner.invoke(cli, ["data-dir", "myplug"])

    assert result.exit_code == 0, result.output
    expected = isolated_swap_home / "data" / "myplug"
    assert str(expected) in result.output
    assert expected.is_dir()


def test_data_dir_errors_when_not_installed(isolated_swap_home):
    from swap.builtin.plugins.cli import cli

    runner = CliRunner()
    with patch("swap.builtin.plugins.cli.plugin_manager.is_installed", return_value=False):
        result = runner.invoke(cli, ["data-dir", "ghost"])

    assert result.exit_code != 0
    assert "not installed" in result.output


def test_uninstall_purge_flag_passes_through(isolated_swap_home):
    from swap.builtin.plugins.cli import cli

    runner = CliRunner()
    data_dir = isolated_swap_home / "data" / "myplug"
    data_dir.mkdir(parents=True)
    (data_dir / "file.txt").write_text("payload")

    with patch(
        "swap.core.plugin_manager.get_installed_plugins",
        return_value={"myplug": "swap-myplug"},
    ):
        with patch("swap.core.plugin_manager.subprocess.run"):
            result = runner.invoke(cli, ["uninstall", "myplug", "--purge"])

    assert result.exit_code == 0, result.output
    assert not data_dir.exists()


def test_uninstall_without_purge_keeps_data(isolated_swap_home):
    from swap.builtin.plugins.cli import cli

    runner = CliRunner()
    data_dir = isolated_swap_home / "data" / "myplug"
    data_dir.mkdir(parents=True)
    (data_dir / "file.txt").write_text("payload")

    with patch(
        "swap.core.plugin_manager.get_installed_plugins",
        return_value={"myplug": "swap-myplug"},
    ):
        with patch("swap.core.plugin_manager.subprocess.run"):
            result = runner.invoke(cli, ["uninstall", "myplug"])

    assert result.exit_code == 0, result.output
    assert data_dir.exists()
