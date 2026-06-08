from src import news


def test_parse_new_style_items():
    items = [{"content": {"title": "Apple soars on earnings"}}]
    assert news._parse_news_items(items) == ["Apple soars on earnings"]


def test_parse_old_style_items():
    items = [{"title": "Legacy headline"}]
    assert news._parse_news_items(items) == ["Legacy headline"]


def test_parse_respects_limit_and_skips_titleless():
    items = [
        {"content": {"title": "One"}},
        {"content": {}},                 # no title -> skipped
        {"title": "Two"},
        {"title": "Three"},
    ]
    assert news._parse_news_items(items, limit=2) == ["One"]
