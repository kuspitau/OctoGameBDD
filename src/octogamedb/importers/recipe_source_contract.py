"""P4-T01 source-shaped spell/recipe identity normalization.

This module deliberately stops before canonical schema design.  It normalizes only the
source fields whose semantics were established from the pinned Tortoise/Vanilla shapes:
Spell effects, SkillLineAbility membership, item spell slots and trainer spell rows.
Recipe identity is anchored to a crafting spell only when the source proves both a
skill-line membership and at least one CREATE_ITEM effect.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

CONTRACT_SCHEMA = "p4-t01-source-contract/1"
SPELL_EFFECT_CREATE_ITEM = 24
SPELL_EFFECT_LEARN_SPELL = 36


class RecipeSourceContractError(ValueError):
    """Raised when a P4-T01 source-shaped snapshot cannot be interpreted safely."""


@dataclass(frozen=True)
class Provenance:
    source_key: str
    source_revision: str
    record_key: str
    slot: int | None = None


@dataclass(frozen=True)
class SpellEffect:
    spell_id: int
    effect_index: int
    effect_id: int
    effect_base_points: int
    effect_die_sides: int
    item_type_id: int | None
    trigger_spell_id: int | None
    provenance: Provenance


@dataclass(frozen=True)
class SpellRecord:
    spell_id: int
    name: str
    rank_text: str | None
    effects: tuple[SpellEffect, ...]
    provenance: Provenance


@dataclass(frozen=True)
class SkillLineMembership:
    record_id: int
    skill_line_id: int
    spell_id: int
    required_skill_value: int
    forward_spell_id: int | None
    min_value: int
    max_value: int
    provenance: Provenance


@dataclass(frozen=True)
class ItemSpellSlot:
    item_id: int
    slot: int
    spell_id: int
    spell_trigger: int
    spell_charges: int
    provenance: Provenance


@dataclass(frozen=True)
class TrainerSpellSource:
    trainer_entry: int
    acquisition_spell_id: int
    spell_cost: int
    required_skill_line_id: int | None
    required_skill_value: int
    required_character_level: int
    provenance: Provenance


@dataclass(frozen=True)
class TeachingItemLink:
    item_id: int
    item_spell_slot: int
    acquisition_spell_id: int
    learn_effect_index: int
    craft_spell_id: int
    provenance: Provenance


@dataclass(frozen=True)
class TrainerTeachingLink:
    trainer_entry: int
    acquisition_spell_id: int
    learn_effect_index: int
    craft_spell_id: int
    required_skill_line_id: int | None
    required_skill_value: int
    required_character_level: int
    provenance: Provenance


@dataclass(frozen=True)
class RecipeIdentity:
    craft_spell_id: int
    profession_memberships: tuple[SkillLineMembership, ...]
    output_effects: tuple[SpellEffect, ...]
    teaching_items: tuple[TeachingItemLink, ...]
    trainer_sources: tuple[TrainerTeachingLink, ...]


@dataclass(frozen=True)
class RecipeSourceContract:
    source_key: str
    source_revision: str
    content_hash: str
    spells: tuple[SpellRecord, ...]
    skill_line_memberships: tuple[SkillLineMembership, ...]
    item_spell_slots: tuple[ItemSpellSlot, ...]
    trainer_spell_sources: tuple[TrainerSpellSource, ...]
    recipes: tuple[RecipeIdentity, ...]


def stable_source_hash(value: Any) -> str:
    """Hash a source-shaped value deterministically without losing slot/order fields."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecipeSourceContractError(f"{field} must be a non-empty string")
    return value.strip()


