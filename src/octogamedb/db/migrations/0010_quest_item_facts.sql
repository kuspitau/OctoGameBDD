CREATE TABLE quest_required_items (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (quest_id, item_id)
);
CREATE INDEX idx_quest_required_items_item
    ON quest_required_items(item_id, quest_id);

CREATE TABLE quest_required_sources (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE RESTRICT,
    raw_source_count INTEGER NOT NULL CHECK (raw_source_count >= 0),
    PRIMARY KEY (quest_id, item_id)
);
CREATE INDEX idx_quest_required_sources_item
    ON quest_required_sources(item_id, quest_id);

CREATE TABLE quest_provided_items (
    quest_id INTEGER PRIMARY KEY REFERENCES quests(quest_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE RESTRICT,
    quantity INTEGER CHECK (quantity IS NULL OR quantity > 0)
);
CREATE INDEX idx_quest_provided_items_item
    ON quest_provided_items(item_id, quest_id);

CREATE TABLE quest_reward_items (
    quest_id INTEGER NOT NULL REFERENCES quests(quest_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (quest_id, item_id)
);
CREATE INDEX idx_quest_reward_items_item
    ON quest_reward_items(item_id, quest_id);

CREATE TABLE quest_choice_reward_sets (
    quest_id INTEGER PRIMARY KEY REFERENCES quests(quest_id) ON DELETE CASCADE,
    choice_semantics TEXT NOT NULL DEFAULT 'choose_one'
        CHECK (choice_semantics = 'choose_one'),
    selected_member_count INTEGER NOT NULL CHECK (selected_member_count >= 0)
);

CREATE TABLE quest_choice_reward_items (
    quest_id INTEGER NOT NULL REFERENCES quest_choice_reward_sets(quest_id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(item_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (quest_id, item_id)
);
CREATE INDEX idx_quest_choice_reward_items_item
    ON quest_choice_reward_items(item_id, quest_id);
