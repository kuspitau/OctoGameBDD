"""Validate the tracked P4-T01 source-shaped contract fixture without external data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from octogamedb.importers.recipe_source_contract import normalize_recipe_source_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/p4_t01/source_contract.json"),
    )
    args = parser.parse_args()

    snapshot = json.loads(args.fixture.read_text(encoding="utf-8"))
    contract = normalize_recipe_source_snapshot(snapshot)
    payload = {
        "status": "ok",
        "source_key": contract.source_key,
        "source_revision": contract.source_revision,
        "content_hash": contract.content_hash,
        "spell_count": len(contract.spells),
        "skill_line_membership_count": len(contract.skill_line_memberships),
        "item_spell_slot_count": len(contract.item_spell_slots),
        "trainer_spell_source_count": len(contract.trainer_spell_sources),
        "recipe_count": len(contract.recipes),
        "recipe_ids": [recipe.craft_spell_id for recipe in contract.recipes],
        "recipe_summaries": [
            {
                "craft_spell_id": recipe.craft_spell_id,
                "skill_line_ids": [
                    membership.skill_line_id for membership in recipe.profession_memberships
                ],
                "required_skill_values": [
                    membership.required_skill_value for membership in recipe.profession_memberships
                ],
                "output_slots": [effect.effect_index for effect in recipe.output_effects],
                "output_item_ids": [effect.item_type_id for effect in recipe.output_effects],
                "teaching_item_ids": [link.item_id for link in recipe.teaching_items],
                "trainer_entries": [link.trainer_entry for link in recipe.trainer_sources],
            }
            for recipe in contract.recipes
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
