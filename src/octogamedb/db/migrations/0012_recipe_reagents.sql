CREATE TABLE recipe_reagents (
    recipe_id INTEGER NOT NULL
        REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
    reagent_index INTEGER NOT NULL CHECK (reagent_index >= 0 AND reagent_index < 8),
    native_item_id INTEGER NOT NULL CHECK (native_item_id > 0),
    item_id INTEGER REFERENCES items(item_id) ON DELETE RESTRICT,
    required_quantity INTEGER NOT NULL CHECK (required_quantity >= 0),
    PRIMARY KEY (recipe_id, reagent_index),
    CHECK (item_id IS NULL OR item_id = native_item_id)
);

CREATE INDEX idx_recipe_reagents_item_id ON recipe_reagents(item_id);
CREATE INDEX idx_recipe_reagents_native_item_id ON recipe_reagents(native_item_id);
