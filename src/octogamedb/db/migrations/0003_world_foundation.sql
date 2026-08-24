CREATE TABLE maps (
    map_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    map_kind TEXT,
    parent_map_id INTEGER REFERENCES maps(map_id) ON DELETE RESTRICT,
    CHECK (parent_map_id IS NULL OR parent_map_id <> map_id)
);

CREATE INDEX idx_maps_name ON maps(name COLLATE NOCASE);
CREATE INDEX idx_maps_parent_map_id ON maps(parent_map_id);

CREATE TABLE zones (
    zone_id INTEGER PRIMARY KEY,
    map_id INTEGER REFERENCES maps(map_id) ON DELETE RESTRICT,
    parent_zone_id INTEGER REFERENCES zones(zone_id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    CHECK (parent_zone_id IS NULL OR parent_zone_id <> zone_id)
);

CREATE INDEX idx_zones_name ON zones(name COLLATE NOCASE);
CREATE INDEX idx_zones_map_id ON zones(map_id);
CREATE INDEX idx_zones_parent_zone_id ON zones(parent_zone_id);

CREATE TABLE creatures (
    creature_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    level_min INTEGER CHECK (level_min IS NULL OR level_min >= 0),
    level_max INTEGER CHECK (level_max IS NULL OR level_max >= 0),
    faction TEXT,
    classification TEXT,
    creature_type TEXT,
    npc_flags INTEGER,
    CHECK (level_min IS NULL OR level_max IS NULL OR level_min <= level_max)
);

CREATE INDEX idx_creatures_name ON creatures(name COLLATE NOCASE);

CREATE TABLE creature_spawns (
    spawn_id INTEGER PRIMARY KEY,
    spawn_key TEXT NOT NULL UNIQUE CHECK (length(trim(spawn_key)) > 0),
    creature_id INTEGER NOT NULL REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    map_id INTEGER REFERENCES maps(map_id) ON DELETE RESTRICT,
    zone_id INTEGER REFERENCES zones(zone_id) ON DELETE RESTRICT,
    coordinate_space TEXT NOT NULL
        CHECK (coordinate_space IN ('zone_percent', 'world')),
    x REAL NOT NULL,
    y REAL NOT NULL,
    z REAL,
    orientation REAL,
    respawn_seconds INTEGER CHECK (respawn_seconds IS NULL OR respawn_seconds >= 0),
    CHECK (map_id IS NOT NULL OR zone_id IS NOT NULL),
    CHECK (
        coordinate_space <> 'zone_percent'
        OR (
            zone_id IS NOT NULL
            AND x >= 0.0 AND x <= 100.0
            AND y >= 0.0 AND y <= 100.0
        )
    )
);

CREATE INDEX idx_creature_spawns_creature_id ON creature_spawns(creature_id);
CREATE INDEX idx_creature_spawns_zone_id ON creature_spawns(zone_id);
CREATE INDEX idx_creature_spawns_map_id ON creature_spawns(map_id);

CREATE TABLE gameobjects (
    gameobject_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    object_type TEXT
);

CREATE INDEX idx_gameobjects_name ON gameobjects(name COLLATE NOCASE);

CREATE TABLE gameobject_spawns (
    spawn_id INTEGER PRIMARY KEY,
    spawn_key TEXT NOT NULL UNIQUE CHECK (length(trim(spawn_key)) > 0),
    gameobject_id INTEGER NOT NULL REFERENCES gameobjects(gameobject_id) ON DELETE RESTRICT,
    map_id INTEGER REFERENCES maps(map_id) ON DELETE RESTRICT,
    zone_id INTEGER REFERENCES zones(zone_id) ON DELETE RESTRICT,
    coordinate_space TEXT NOT NULL
        CHECK (coordinate_space IN ('zone_percent', 'world')),
    x REAL NOT NULL,
    y REAL NOT NULL,
    z REAL,
    orientation REAL,
    respawn_seconds INTEGER CHECK (respawn_seconds IS NULL OR respawn_seconds >= 0),
    CHECK (map_id IS NOT NULL OR zone_id IS NOT NULL),
    CHECK (
        coordinate_space <> 'zone_percent'
        OR (
            zone_id IS NOT NULL
            AND x >= 0.0 AND x <= 100.0
            AND y >= 0.0 AND y <= 100.0
        )
    )
);

CREATE INDEX idx_gameobject_spawns_gameobject_id ON gameobject_spawns(gameobject_id);
CREATE INDEX idx_gameobject_spawns_zone_id ON gameobject_spawns(zone_id);
CREATE INDEX idx_gameobject_spawns_map_id ON gameobject_spawns(map_id);
