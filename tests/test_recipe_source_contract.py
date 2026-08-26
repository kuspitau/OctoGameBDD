from __future__ import annotations

import json
from pathlib import Path

import pytest

from octogamedb.importers.recipe_source_contract import (
    CONTRACT_SCHEMA,
    RecipeSourceContractError,
    normalize_recipe_source_snapshot,
    stable_source_hash,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p4_t01" / "source_contract.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_recipe_identity_preserves_native_ids_slots_and_distinctions() -> None:
    contract = normalize_recipe_source_snapshot(_fixture())

    assert [recipe.craft_spell_id for recipe in contract.recipes] == [1000, 1100]
    forging = contract.recipes[0]
    assert [membership.skill_line_id for membership in forging.profession_memberships] == [164]
    assert forging.profession_memberships[0].required_skill_value == 80
    assert [effect.effect_index for effect in forging.output_effects] == [0, 2]
    assert [effect.item_type_id for effect in forging.output_effects] == [2000, 2001]
    assert forging.output_effects[1].effect_base_points == 1
    assert forging.output_effects[1].effect_die_sides == 2

    assert len(forging.teaching_items) == 1
    teaching = forging.teaching_items[0]
    assert teaching.item_id == 3000
    assert teaching.item_spell_slot == 0
    assert teaching.acquisition_spell_id == 9000
    assert teaching.learn_effect_index == 1
    assert teaching.craft_spell_id == 1000
    assert teaching.provenance.slot == 0

    assert len(forging.trainer_sources) == 1
    trainer = forging.trainer_sources[0]
    assert trainer.acquisition_spell_id == 9001
    assert trainer.craft_spell_id == 1000
    assert trainer.required_skill_line_id == 164
    assert trainer.required_skill_value == 75
    assert trainer.required_character_level == 10

    # The second profession recipe is valid without a teaching item or trainer row.
    alchemy = contract.recipes[1]
    assert alchemy.profession_memberships[0].skill_line_id == 171
    assert alchemy.profession_memberships[0].required_skill_value == 125
    assert alchemy.teaching_items == ()
    assert alchemy.trainer_sources == ()

    # An unrelated second spell slot on the same item remains source evidence, not a recipe link.
    assert [(slot.item_id, slot.slot, slot.spell_id) for slot in contract.item_spell_slots] == [
        (3000, 0, 9000),
        (3000, 3, 9999),
    ]


def test_trainer_requirement_is_not_recipe_skill_requirement() -> None:
    contract = normalize_recipe_source_snapshot(_fixture())
    recipe = contract.recipes[0]

    assert recipe.profession_memberships[0].required_skill_value == 80
    assert recipe.trainer_sources[0].required_skill_value == 75
    assert recipe.trainer_sources[0].required_character_level == 10


def test_source_hash_is_deterministic_and_sensitive_to_slot_order_data() -> None:
    fixture = _fixture()
    first = stable_source_hash(fixture)
    second = stable_source_hash(json.loads(json.dumps(fixture, sort_keys=True)))
    assert first == second
    assert first == "sha256:cf4661faa4e9f8f7ba7d4f38f2dea1175a02eb4f8236638b7b3704da9b59cf14"

    changed = _fixture()
    item_spells = changed["item_spells"]
    assert isinstance(item_spells, list)
    item_spells[0]["slot"] = 1
    assert stable_source_hash(changed) != first


def test_fail_closed_on_unsupported_contract_schema() -> None:
    fixture = _fixture()
    fixture["contract_schema"] = "future-contract/99"
    with pytest.raises(RecipeSourceContractError, match="unsupported contract_schema"):
        normalize_recipe_source_snapshot(fixture)


def test_fail_closed_on_unproven_create_item_target() -> None:
    fixture = _fixture()
    spells = fixture["spells"]
    assert isinstance(spells, list)
    effects = spells[0]["effects"]
    effects[0]["EffectItemType"] = 0
    with pytest.raises(RecipeSourceContractError, match="CREATE_ITEM"):
        normalize_recipe_source_snapshot(fixture)


def test_fail_closed_on_dangling_skill_line_spell() -> None:
    fixture = _fixture()
    memberships = fixture["skill_line_abilities"]
    assert isinstance(memberships, list)
    memberships[0]["spellId"] = 424242
    with pytest.raises(RecipeSourceContractError, match="references missing spell"):
        normalize_recipe_source_snapshot(fixture)


def test_fixture_uses_current_contract_version() -> None:
    assert _fixture()["contract_schema"] == CONTRACT_SCHEMA
