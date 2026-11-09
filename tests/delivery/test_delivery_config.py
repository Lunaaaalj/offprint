"""Delivery settings: the file, its defaults, and where the password may come from."""

from pathlib import Path

import pytest

from offprint.delivery import DeliveryError, load_delivery_config
from offprint.delivery.config import smtp_password

TOML = """
[kindle]
address = "me_abc@kindle.com"
sender = "me@example.com"

[smtp]
host = "smtp.example.com"
username = "me@example.com"
"""


def env_for(tmp_path: Path, text: str | None = TOML) -> dict[str, str]:
    path = tmp_path / "config.toml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return {"HOME": str(tmp_path), "OFFPRINT_CONFIG_FILE": str(path)}


def test_the_settings_and_their_defaults(tmp_path: Path) -> None:
    config = load_delivery_config(env_for(tmp_path))

    assert (config.kindle, config.sender) == ("me_abc@kindle.com", "me@example.com")
    assert (config.host, config.port, config.security) == ("smtp.example.com", 587, "starttls")
    assert config.username == "me@example.com"
    assert config.max_bytes == 50_000_000
    assert config.widths == (1600, 1200, 900, 600)
    assert config.log_path == tmp_path / ".local" / "share" / "offprint" / "deliveries.jsonl"


def test_the_default_port_follows_the_security(tmp_path: Path) -> None:
    text = TOML.replace('host = "smtp.example.com"', 'host = "h"\nsecurity = "ssl"')

    assert load_delivery_config(env_for(tmp_path, text)).port == 465


def test_the_limits_and_the_log_can_be_set(tmp_path: Path) -> None:
    text = TOML + "\n[limits]\nmax_mb = 20\nwidths = [600, 1200, 600]\n"
    env = env_for(tmp_path, text) | {"OFFPRINT_DELIVERY_LOG": str(tmp_path / "log.jsonl")}

    config = load_delivery_config(env)

    assert config.max_bytes == 20_000_000
    assert config.widths == (1200, 600)
    assert config.log_path == tmp_path / "log.jsonl"


def test_xdg_data_home_holds_the_log(tmp_path: Path) -> None:
    env = env_for(tmp_path) | {"XDG_DATA_HOME": str(tmp_path / "xdg")}

    assert load_delivery_config(env).log_path == tmp_path / "xdg" / "offprint" / "deliveries.jsonl"


def test_no_login_is_fine(tmp_path: Path) -> None:
    text = TOML.replace('username = "me@example.com"\n', "")

    assert load_delivery_config(env_for(tmp_path, text)).username is None


def test_a_missing_file_says_where_to_look(tmp_path: Path) -> None:
    with pytest.raises(DeliveryError, match=r"no config file at .*config\.toml"):
        load_delivery_config(env_for(tmp_path, None))


def test_a_password_in_the_file_is_refused(tmp_path: Path) -> None:
    text = TOML + 'password = "hunter2"\n'

    with pytest.raises(DeliveryError, match="can't be in the config file"):
        load_delivery_config(env_for(tmp_path, text))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('address = "me_abc@kindle.com"', 'address = "nope"', "kindle.address"),
        ('sender = "me@example.com"', "", "kindle.sender"),
        ('host = "smtp.example.com"', 'host = "h"\nport = 0', "smtp.port"),
        ('host = "smtp.example.com"', 'host = "h"\nsecurity = "tls"', "smtp.security"),
        ("[smtp]", "[mail]", r"missing the \[smtp\] section"),
        ("[kindle]", "kindle = 3\n[x]", r"missing the \[kindle\] section"),
    ],
)
def test_a_wrong_value_names_its_key(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(DeliveryError, match=message):
        load_delivery_config(env_for(tmp_path, TOML.replace(old, new)))


def test_bad_toml_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DeliveryError, match="can't read"):
        load_delivery_config(env_for(tmp_path, "[kindle"))


def test_a_bad_width_list_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DeliveryError, match="limits.widths"):
        load_delivery_config(env_for(tmp_path, TOML + "\n[limits]\nwidths = ['x']\n"))


def test_the_password_comes_from_the_environment_first(tmp_path: Path) -> None:
    config = load_delivery_config(env_for(tmp_path))

    def keyring(service: str, user: str) -> str:
        raise AssertionError("the keychain shouldn't be asked")

    assert smtp_password(config, {"OFFPRINT_SMTP_PASSWORD": "app-pw"}, keyring) == "app-pw"


def test_the_password_falls_back_to_the_keychain(tmp_path: Path) -> None:
    config = load_delivery_config(env_for(tmp_path))
    asked: list[tuple[str, str]] = []

    def keyring(service: str, user: str) -> str:
        asked.append((service, user))
        return "from-keychain"

    assert smtp_password(config, {}, keyring) == "from-keychain"
    assert asked == [("offprint", "me@example.com")]


def test_no_password_anywhere_says_how_to_set_one(tmp_path: Path) -> None:
    config = load_delivery_config(env_for(tmp_path))

    with pytest.raises(DeliveryError, match=r"keyring set offprint me@example\.com"):
        smtp_password(config, {}, lambda service, user: None)


def test_a_broken_keychain_is_a_delivery_error(tmp_path: Path) -> None:
    config = load_delivery_config(env_for(tmp_path))

    def keyring(service: str, user: str) -> str:
        raise RuntimeError("locked")

    with pytest.raises(DeliveryError, match="can't read the keychain: locked"):
        smtp_password(config, {}, keyring)


def test_without_a_login_there_is_no_password(tmp_path: Path) -> None:
    config = load_delivery_config(
        env_for(tmp_path, TOML.replace('username = "me@example.com"', ""))
    )

    assert smtp_password(config, {}, lambda service, user: "unused") is None
