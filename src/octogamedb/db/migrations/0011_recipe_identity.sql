CREATE TABLE spells (
    spell_id INTEGER PRIMARY KEY,
    name TEXT CHECK (name IS NULL OR length(trim(name)) > 0),
    rank_text TEXT CHECK (rank_text IS NULL OR length(trim(rank_text)) > 0)
);

CREATE INDEX idx_spells_name ON spells(name COLLATE NOCASE);

CREATE TABLE skill_lines (
    skill_line_id INTEGER PRIMARY KEY,
    name TEXT CHECK (name IS NULL OR length(trim(name)) > 0)
);

CREATE INDEX idx_skill_lines_name ON skill_lines(name COLLATE NOCASE);

CREATE TABLE recipes (
    recipe_id INTEGER PRIMARY KEY,
    crafting_spell_id INTEGER NOT NULL UNIQUE
        REFERENCES spells(spell_id) ON DELETE RESTRICT,
    CHECK (recipe_id = crafting_spell_id)
);

CREATE TABLE recipe_skill_lines (
    recipe_id INTEGER NOT NULL
        REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
    skill_line_ability_id INTEGER NOT NULL,
    skill_line_id INTEGER NOT NULL
        REFERENCES skill_lines(skill_line_id) ON DELETE RESTRICT,
    required_skill_value INTEGER NOT NULL CHECK (required_skill_value >= 0),
    PRIMARY KEY (recipe_id, skill_line_ability_id),
    UNIQUE (skill_line_ability_id)
);

CREATE INDEX idx_recipe_skill_lines_skill_line_id
    ON recipe_skill_lines(skill_line_id);

CREATE TABLE recipe_outputs (
    recipe_id INTEGER NOT NULL
        REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
    effect_index INTEGER NOT NULL CHECK (effect_index >= 0),
    native_item_id INTEGER NOT NULL CHECK (native_item_id > 0),
    item_id INTEGER REFERENCES items(item_id) ON DELETE RESTRICT,
    PRIMARY KEY (recipe_id, effect_index),
    CHECK (item_id IS NULL OR item_id = native_item_id)
);

CREATE INDEX idx_recipe_outputs_item_id ON recipe_outputs(item_id);
CREATE INDEX idx_recipe_outputs_native_item_id ON recipe_outputs(native_item_id);
