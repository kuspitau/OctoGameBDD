CREATE TABLE items (
    item_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
);

CREATE INDEX idx_items_name ON items(name COLLATE NOCASE);

CREATE TABLE creature_loot (
    creature_id INTEGER NOT NULL
        REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    item_id INTEGER NOT NULL
        REFERENCES items(item_id) ON DELETE RESTRICT,
    chance_percent REAL NOT NULL CHECK (chance_percent >= 0.0 AND chance_percent <= 100.0),
    PRIMARY KEY (creature_id, item_id)
);

CREATE INDEX idx_creature_loot_item_id ON creature_loot(item_id);

CREATE TABLE gameobject_loot (
    gameobject_id INTEGER NOT NULL
        REFERENCES gameobjects(gameobject_id) ON DELETE RESTRICT,
    item_id INTEGER NOT NULL
        REFERENCES items(item_id) ON DELETE RESTRICT,
    chance_percent REAL NOT NULL CHECK (chance_percent >= 0.0 AND chance_percent <= 100.0),
    PRIMARY KEY (gameobject_id, item_id)
);

CREATE INDEX idx_gameobject_loot_item_id ON gameobject_loot(item_id);
