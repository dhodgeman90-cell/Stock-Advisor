from src import config


def test_load_missing_file_is_empty(tmp_path):
    assert config.load_integrations(tmp_path) == {}


def test_save_then_load_roundtrip(tmp_path):
    config.save_integrations(tmp_path, user="me@gmail.com", to="me@gmail.com",
                             host="smtp.gmail.com", port="465")
    loaded = config.load_integrations(tmp_path)
    assert loaded == {
        "EMAIL_USER": "me@gmail.com",
        "EMAIL_TO": "me@gmail.com",
        "EMAIL_HOST": "smtp.gmail.com",
        "EMAIL_PORT": "465",
    }


def test_blank_fields_are_omitted_not_stored_as_empty(tmp_path):
    # Saving with blanks must not write empty strings the engine would treat as "set".
    config.save_integrations(tmp_path, user="me@gmail.com", to="", host="", port="")
    assert config.load_integrations(tmp_path) == {"EMAIL_USER": "me@gmail.com"}


def test_values_are_stringified_and_trimmed(tmp_path):
    config.save_integrations(tmp_path, user="  me@gmail.com  ", to="you@x.com",
                             host="smtp.gmail.com", port=587)
    loaded = config.load_integrations(tmp_path)
    assert loaded["EMAIL_USER"] == "me@gmail.com"
    assert loaded["EMAIL_PORT"] == "587"
