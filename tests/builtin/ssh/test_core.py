import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


def test_generate_keypair_runs_ssh_keygen(tmp_path):
    from swap.builtin.ssh import core
    key_path = tmp_path / "id_ed25519_test"
    with patch("swap.builtin.ssh.core.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = core.generate_keypair(key_path)
    assert result is True
    args = mock_run.call_args[0][0]
    assert "ssh-keygen" in args
    assert str(key_path) in args
    assert "-N" in args
    assert "" in args  # empty passphrase


def test_generate_keypair_skips_existing(tmp_path):
    from swap.builtin.ssh import core
    key_path = tmp_path / "id_ed25519_test"
    key_path.touch()
    with patch("swap.builtin.ssh.core.subprocess.run") as mock_run:
        result = core.generate_keypair(key_path)
    assert result is False
    mock_run.assert_not_called()


def test_generate_keypair_raises_on_failure(tmp_path):
    from swap.builtin.ssh import core
    key_path = tmp_path / "id_ed25519_test"
    with patch("swap.builtin.ssh.core.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr=b"invalid key type")
        with pytest.raises(RuntimeError, match="ssh-keygen failed"):
            core.generate_keypair(key_path)


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
    assert "10.0.0.2" not in config_path.read_text()


def test_add_config_entry_no_substring_false_positive(tmp_path):
    """'myserver' should not match when config contains 'myserver-production'."""
    from swap.builtin.ssh import core
    config_path = tmp_path / "config"
    config_path.write_text("Host myserver-production\n    HostName 10.0.0.1\n")
    key_path = tmp_path / "id_ed25519_test"
    result = core.add_config_entry("myserver", "10.0.0.2", "root", key_path, config_path)
    assert result is True  # should NOT be skipped


def test_push_public_key_uses_sftp(tmp_path):
    from swap.builtin.ssh import core

    mock_sftp = MagicMock()
    mock_sftp.__enter__ = MagicMock(return_value=mock_sftp)
    mock_sftp.__exit__ = MagicMock(return_value=False)
    mock_sftp.stat.side_effect = FileNotFoundError
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=mock_file)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_file.read.return_value = b""
    mock_sftp.open.return_value = mock_file

    mock_client = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp

    with patch("paramiko.SSHClient", return_value=mock_client):
        result = core.push_public_key("host", "user", "pass", "ssh-ed25519 AAAA test_key")

    assert result is True
    mock_client.connect.assert_called_once_with("host", username="user", password="pass", timeout=10)
    mock_client.close.assert_called_once()


def test_push_public_key_skips_duplicate():
    from swap.builtin.ssh import core

    mock_sftp = MagicMock()
    mock_sftp.__enter__ = MagicMock(return_value=mock_sftp)
    mock_sftp.__exit__ = MagicMock(return_value=False)
    mock_sftp.stat.return_value = MagicMock()  # .ssh exists
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=mock_file)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_file.read.return_value = b"ssh-ed25519 AAAA existing_key\n"
    mock_sftp.open.return_value = mock_file

    mock_client = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp

    with patch("paramiko.SSHClient", return_value=mock_client):
        result = core.push_public_key("host", "user", "pass", "ssh-ed25519 AAAA existing_key")

    assert result is False


def test_setup_orchestrates_all_steps(tmp_path):
    from swap.builtin.ssh import core

    pub_key_content = "ssh-ed25519 AAAA testkey"

    # Create the .pub file that setup() will read
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    pub_path = ssh_dir / "mykey.pub"
    pub_path.write_text(pub_key_content)

    with patch.object(core, "generate_keypair", return_value=True) as mock_gen, \
         patch.object(core, "push_public_key", return_value=True) as mock_push, \
         patch.object(core, "add_config_entry", return_value=True) as mock_cfg, \
         patch("swap.builtin.ssh.core.Path.home", return_value=tmp_path):

        result = core.setup("myalias", "myhost", "myuser", "mykey", "mypass")

    assert result.key_generated is True
    assert result.key_pushed is True
    assert result.config_updated is True
    assert result.alias == "myalias"
    assert result.hostname == "myhost"
    assert result.username == "myuser"
    mock_push.assert_called_once()
    push_args = mock_push.call_args[0]
    assert push_args[3] == pub_key_content
