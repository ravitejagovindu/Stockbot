"""The contract is the single source: every example file validates against the BFF's pydantic models, and the models' fields match openapi.yaml."""
from __future__ import annotations

import pytest
import yaml
from conftest import EXAMPLES, REPO, example

from bff import models as M

PREFIX_MODEL = {"today_": M.Today, "account_": M.Account, "positions_": M.Positions, "trades_": M.Trades, "health_": M.Health, "error_": M.ErrorResponse}
FILES = sorted(p.name for p in EXAMPLES.glob("*.json"))


def model_for(name: str):
    return next(m for p, m in PREFIX_MODEL.items() if name.startswith(p))


def test_there_are_example_files():
    assert len(FILES) >= 28


@pytest.mark.parametrize("name", FILES)
def test_example_validates_against_the_bff_model(name):
    model_for(name).model_validate(example(name))           # extra keys, wrong types, bad enums, a wrong offset: all raise


@pytest.mark.parametrize("name", FILES)
def test_example_round_trips_without_losing_a_field(name):
    body = example(name)
    again = model_for(name).model_validate(body).model_dump(mode="json")
    assert again == body, "the model adds or drops a field relative to the example"


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load((REPO / "docs" / "android" / "contract" / "openapi.yaml").read_text(encoding="utf-8"))["components"]["schemas"]


def props(schema: dict, spec: dict) -> set:
    out = set()
    for part in schema.get("allOf", [schema]):
        if "$ref" in part:
            out |= props(spec[part["$ref"].split("/")[-1]], spec)
        out |= set(part.get("properties", {}))
    return out


@pytest.mark.parametrize("schema,model", [("Today", M.Today), ("Health", M.Health), ("Ticket", M.Ticket), ("BlockedItem", M.BlockedItem), ("PendingFill", M.PendingFill),
                                          ("Account", M.Account), ("Positions", M.Positions), ("Trades", M.Trades), ("Error", M.ErrorResponse)])
def test_model_fields_match_openapi(schema, model, spec):
    assert props(spec[schema], spec) == set(model.model_fields), schema


def test_nested_openapi_objects_match_models(spec):
    acc = spec["Account"]["allOf"][1]["properties"]
    assert set(acc["summary"]["properties"]) == set(M.AccountSummary.model_fields)
    assert set(acc["curve"]["items"]["properties"]) == set(M.CurvePoint.model_fields)
    assert set(acc["marks"]["properties"]) == set(M.Marks.model_fields)
    assert set(spec["Positions"]["allOf"][1]["properties"]["positions"]["items"]["properties"]) == set(M.Position.model_fields)
    tr = spec["Trades"]["allOf"][1]["properties"]
    assert set(tr["trades"]["items"]["properties"]) == set(M.ClosedTrade.model_fields)
    assert set(tr["stats"]["properties"]) == set(M.TradeStats.model_fields)


def test_enums_in_openapi_match_models(spec):
    from typing import get_args
    assert set(spec["BlockReason"]["enum"]) == set(get_args(M.BlockReason))
    assert set(spec["ExitReason"]["enum"]) == set(get_args(M.ExitReason))
    assert set(spec["Side"]["enum"]) == set(get_args(M.Side))


def test_a_field_the_contract_does_not_list_is_refused():
    body = example("today_empty.json")
    body["surprise"] = 1
    with pytest.raises(Exception):
        M.Today.model_validate(body)
