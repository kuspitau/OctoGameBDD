CREATE TABLE quest_objective_sets (
    quest_id INTEGER PRIMARY KEY REFERENCES quests(quest_id) ON DELETE CASCADE,
    selected_set_present INTEGER NOT NULL CHECK (selected_set_present IN (0, 1)),
    selected_member_count INTEGER NOT NULL CHECK (selected_member_count >= 0)
);

CREATE TABLE quest_creature_objectives (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    creature_id INTEGER NOT NULL REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, creature_id)
);
CREATE INDEX idx_quest_creature_objectives_creature
    ON quest_creature_objectives(creature_id, quest_id);

CREATE TABLE quest_gameobject_objectives (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    gameobject_id INTEGER NOT NULL REFERENCES gameobjects(gameobject_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, gameobject_id)
);
CREATE INDEX idx_quest_gameobject_objectives_gameobject
    ON quest_gameobject_objectives(gameobject_id, quest_id);

CREATE TABLE quest_item_objectives (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, item_id)
);
CREATE INDEX idx_quest_item_objectives_item
    ON quest_item_objectives(item_id, quest_id);

CREATE TABLE quest_item_use_objectives (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, item_id)
);
CREATE INDEX idx_quest_item_use_objectives_item
    ON quest_item_use_objectives(item_id, quest_id);

CREATE TABLE area_triggers (
    area_trigger_id INTEGER PRIMARY KEY,
    selected_entry_present INTEGER NOT NULL CHECK (selected_entry_present IN (0, 1)),
    selected_coords_present INTEGER NOT NULL CHECK (selected_coords_present IN (0, 1)),
    selected_location_count INTEGER NOT NULL CHECK (selected_location_count >= 0)
);

CREATE TABLE area_trigger_locations (
    area_trigger_id INTEGER NOT NULL REFERENCES area_triggers(area_trigger_id) ON DELETE CASCADE,
    source_index INTEGER NOT NULL CHECK (source_index > 0),
    zone_id INTEGER NOT NULL REFERENCES zones(zone_id) ON DELETE RESTRICT,
    coordinate_space TEXT NOT NULL CHECK (coordinate_space = 'zone_percent'),
    x REAL NOT NULL CHECK (x >= 0.0 AND x <= 100.0),
    y REAL NOT NULL CHECK (y >= 0.0 AND y <= 100.0),
    PRIMARY KEY (area_trigger_id, source_index)
);
CREATE INDEX idx_area_trigger_locations_zone
    ON area_trigger_locations(zone_id, area_trigger_id);

CREATE TABLE quest_area_trigger_objectives (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    area_trigger_id INTEGER NOT NULL REFERENCES area_triggers(area_trigger_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, area_trigger_id)
);
CREATE INDEX idx_quest_area_trigger_objectives_trigger
    ON quest_area_trigger_objectives(area_trigger_id, quest_id);

CREATE TABLE quest_zone_objectives (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    zone_id INTEGER NOT NULL REFERENCES zones(zone_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, zone_id)
);
CREATE INDEX idx_quest_zone_objectives_zone
    ON quest_zone_objectives(zone_id, quest_id);

CREATE TABLE item_use_target_sets (
    item_id INTEGER PRIMARY KEY REFERENCES items(item_id) ON DELETE CASCADE,
    selected_set_present INTEGER NOT NULL CHECK (selected_set_present IN (0, 1)),
    selected_target_count INTEGER NOT NULL CHECK (selected_target_count >= 0)
);

CREATE TABLE item_use_creature_targets (
    item_id INTEGER NOT NULL REFERENCES item_use_target_sets(item_id) ON DELETE CASCADE,
    creature_id INTEGER NOT NULL REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    spell_id INTEGER NOT NULL CHECK (spell_id >= 0),
    PRIMARY KEY (item_id, creature_id)
);
CREATE INDEX idx_item_use_creature_targets_creature
    ON item_use_creature_targets(creature_id, item_id);

CREATE TABLE item_use_gameobject_targets (
    item_id INTEGER NOT NULL REFERENCES item_use_target_sets(item_id) ON DELETE CASCADE,
    gameobject_id INTEGER NOT NULL REFERENCES gameobjects(gameobject_id) ON DELETE RESTRICT,
    spell_id INTEGER NOT NULL CHECK (spell_id >= 0),
    PRIMARY KEY (item_id, gameobject_id)
);
CREATE INDEX idx_item_use_gameobject_targets_gameobject
    ON item_use_gameobject_targets(gameobject_id, item_id);
