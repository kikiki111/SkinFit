"""画面（web/）とサーバーで同じ意味の定数が、ずれていないかの検査。片方だけ直すと落ちる。"""

import re
from pathlib import Path
from typing import get_args

from app.research import CATEGORY_LABEL
from app.routine import ORDER
from app.schemas import Category

WEB = Path(__file__).resolve().parent.parent / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB / "index.html").read_text(encoding="utf-8")
# 「その他」は画面の選択肢の名前。検索の指示では「スキンケア製品」と呼ぶ
SCREEN_LABEL = {**CATEGORY_LABEL, "other": "その他"}


def _js_object(name: str) -> str:
    return re.search(rf"const {name} = \{{(.*?)\}};", APP_JS, re.S).group(1)


def test_every_category_has_a_label():
    assert set(CATEGORY_LABEL) == set(get_args(Category))


def test_category_labels_on_screen_match_the_server():
    assert dict(re.findall(r'(\w+): "([^"]*)"', _js_object("CATEGORY"))) == SCREEN_LABEL


def test_category_choices_match_the_server():
    select = re.search(r'<select id="cond-category">(.*?)</select>', INDEX_HTML, re.S).group(1)
    assert dict(re.findall(r'<option value="(\w+)">([^<]*)</option>', select)) == SCREEN_LABEL


def test_routine_order_on_screen_matches_the_server():
    assert {k: int(v) for k, v in re.findall(r"(\w+): (\d+)", _js_object("ORDER"))} == ORDER
