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


def test_save_brokerage_identity_roundtrip(tmp_path):
    config.save_brokerage_identity(tmp_path, client_id="cid-123", user_id="stock-advisor")
    loaded = config.load_integrations(tmp_path)
    assert loaded["SNAPTRADE_CLIENT_ID"] == "cid-123"
    assert loaded["SNAPTRADE_USER_ID"] == "stock-advisor"


def test_brokerage_and_email_coexist_without_clobbering(tmp_path):
    config.save_integrations(tmp_path, user="me@gmail.com", to="me@gmail.com",
                             host="smtp.gmail.com", port="465")
    config.save_brokerage_identity(tmp_path, client_id="cid-123")
    loaded = config.load_integrations(tmp_path)
    assert loaded["EMAIL_USER"] == "me@gmail.com"      # email survived the brokerage write
    assert loaded["SNAPTRADE_CLIENT_ID"] == "cid-123"


def test_save_brokerage_identity_skips_none_clears_blank(tmp_path):
    config.save_brokerage_identity(tmp_path, client_id="cid-123", user_id="u1")
    config.save_brokerage_identity(tmp_path, client_id="")        # client_id cleared, user_id untouched
    loaded = config.load_integrations(tmp_path)
    assert "SNAPTRADE_CLIENT_ID" not in loaded
    assert loaded["SNAPTRADE_USER_ID"] == "u1"
