CREATE TABLE item_templates (
    item_id INTEGER PRIMARY KEY
        REFERENCES items(item_id) ON DELETE RESTRICT,
    class_id INTEGER NOT NULL CHECK (class_id >= 0),
    subclass_id INTEGER NOT NULL CHECK (subclass_id >= 0),
    quality INTEGER NOT NULL CHECK (quality >= 0),
    inventory_type INTEGER NOT NULL CHECK (inventory_type >= 0),
    item_level INTEGER NOT NULL CHECK (item_level >= 0),
    required_level INTEGER NOT NULL CHECK (required_level >= 0),
    allowable_class_mask INTEGER NOT NULL,
    allowable_race_mask INTEGER NOT NULL,
    required_skill_id INTEGER NOT NULL CHECK (required_skill_id >= 0),
    required_skill_rank INTEGER NOT NULL CHECK (required_skill_rank >= 0),
    required_spell_id INTEGER NOT NULL CHECK (required_spell_id >= 0),
    required_reputation_faction_id INTEGER NOT NULL CHECK (required_reputation_faction_id >= 0),
    required_reputation_rank INTEGER NOT NULL CHECK (required_reputation_rank >= 0),
    armor INTEGER NOT NULL CHECK (armor >= 0),
    holy_resistance INTEGER NOT NULL CHECK (holy_resistance >= 0),
    fire_resistance INTEGER NOT NULL CHECK (fire_resistance >= 0),
    nature_resistance INTEGER NOT NULL CHECK (nature_resistance >= 0),
    frost_resistance INTEGER NOT NULL CHECK (frost_resistance >= 0),
    shadow_resistance INTEGER NOT NULL CHECK (shadow_resistance >= 0),
    arcane_resistance INTEGER NOT NULL CHECK (arcane_resistance >= 0),
    max_durability INTEGER NOT NULL CHECK (max_durability >= 0)
);

CREATE INDEX idx_item_templates_level_quality
ON item_templates(item_level, quality);

CREATE INDEX idx_item_templates_class_subclass
ON item_templates(class_id, subclass_id);

CREATE INDEX idx_item_templates_required_level
ON item_templates(required_level);

CREATE TABLE item_stat_modifiers (
    item_id INTEGER NOT NULL
        REFERENCES item_templates(item_id) ON DELETE CASCADE,
    slot_index INTEGER NOT NULL CHECK (slot_index >= 0 AND slot_index < 10),
    stat_type INTEGER NOT NULL CHECK (stat_type >= 0),
    stat_value INTEGER NOT NULL,
    PRIMARY KEY (item_id, slot_index)
);

CREATE INDEX idx_item_stat_modifiers_type_value
ON item_stat_modifiers(stat_type, stat_value);
