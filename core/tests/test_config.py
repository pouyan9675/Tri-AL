from pathlib import Path

import pytest

from trial_al.config import ConfigError, config_path, load_config, set_plugin_enabled


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_means_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "absent.toml", env={})

    assert config.server.host == "127.0.0.1"
    assert config.server.port == 8000
    assert config.data.dir == Path("data")
    assert config.update.schedule == "daily"
    assert config.plugins == {}


def test_reads_the_file(tmp_path: Path) -> None:
    path = write(
        tmp_path / "trial-al.toml",
        '[server]\nport = 9000\n\n[plugins.sample]\nenabled = false\ngreeting = "Hi"\n',
    )

    config = load_config(path, env={})

    assert config.server.port == 9000
    assert not config.plugin_enabled("sample")
    assert config.plugin_settings("sample") == {"greeting": "Hi"}


def test_plugins_without_a_section_are_enabled() -> None:
    config = load_config(Path("absent.toml"), env={})

    assert config.plugin_enabled("anything")
    assert config.plugin_settings("anything") == {}


def test_environment_overrides_the_file(tmp_path: Path) -> None:
    path = write(tmp_path / "trial-al.toml", '[server]\nhost = "0.0.0.0"\nport = 9000\n')
    env = {
        "TRIAL_AL_SERVER__PORT": "9100",
        "TRIAL_AL_PLUGINS__SAMPLE__GREETING": "Hi",
        "TRIAL_AL_PLUGINS__OTHER__ENABLED": "false",
        "UNRELATED": "ignored",
    }

    config = load_config(path, env=env)

    assert config.server.host == "0.0.0.0"
    assert config.server.port == 9100
    assert config.plugin_settings("sample") == {"greeting": "Hi"}
    assert not config.plugin_enabled("other")


def test_config_path_comes_from_trial_al_config(tmp_path: Path) -> None:
    path = write(tmp_path / "custom.toml", "[server]\nport = 9200\n")
    env = {"TRIAL_AL_CONFIG": str(path)}

    assert config_path({}) == Path("trial-al.toml")
    assert config_path(env) == path
    assert load_config(env=env).server.port == 9200


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    path = write(tmp_path / "trial-al.toml", "[server]\nhots = 'x'\n")

    with pytest.raises(ConfigError, match=r"server\.hots: Extra inputs are not permitted"):
        load_config(path, env={})


def test_errors_name_the_environment_variable(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"server\.port: .* \(from TRIAL_AL_SERVER__PORT\)"):
        load_config(tmp_path / "absent.toml", env={"TRIAL_AL_SERVER__PORT": "lots"})


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"TRIAL_AL_SERVER__": "1"}, "empty key"),
        ({"TRIAL_AL_SERVER__HOST__NAME": "x"}, "'server.host' is not a table"),
    ],
)
def test_rejects_malformed_environment_variables(
    tmp_path: Path, env: dict[str, str], message: str
) -> None:
    path = write(tmp_path / "trial-al.toml", "[server]\nhost = 'h'\n")

    with pytest.raises(ConfigError, match=message):
        load_config(path, env=env)


def test_rejects_invalid_toml(tmp_path: Path) -> None:
    path = write(tmp_path / "trial-al.toml", "[server\n")

    with pytest.raises(ConfigError, match=r"trial-al\.toml"):
        load_config(path, env={})


def test_set_plugin_enabled_creates_the_file(tmp_path: Path) -> None:
    path = tmp_path / "trial-al.toml"

    set_plugin_enabled(path, "sample", False)

    assert path.read_text() == "[plugins.sample]\nenabled = false\n"
    assert not load_config(path, env={}).plugin_enabled("sample")


def test_set_plugin_enabled_keeps_comments_and_settings(tmp_path: Path) -> None:
    original = (
        '# My setup\n[server]\nport = 9000  # not 8000\n\n[plugins.sample]\ngreeting = "Hi"\n'
    )
    path = write(tmp_path / "trial-al.toml", original)

    set_plugin_enabled(path, "sample", False)

    assert path.read_text() == original + "enabled = false\n"
    config = load_config(path, env={})
    assert not config.plugin_enabled("sample")
    assert config.plugin_settings("sample") == {"greeting": "Hi"}
