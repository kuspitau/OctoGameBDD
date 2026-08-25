-- later bounded update wins only when its source guard matches
UPDATE `quest_template`
SET `RewItemCount1` = 2
WHERE `entry` = 818
  AND `RewItemId1` = 3001;

-- guard mismatch must be a deterministic no-op, matching MySQL UPDATE semantics
UPDATE `quest_template`
SET `ReqItemCount1` = 99
WHERE `entry` = 815
  AND `ReqItemId1` = 999999;
