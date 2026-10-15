"""Geminiに渡す構造化出力のスキーマが、google-genaiの変換を通るか。

通らないスキーマは、Geminiを呼ぶ前にSDKの中で例外になる。他のテストはGeminiをモックにするため、ここで別に検査する。
"""

import ast
import importlib
from pathlib import Path

import pytest
from google.genai import _transformers
from pydantic import BaseModel

APP = Path(__file__).resolve().parent.parent / "app"


def _func_name(node: ast.expr) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)


def _gemini_schemas() -> dict[str, type[BaseModel]]:
    """app/ で generate_json と output_schema= に渡しているスキーマを集める。

    research._structure のように、受け取ったスキーマを generate_json へ受け流す関数は、その呼び出し元までたどる。
    """
    trees = {".".join(p.relative_to(APP.parent).with_suffix("").parts): ast.parse(p.read_text(encoding="utf-8"))
             for p in sorted(APP.rglob("*.py"))}
    forwarders = {"generate_json": 1}  # 関数名 → スキーマを受け取る引数の位置
    for tree in trees.values():
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            params = [a.arg for a in fn.args.args]
            for call in ast.walk(fn):
                if (isinstance(call, ast.Call) and _func_name(call.func) == "generate_json" and len(call.args) > 1
                        and isinstance(call.args[1], ast.Name) and call.args[1].id in params):
                    forwarders[fn.name] = params.index(call.args[1].id)
    found = {}
    for module_name, tree in trees.items():
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            pos = forwarders.get(_func_name(call.func))
            args = [call.args[pos]] if pos is not None and len(call.args) > pos else []
            args += [k.value for k in call.keywords if k.arg == "output_schema"]
            for arg in args:
                if not isinstance(arg, ast.Name):
                    continue
                schema = getattr(importlib.import_module(module_name), arg.id, None)
                if isinstance(schema, type) and issubclass(schema, BaseModel):
                    found[f"{module_name}.{arg.id}"] = schema
    return found


SCHEMAS = _gemini_schemas()


def test_schemas_are_collected_from_every_call_style():
    # generate_json の直接呼び出し・_structure 経由・ADKの output_schema= の3通りを拾えていること
    assert {"app.workflows.agents._IntakeOutput", "app.research._FactsOut", "app.workflows.agents.SelectOutput"} <= set(SCHEMAS)


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_converts_for_gemini(name):
    # SDKが送信前に行う変換と同じ処理。未対応のキーワード（例：Field(gt=0) の exclusiveMinimum）があると落ちる
    _transformers.t_schema(None, SCHEMAS[name])
