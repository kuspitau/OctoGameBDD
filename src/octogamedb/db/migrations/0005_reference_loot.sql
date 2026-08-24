CREATE TABLE loot_references (
    reference_loot_id INTEGER PRIMARY KEY
);

CREATE TABLE item_reference_loot (
    item_id INTEGER NOT NULL
        REFERENCES items(item_id) ON DELETE RESTRICT,
    reference_loot_id INTEGER NOT NULL
        REFERENCES loot_references(reference_loot_id) ON DELETE RESTRICT,
    chance_percent REAL NOT NULL CHECK (chance_percent >= 0.0 AND chance_percent <= 100.0),
    PRIMARY KEY (item_id, reference_loot_id)
);

CREATE INDEX idx_item_reference_loot_reference_id
    ON item_reference_loot(reference_loot_id);

CREATE TABLE reference_loot_creatures (
    reference_loot_id INTEGER NOT NULL
        REFERENCES loot_references(reference_loot_id) ON DELETE RESTRICT,
    creature_id INTEGER NOT NULL
        REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    PRIMARY KEY (reference_loot_id, creature_id)
);

CREATE INDEX idx_reference_loot_creatures_creature_id
    ON reference_loot_creatures(creature_id);

CREATE TABLE reference_loot_gameobjects (
    reference_loot_id INTEGER NOT NULL
        REFERENCES loot_references(reference_loot_id) ON DELETE RESTRICT,
    gameobject_id INTEGER NOT NULL
        REFERENCES gameobjects(gameobject_id) ON DELETE RESTRICT,
    PRIMARY KEY (reference_loot_id, gameobject_id)
);

CREATE INDEX idx_reference_loot_gameobjects_gameobject_id
    ON reference_loot_gameobjects(gameobject_id);
