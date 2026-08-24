CREATE TABLE vendor_items (
    vendor_creature_id INTEGER NOT NULL
        REFERENCES creatures(creature_id) ON DELETE RESTRICT,
    item_id INTEGER NOT NULL
        REFERENCES items(item_id) ON DELETE RESTRICT,
    PRIMARY KEY (vendor_creature_id, item_id)
);

CREATE INDEX idx_vendor_items_item_id ON vendor_items(item_id);