def _int(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecipeSourceContractError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise RecipeSourceContractError(f"{field} must be >= {minimum}")
    return value


def _optional_positive(value: Any, field: str) -> int | None:
    parsed = _int(value, field, minimum=0)
    return None if parsed == 0 else parsed


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RecipeSourceContractError(f"{field} must be an array")
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecipeSourceContractError(f"{field} must be an object")
    return value


def _provenance(
    source_key: str,
    source_revision: str,
    record_key: str,
    *,
    slot: int | None = None,
) -> Provenance:
    return Provenance(
        source_key=source_key,
        source_revision=source_revision,
        record_key=record_key,
        slot=slot,
    )


def _normalize_spell(
    raw: Mapping[str, Any], source_key: str, source_revision: str
) -> SpellRecord:
    spell_id = _int(raw.get("Id"), "Spell.Id", minimum=1)
    name = _required_text(raw.get("SpellName"), f"Spell[{spell_id}].SpellName")
    raw_rank = raw.get("Rank", "")
    if not isinstance(raw_rank, str):
        raise RecipeSourceContractError(f"Spell[{spell_id}].Rank must be a string")
    rank_text = raw_rank.strip() or None
    record_key = f"Spell:{spell_id}"

    effects: list[SpellEffect] = []
    seen_slots: set[int] = set()
    for raw_effect in _sequence(raw.get("effects", ()), f"Spell[{spell_id}].effects"):
        effect = _mapping(raw_effect, f"Spell[{spell_id}].effect")
        slot = _int(effect.get("effect_index"), "effect_index", minimum=0)
        if slot in seen_slots:
            raise RecipeSourceContractError(f"Spell[{spell_id}] repeats effect slot {slot}")
        seen_slots.add(slot)
        effect_id = _int(effect.get("Effect"), "Effect", minimum=0)
        item_type_id = _optional_positive(effect.get("EffectItemType", 0), "EffectItemType")
        trigger_spell_id = _optional_positive(
            effect.get("EffectTriggerSpell", 0), "EffectTriggerSpell"
        )
        if effect_id == SPELL_EFFECT_CREATE_ITEM and item_type_id is None:
            raise RecipeSourceContractError(
                f"Spell[{spell_id}] CREATE_ITEM slot {slot} has no EffectItemType"
            )
        if effect_id == SPELL_EFFECT_LEARN_SPELL and trigger_spell_id is None:
            raise RecipeSourceContractError(
                f"Spell[{spell_id}] LEARN_SPELL slot {slot} has no EffectTriggerSpell"
            )
        effects.append(
            SpellEffect(
                spell_id=spell_id,
                effect_index=slot,
                effect_id=effect_id,
                effect_base_points=_int(effect.get("EffectBasePoints", 0), "EffectBasePoints"),
                effect_die_sides=_int(effect.get("EffectDieSides", 0), "EffectDieSides"),
                item_type_id=item_type_id,
                trigger_spell_id=trigger_spell_id,
                provenance=_provenance(source_key, source_revision, record_key, slot=slot),
            )
        )
    effects.sort(key=lambda item: item.effect_index)
    return SpellRecord(
        spell_id=spell_id,
        name=name,
        rank_text=rank_text,
        effects=tuple(effects),
        provenance=_provenance(source_key, source_revision, record_key),
    )


def _normalize_membership(
    raw: Mapping[str, Any], source_key: str, source_revision: str
) -> SkillLineMembership:
    record_id = _int(raw.get("id"), "SkillLineAbility.id", minimum=1)
    return SkillLineMembership(
        record_id=record_id,
        skill_line_id=_int(raw.get("skillId"), "SkillLineAbility.skillId", minimum=1),
        spell_id=_int(raw.get("spellId"), "SkillLineAbility.spellId", minimum=1),
        required_skill_value=_int(
            raw.get("req_skill_value", 0), "SkillLineAbility.req_skill_value", minimum=0
        ),
        forward_spell_id=_optional_positive(
            raw.get("forward_spellid", 0), "SkillLineAbility.forward_spellid"
        ),
        min_value=_int(raw.get("min_value", 0), "SkillLineAbility.min_value", minimum=0),
        max_value=_int(raw.get("max_value", 0), "SkillLineAbility.max_value", minimum=0),
        provenance=_provenance(
            source_key, source_revision, f"SkillLineAbility:{record_id}"
        ),
    )


def _normalize_item_slot(
    raw: Mapping[str, Any], source_key: str, source_revision: str
) -> ItemSpellSlot:
    item_id = _int(raw.get("item_id"), "item_id", minimum=1)
    slot = _int(raw.get("slot"), "item spell slot", minimum=0)
    return ItemSpellSlot(
        item_id=item_id,
        slot=slot,
        spell_id=_int(raw.get("SpellId"), "ItemSpell.SpellId", minimum=1),
        spell_trigger=_int(raw.get("SpellTrigger"), "ItemSpell.SpellTrigger", minimum=0),
        spell_charges=_int(raw.get("SpellCharges", 0), "ItemSpell.SpellCharges"),
        provenance=_provenance(
            source_key, source_revision, f"item_template:{item_id}:spell", slot=slot
        ),
    )


def _normalize_trainer(
    raw: Mapping[str, Any], source_key: str, source_revision: str
) -> TrainerSpellSource:
    entry = _int(raw.get("entry"), "npc_trainer.entry", minimum=1)
    acquisition_spell = _int(raw.get("spell"), "npc_trainer.spell", minimum=1)
    reqskill = _optional_positive(raw.get("reqskill", 0), "npc_trainer.reqskill")
    return TrainerSpellSource(
        trainer_entry=entry,
        acquisition_spell_id=acquisition_spell,
        spell_cost=_int(raw.get("spellcost", 0), "npc_trainer.spellcost", minimum=0),
        required_skill_line_id=reqskill,
        required_skill_value=_int(
            raw.get("reqskillvalue", 0), "npc_trainer.reqskillvalue", minimum=0
        ),
        required_character_level=_int(
            raw.get("reqlevel", 0), "npc_trainer.reqlevel", minimum=0
        ),
        provenance=_provenance(
            source_key, source_revision, f"npc_trainer:{entry}:{acquisition_spell}"
        ),
    )


def normalize_recipe_source_snapshot(snapshot: Mapping[str, Any]) -> RecipeSourceContract:
    """Normalize the bounded P4-T01 source shape and derive proven recipe identities.

    Derivation is intentionally conservative.  A recipe exists in this contract only when the same
    native spell is both a SkillLineAbility member and has one or more CREATE_ITEM effects.
    Item and trainer sources become teaching links only when their acquisition spell has a
    LEARN_SPELL effect
    whose target is that crafting spell.
    """

    if snapshot.get("contract_schema") != CONTRACT_SCHEMA:
        raise RecipeSourceContractError(
            f"unsupported contract_schema: {snapshot.get('contract_schema')!r}"
        )
    source_key = _required_text(snapshot.get("source_key"), "source_key")
    source_revision = _required_text(snapshot.get("source_revision"), "source_revision")

    spells = tuple(
        _normalize_spell(_mapping(row, "spell row"), source_key, source_revision)
        for row in _sequence(snapshot.get("spells", ()), "spells")
    )
    spell_by_id: dict[int, SpellRecord] = {}
    for spell in spells:
        if spell.spell_id in spell_by_id:
            raise RecipeSourceContractError(f"duplicate Spell.Id {spell.spell_id}")
        spell_by_id[spell.spell_id] = spell

    memberships = tuple(
        _normalize_membership(_mapping(row, "SkillLineAbility row"), source_key, source_revision)
        for row in _sequence(snapshot.get("skill_line_abilities", ()), "skill_line_abilities")
    )
    membership_ids: set[int] = set()
    for membership in memberships:
        if membership.record_id in membership_ids:
            raise RecipeSourceContractError(
                f"duplicate SkillLineAbility.id {membership.record_id}"
            )
        membership_ids.add(membership.record_id)
        if membership.spell_id not in spell_by_id:
            raise RecipeSourceContractError(
                f"SkillLineAbility[{membership.record_id}] references missing spell "
                f"{membership.spell_id}"
            )

    item_slots = tuple(
        _normalize_item_slot(_mapping(row, "item spell row"), source_key, source_revision)
        for row in _sequence(snapshot.get("item_spells", ()), "item_spells")
    )
    seen_item_slots: set[tuple[int, int]] = set()
    for item_slot in item_slots:
        key = (item_slot.item_id, item_slot.slot)
        if key in seen_item_slots:
            raise RecipeSourceContractError(f"duplicate item spell slot {key}")
        seen_item_slots.add(key)
        if item_slot.spell_id not in spell_by_id:
            raise RecipeSourceContractError(
                f"item {item_slot.item_id} slot {item_slot.slot} references missing spell "
                f"{item_slot.spell_id}"
            )

    trainers = tuple(
        _normalize_trainer(_mapping(row, "trainer row"), source_key, source_revision)
        for row in _sequence(snapshot.get("trainer_spells", ()), "trainer_spells")
    )
    seen_trainers: set[tuple[int, int]] = set()
    for trainer in trainers:
        key = (trainer.trainer_entry, trainer.acquisition_spell_id)
        if key in seen_trainers:
            raise RecipeSourceContractError(f"duplicate trainer spell row {key}")
        seen_trainers.add(key)
        if trainer.acquisition_spell_id not in spell_by_id:
            raise RecipeSourceContractError(
                f"trainer {trainer.trainer_entry} references missing acquisition spell "
                f"{trainer.acquisition_spell_id}"
            )

    memberships_by_spell: dict[int, list[SkillLineMembership]] = {}
    for membership in memberships:
        memberships_by_spell.setdefault(membership.spell_id, []).append(membership)

    learn_targets: dict[int, list[SpellEffect]] = {}
    for spell in spells:
        for effect in spell.effects:
            if effect.effect_id == SPELL_EFFECT_LEARN_SPELL:
                assert effect.trigger_spell_id is not None
                learn_targets.setdefault(effect.trigger_spell_id, []).append(effect)

    recipes: list[RecipeIdentity] = []
    for spell in spells:
        outputs = tuple(
            effect
            for effect in spell.effects
            if effect.effect_id == SPELL_EFFECT_CREATE_ITEM
        )
        profession_memberships = tuple(
            sorted(
                memberships_by_spell.get(spell.spell_id, ()),
                key=lambda item: (item.skill_line_id, item.record_id),
            )
        )
        if not outputs or not profession_memberships:
            continue

        item_links: list[TeachingItemLink] = []
        trainer_links: list[TrainerTeachingLink] = []
        for learn_effect in sorted(
            learn_targets.get(spell.spell_id, ()),
            key=lambda item: (item.spell_id, item.effect_index),
        ):
            acquisition_spell_id = learn_effect.spell_id
            for item_slot in item_slots:
                if item_slot.spell_id != acquisition_spell_id:
                    continue
                item_links.append(
                    TeachingItemLink(
                        item_id=item_slot.item_id,
                        item_spell_slot=item_slot.slot,
                        acquisition_spell_id=acquisition_spell_id,
                        learn_effect_index=learn_effect.effect_index,
                        craft_spell_id=spell.spell_id,
                        provenance=item_slot.provenance,
                    )
                )
            for trainer in trainers:
                if trainer.acquisition_spell_id != acquisition_spell_id:
                    continue
                trainer_links.append(
                    TrainerTeachingLink(
                        trainer_entry=trainer.trainer_entry,
                        acquisition_spell_id=acquisition_spell_id,
                        learn_effect_index=learn_effect.effect_index,
                        craft_spell_id=spell.spell_id,
                        required_skill_line_id=trainer.required_skill_line_id,
                        required_skill_value=trainer.required_skill_value,
                        required_character_level=trainer.required_character_level,
                        provenance=trainer.provenance,
                    )
                )

        recipes.append(
            RecipeIdentity(
                craft_spell_id=spell.spell_id,
                profession_memberships=profession_memberships,
                output_effects=outputs,
                teaching_items=tuple(
                    sorted(
                        item_links,
                        key=lambda item: (
                            item.item_id,
                            item.item_spell_slot,
                            item.acquisition_spell_id,
                            item.learn_effect_index,
                        ),
                    )
                ),
                trainer_sources=tuple(
                    sorted(
                        trainer_links,
                        key=lambda item: (
                            item.trainer_entry,
                            item.acquisition_spell_id,
                            item.learn_effect_index,
                        ),
                    )
                ),
            )
        )

    recipes.sort(key=lambda item: item.craft_spell_id)
    return RecipeSourceContract(
        source_key=source_key,
        source_revision=source_revision,
        content_hash=stable_source_hash(snapshot),
        spells=tuple(sorted(spells, key=lambda item: item.spell_id)),
        skill_line_memberships=tuple(
            sorted(
                memberships,
                key=lambda item: (item.skill_line_id, item.spell_id, item.record_id),
            )
        ),
        item_spell_slots=tuple(sorted(item_slots, key=lambda item: (item.item_id, item.slot))),
        trainer_spell_sources=tuple(
            sorted(trainers, key=lambda item: (item.trainer_entry, item.acquisition_spell_id))
        ),
        recipes=tuple(recipes),
    )
