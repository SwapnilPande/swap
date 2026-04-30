import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


def test_generate_keypair_runs_ssh_keygen(tmp_path):
    from swap.builtin.ssh import core
    key_path = tmp_path / "id_ed25519_test"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = core.generate_keypair(key_path)
    assert result is True
    args = mock_run.call_args[0][0]
    assert "ssh-keygen" in args
    assert str(key_path) in args


def test_generate_keypair_skips_existing(tmp_path):
    from swap.builtin.ssh import core
    key_path = tmp_path / "id_ed25519_test"
    key_path.touch()
    with patch("subprocess.run") as mock_run:
        result = core.generate_keypair(key_path)
    assert result is False
    mock_run.assert_not_called()


def test_add_config_entry_creates_new_file(tmp_path):
    from swap.builtin.ssh import core
    config_path = tmp_path / "config"
    key_path = tmp_path / "id_ed25519_test"
    result = core.add_config_entry("myserver", "192.168.1.1", "ubuntu", key_path, config_path)
    assert result is True
    content = config_path.read_text()
    assert "Host myserver" in content
    assert "HostName 192.168.1.1" in content
    assert "User ubuntu" in content
    assert str(key_path) in content


def test_add_config_entry_appends_to_existing(tmp_path):
    from swap.builtin.ssh import core
    config_path = tmp_path / "config"
    config_path.write_text("Host existing\n    HostName 10.0.0.1\n")
    key_path = tmp_path / "id_ed25519_test"
    result = core.add_config_entry("newhost", "10.0.0.2", "root", key_path, config_path)
    assert result is True
    content = config_path.read_text()
    assert "Host existing" in content
    assert "Host newhost" in content


def test_add_config_entry_skips_duplicate_alias(tmp_path):
    from swap.builtin.ssh import core
    config_path = tmp_path / "config"
    config_path.write_text("Host myserver\n    HostName 10.0.0.1\n")
    key_path = tmp_path / "id_ed25519_test"
    result = core.add_config_entry("myserver", "10.0.0.2", "root", key_path, config_path)
    assert result is False
    # File should not be changed
    assert "10.0.0.2" not in config_path.read_text()


def test_push_public_key_calls_exec_command(tmp_path):
    from swap.builtin.ssh import core
    mock_channel = MagicMock()
    mock_channel.recv_exit_status.return_value = 0
    mock_stdout = MagicMock()
    mock_stdout.channel = mock_channel
    mock_client = MagicMock()
    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

    with patch("paramiko.SSHClient", return_value=mock_client):
        core.push_public_key("host", "user", "pass", "ssh-ed25519 AAAA...")

    mock_client.connect.assert_called_once_with("host", username="user", password="pass", timeout=10)
    mock_client.exec_command.assert_called_once()
    cmd_arg = mock_client.exec_command.call_args[0][0]
    assert "authorized_keys" in cmd_arg
    mock_client.close.assert_called_once()


def test_push_public_key_raises_on_nonzero_exit():
    from swap.builtin.ssh import core
    mock_channel = MagicMock()
    mock_channel.recv_exit_status.return_value = 1
    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b"permission denied"
    mock_stdout = MagicMock()
    mock_stdout.channel = mock_channel
    mock_client = MagicMock()
    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

    with patch("paramiko.SSHClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Failed to push key"):
            core.push_public_key("host", "user", "pass", "ssh-ed25519 AAAA...")
