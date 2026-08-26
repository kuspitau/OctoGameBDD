CREATE TABLE recipe_teaching_items (
    recipe_id INTEGER NOT NULL
        REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
    native_item_id INTEGER NOT NULL CHECK (native_item_id > 0),
    item_id INTEGER
        REFERENCES items(item_id) ON DELETE RESTRICT,
    item_spell_slot INTEGER NOT NULL CHECK (item_spell_slot BETWEEN 0 AND 4),
    spell_trigger INTEGER CHECK (spell_trigger IS NULL OR spell_trigger >= 0),
    spell_charges INTEGER,
    acquisition_spell_id INTEGER NOT NULL
        REFERENCES spells(spell_id) ON DELETE RESTRICT,
    learning_proof_kind TEXT NOT NULL CHECK (
        learning_proof_kind IN ('octo_dbc_learn_spell', 'tortoise_spell_learn_spell')
    ),
    learn_effect_index INTEGER CHECK (
        learn_effect_index IS NULL OR learn_effect_index BETWEEN 0 AND 2
    ),
    server_learn_active INTEGER CHECK (
        server_learn_active IS NULL OR server_learn_active IN (0, 1)
    ),
    PRIMARY KEY (
        recipe_id,
        native_item_id,
        item_spell_slot,
        acquisition_spell_id
    ),
    CHECK (item_id IS NULL OR item_id = native_item_id),
    CHECK (
        (learning_proof_kind = 'octo_dbc_learn_spell' AND learn_effect_index IS NOT NULL)
        OR
        (learning_proof_kind = 'tortoise_spell_learn_spell' AND learn_effect_index IS NULL)
    )
);

CREATE INDEX idx_recipe_teaching_items_item_id
ON recipe_teaching_items(item_id);

CREATE INDEX idx_recipe_teaching_items_acquisition_spell
ON recipe_teaching_items(acquisition_spell_id);

CREATE TABLE recipe_trainer_sources (
    recipe_id INTEGER NOT NULL
        REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
    trainer_kind TEXT NOT NULL CHECK (trainer_kind IN ('direct', 'template')),
    native_trainer_entry INTEGER NOT NULL CHECK (native_trainer_entry > 0),
    creature_id INTEGER
        REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    trainer_template_id INTEGER CHECK (
        trainer_template_id IS NULL OR trainer_template_id > 0
    ),
    acquisition_spell_id INTEGER NOT NULL
        REFERENCES spells(spell_id) ON DELETE RESTRICT,
    learning_proof_kind TEXT NOT NULL CHECK (
        learning_proof_kind IN ('octo_dbc_learn_spell', 'tortoise_spell_learn_spell')
    ),
    learn_effect_index INTEGER CHECK (
        learn_effect_index IS NULL OR learn_effect_index BETWEEN 0 AND 2
    ),
    server_learn_active INTEGER CHECK (
        server_learn_active IS NULL OR server_learn_active IN (0, 1)
    ),
    spell_cost INTEGER NOT NULL CHECK (spell_cost >= 0),
    required_skill_line_id INTEGER CHECK (
        required_skill_line_id IS NULL OR required_skill_line_id > 0
    ),
    required_skill_value INTEGER NOT NULL CHECK (required_skill_value >= 0),
    required_character_level INTEGER NOT NULL CHECK (required_character_level >= 0),
    PRIMARY KEY (
        recipe_id,
        trainer_kind,
        native_trainer_entry,
        acquisition_spell_id
    ),
    CHECK (creature_id IS NULL OR creature_id = native_trainer_entry),
    CHECK (
        (trainer_kind = 'direct' AND trainer_template_id IS NULL)
        OR
        (trainer_kind = 'template' AND trainer_template_id IS NOT NULL)
    ),
    CHECK (
        (learning_proof_kind = 'octo_dbc_learn_spell' AND learn_effect_index IS NOT NULL)
        OR
        (learning_proof_kind = 'tortoise_spell_learn_spell' AND learn_effect_index IS NULL)
    )
);

CREATE INDEX idx_recipe_trainer_sources_creature_id
ON recipe_trainer_sources(creature_id);

CREATE INDEX idx_recipe_trainer_sources_template_id
ON recipe_trainer_sources(trainer_template_id);

CREATE INDEX idx_recipe_trainer_sources_acquisition_spell
ON recipe_trainer_sources(acquisition_spell_id);

CREATE TABLE recipe_quest_learning_sources (
    recipe_id INTEGER NOT NULL
        REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
    native_quest_id INTEGER NOT NULL CHECK (native_quest_id > 0),
    quest_id INTEGER
        REFERENCES quests(quest_id) ON DELETE RESTRICT,
    reward_spell_field TEXT NOT NULL CHECK (
        reward_spell_field IN ('RewSpellCast', 'RewSpell')
    ),
    acquisition_spell_id INTEGER NOT NULL
        REFERENCES spells(spell_id) ON DELETE RESTRICT,
    learning_proof_kind TEXT NOT NULL CHECK (
        learning_proof_kind IN ('octo_dbc_learn_spell', 'tortoise_spell_learn_spell')
    ),
    learn_effect_index INTEGER CHECK (
        learn_effect_index IS NULL OR learn_effect_index BETWEEN 0 AND 2
    ),
    server_learn_active INTEGER CHECK (
        server_learn_active IS NULL OR server_learn_active IN (0, 1)
    ),
    PRIMARY KEY (
        recipe_id,
        native_quest_id,
        reward_spell_field,
        acquisition_spell_id
    ),
    CHECK (quest_id IS NULL OR quest_id = native_quest_id),
    CHECK (
        (learning_proof_kind = 'octo_dbc_learn_spell' AND learn_effect_index IS NOT NULL)
        OR
        (learning_proof_kind = 'tortoise_spell_learn_spell' AND learn_effect_index IS NULL)
    )
);

CREATE INDEX idx_recipe_quest_learning_sources_quest_id
ON recipe_quest_learning_sources(quest_id);

CREATE INDEX idx_recipe_quest_learning_sources_acquisition_spell
ON recipe_quest_learning_sources(acquisition_spell_id);
