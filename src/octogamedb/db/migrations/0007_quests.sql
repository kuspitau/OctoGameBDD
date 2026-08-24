CREATE TABLE quests (
    quest_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
);

CREATE TABLE quest_creature_endpoints (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    endpoint_kind TEXT NOT NULL CHECK (endpoint_kind IN ('giver', 'finisher')),
    creature_id INTEGER NOT NULL REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, endpoint_kind, creature_id)
);

CREATE INDEX idx_quest_creature_endpoints_creature
    ON quest_creature_endpoints(creature_id, endpoint_kind, quest_id);

CREATE TABLE quest_gameobject_endpoints (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    endpoint_kind TEXT NOT NULL CHECK (endpoint_kind IN ('giver', 'finisher')),
    gameobject_id INTEGER NOT NULL REFERENCES gameobjects(gameobject_id) ON DELETE RESTRICT,
    PRIMARY KEY (quest_id, endpoint_kind, gameobject_id)
);

CREATE INDEX idx_quest_gameobject_endpoints_gameobject
    ON quest_gameobject_endpoints(gameobject_id, endpoint_kind, quest_id);
