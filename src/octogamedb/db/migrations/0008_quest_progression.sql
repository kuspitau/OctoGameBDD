ALTER TABLE quests ADD COLUMN quest_level INTEGER;
ALTER TABLE quests ADD COLUMN minimum_level INTEGER;
ALTER TABLE quests ADD COLUMN race_mask INTEGER;
ALTER TABLE quests ADD COLUMN class_mask INTEGER;

CREATE TABLE quest_prerequisite_sets (
    quest_id INTEGER PRIMARY KEY REFERENCES quests(quest_id) ON DELETE CASCADE,
    requirement_mode TEXT NOT NULL CHECK (requirement_mode = 'any_of'),
    selected_set_present INTEGER NOT NULL CHECK (selected_set_present IN (0, 1)),
    selected_member_count INTEGER NOT NULL CHECK (selected_member_count >= 0)
);

CREATE TABLE quest_prerequisite_set_members (
    quest_id INTEGER NOT NULL REFERENCES quest_prerequisite_sets(quest_id) ON DELETE CASCADE,
    member_quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    PRIMARY KEY (quest_id, member_quest_id)
);

CREATE INDEX idx_quest_prerequisite_member_reverse
    ON quest_prerequisite_set_members(member_quest_id, quest_id);

CREATE TABLE quest_close_sets (
    quest_id INTEGER PRIMARY KEY REFERENCES quests(quest_id) ON DELETE CASCADE,
    set_semantics TEXT NOT NULL CHECK (set_semantics = 'exclusive_group_member_set'),
    selected_set_present INTEGER NOT NULL CHECK (selected_set_present IN (0, 1)),
    selected_member_count INTEGER NOT NULL CHECK (selected_member_count >= 0)
);

CREATE TABLE quest_close_set_members (
    quest_id INTEGER NOT NULL REFERENCES quest_close_sets(quest_id) ON DELETE CASCADE,
    member_quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    PRIMARY KEY (quest_id, member_quest_id)
);

CREATE INDEX idx_quest_close_member_reverse
    ON quest_close_set_members(member_quest_id, quest_id);
