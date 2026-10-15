"""画面（web/app.js）への差し込みの無害化漏れを見つける。

APIから来る文字列の項目（製品名・要約・出典URLなど）を、テンプレート文字列の ${...} で差し込むときは、
esc()（旧名 escapeAttr）を通すこと。link() はURL検証とHTMLエスケープを内部で行う。
数値の項目（件数・順位など）は対象外。この簡易検査に加えて、frontend.test.mjs で
エスケープとURL制限の動作を検証する。JavaScriptの完全な静的解析ではない。
"""

import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "web" / "app.js"
# APIの文字列の項目名（app/schemas.py の文字列フィールド）
STRING_FIELDS = (
    "name|brand|summary|text|title|url|note|label|target|reason|visible_text|status_message|maker_description|"
    "price_note|why_top|rank_reason|detail|canonical|publisher|queries|details|concern_label|keep_note|"
    "stickiness_label|order_note|researched_at|volume_text|name_guess|alternatives|media|ingredients|tradeoffs|unverified"
)
FIELD_ACCESS = re.compile(rf"\.\s*({STRING_FIELDS})\b")
SAFE_WRAP = re.compile(r"^\s*(esc|escapeAttr|link)\(")
SAFE_CALL = re.compile(r"\b(?:esc|escapeAttr|link)\(")
INTERP = re.compile(r"\$\{((?:[^{}]|\{[^{}]*\})*)\}")


def main() -> int:
    problems = []
    for lineno, line in enumerate(APP.read_text(encoding="utf-8").splitlines(), 1):
        if "safe-html:" in line:  # 理由を書いた例外（Googleの検索候補など）
            continue
        for expr in INTERP.findall(line):
            if SAFE_WRAP.match(expr) or SAFE_CALL.search(expr):
                continue
            if FIELD_ACCESS.search(expr):
                problems.append(f"web/app.js:{lineno}: ${{{expr.strip()[:80]}}}")
    if problems:
        print("無害化を通していない差し込みがあります（esc() を通してください）:")
        print("\n".join(problems))
        return 1
    print("画面の差し込み：無害化漏れなし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
