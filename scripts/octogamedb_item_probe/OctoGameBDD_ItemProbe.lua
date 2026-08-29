-- OctoGameBDD P6-T02 bounded item query probe for Vanilla 1.12-compatible clients.
-- One explicit native item ID is outstanding at a time. Timeouts remain unknown.

local PROBE_VERSION = 1
local POLL_SECONDS = 0.20
local RETRY_SECONDS = 3.0
local TIMEOUT_SECONDS = 15.0
local MAX_ATTEMPTS = 5
local MAX_IDS = 20

OctoGameBDD_ItemProbeDB = OctoGameBDD_ItemProbeDB or {}
OctoGameBDD_ItemProbeExport = OctoGameBDD_ItemProbeExport or ""

local frame = CreateFrame("Frame", "OctoGameBDD_ItemProbeFrame", UIParent)
frame.elapsed = 0

local function chat(message)
  DEFAULT_CHAT_FRAME:AddMessage("|cff33ffccOctoGameBDD ItemProbe|r " .. message)
end

local function safe_token(value)
  value = tostring(value or "")
  value = string.gsub(value, "[^%w%._%-]", "_")
  return value
end

local function join_ids(ids)
  local out = ""
  for index = 1, table.getn(ids) do
    if out ~= "" then out = out .. "," end
    out = out .. tostring(ids[index])
  end
  return out
end

local function update_export()
  local capture = OctoGameBDD_ItemProbeDB.capture
  if not capture then
    OctoGameBDD_ItemProbeExport = "v=1|complete=0|ids=|results="
    return
  end

  local results = ""
  for index = 1, table.getn(capture.ids) do
    local item_id = capture.ids[index]
    local result = capture.results[item_id]
    if result then
      if results ~= "" then results = results .. "," end
      results = results .. tostring(item_id) .. ":" .. safe_token(result.initial) .. ":" .. safe_token(result.status)
    end
  end

  local version, build = GetBuildInfo()
  OctoGameBDD_ItemProbeExport =
    "v=" .. tostring(PROBE_VERSION) ..
    "|probe_id=" .. safe_token(capture.probe_id) ..
    "|started=" .. safe_token(capture.started) ..
    "|realm=" .. safe_token(GetRealmName()) ..
    "|character=" .. safe_token(UnitName("player")) ..
    "|locale=" .. safe_token(GetLocale()) ..
    "|client_version=" .. safe_token(version) ..
    "|client_build=" .. safe_token(build) ..
    "|ids=" .. join_ids(capture.ids) ..
    "|results=" .. results ..
    "|complete=" .. (capture.complete and "1" or "0")
end

local function issue_tooltip_query(item_id)
  -- pfQuest uses the same ItemRefTooltip:SetHyperlink route to populate an item name on clean WDB.
  ItemRefTooltip:SetOwner(UIParent, "ANCHOR_PRESERVE")
  ItemRefTooltip:SetHyperlink("item:" .. tostring(item_id) .. ":0:0:0")
  ItemRefTooltip:Hide()
end

local function finish_current(status)
  local capture = OctoGameBDD_ItemProbeDB.capture
  if not capture or not capture.active_id then return end
  local result = capture.results[capture.active_id]
  result.status = status
  result.finished_gettime = GetTime()
  capture.active_id = nil
  capture.deadline = nil
  capture.index = capture.index + 1
  update_export()
end

local function advance()
  local capture = OctoGameBDD_ItemProbeDB.capture
  if not capture or capture.complete then return end

  if capture.active_id then return end
  if capture.index > table.getn(capture.ids) then
    capture.complete = true
    capture.finished = time()
    update_export()
    chat("complete. Logout or exit the client so SavedVariables and WDB are flushed.")
    return
  end

  local item_id = capture.ids[capture.index]
  local name = GetItemInfo(item_id)
  if name then
    capture.results[item_id] = {
      initial = "present",
      status = "already_cached",
      started_gettime = GetTime(),
      finished_gettime = GetTime(),
    }
    capture.index = capture.index + 1
    update_export()
    chat("item " .. item_id .. " already cached; freshness not proven.")
    advance()
    return
  end

  capture.results[item_id] = {
    initial = "missing",
    status = "pending",
    started_gettime = GetTime(),
  }
  capture.active_id = item_id
  capture.deadline = GetTime() + TIMEOUT_SECONDS
  capture.next_retry = GetTime() + RETRY_SECONDS
  capture.attempts = 1
  issue_tooltip_query(item_id)
  update_export()
  chat("querying item " .. item_id .. " (one outstanding request).")
end

local function parse_ids(text)
  local ids = {}
  local seen = {}
  for token in string.gfind(text or "", "(%d+)") do
    local item_id = tonumber(token)
    if item_id and item_id > 0 and not seen[item_id] then
      table.insert(ids, item_id)
      seen[item_id] = true
      if table.getn(ids) >= MAX_IDS then break end
    end
  end
  return ids
end

local function start_probe(text)
  local ids = parse_ids(text)
  if table.getn(ids) == 0 then
    chat("usage: /ogitemprobe start <id1,id2,...> (maximum " .. MAX_IDS .. ")")
    return
  end

  OctoGameBDD_ItemProbeDB.capture = {
    probe_id = tostring(time()) .. "-" .. safe_token(UnitName("player")),
    started = time(),
    ids = ids,
    index = 1,
    active_id = nil,
    deadline = nil,
    complete = false,
    results = {},
  }
  update_export()
  chat("started bounded probe for " .. table.getn(ids) .. " explicit IDs.")
  advance()
end

local function resume_probe()
  local capture = OctoGameBDD_ItemProbeDB.capture
  if not capture or not capture.ids or table.getn(capture.ids) == 0 then
    chat("no saved probe to resume.")
    return
  end
  if capture.complete then
    chat("saved probe is already complete.")
    update_export()
    return
  end
  if capture.active_id then
    local item_id = capture.active_id
    local name = GetItemInfo(item_id)
    if name then
      finish_current("loaded_after_query")
    else
      capture.deadline = GetTime() + TIMEOUT_SECONDS
      capture.next_retry = GetTime() + RETRY_SECONDS
      capture.attempts = (capture.attempts or 0) + 1
      issue_tooltip_query(item_id)
    end
  end
  update_export()
  advance()
  chat("resumed bounded probe.")
end

frame:SetScript("OnUpdate", function()
  this.elapsed = (this.elapsed or 0) + arg1
  if this.elapsed < POLL_SECONDS then return end
  this.elapsed = 0

  local capture = OctoGameBDD_ItemProbeDB.capture
  if not capture or capture.complete or not capture.active_id then return end

  local item_id = capture.active_id
  local name = GetItemInfo(item_id)
  if name then
    finish_current("loaded_after_query")
    chat("item " .. item_id .. " loaded after explicit query.")
    advance()
    return
  end

  if capture.deadline and GetTime() >= capture.deadline then
    finish_current("timeout_unknown")
    chat("item " .. item_id .. " timed out; result remains unknown.")
    advance()
    return
  end

  -- Bounded retry of the same single outstanding ID. This follows the proven pfQuest
  -- SetHyperlink route while avoiding a tight request loop.
  if capture.next_retry and GetTime() >= capture.next_retry and (capture.attempts or 0) < MAX_ATTEMPTS then
    issue_tooltip_query(item_id)
    capture.attempts = (capture.attempts or 0) + 1
    capture.next_retry = GetTime() + RETRY_SECONDS
    update_export()
  end
end)

SLASH_OCTOGAMEDBITEMPROBE1 = "/ogitemprobe"
SlashCmdList["OCTOGAMEDBITEMPROBE"] = function(msg)
  msg = msg or ""
  local _, _, command, rest = string.find(msg, "^%s*(%S+)%s*(.-)%s*$")
  command = string.lower(command or "")
  if command == "start" then
    start_probe(rest)
  elseif command == "resume" then
    resume_probe()
  elseif command == "status" then
    local capture = OctoGameBDD_ItemProbeDB.capture
    if not capture then
      chat("no active/saved probe.")
    else
      chat(
        "status index=" .. tostring(capture.index) .. "/" .. tostring(table.getn(capture.ids)) ..
        " active=" .. tostring(capture.active_id or "none") ..
        " complete=" .. tostring(capture.complete)
      )
    end
    update_export()
  else
    chat("commands: start <id1,id2,...> | resume | status")
  end
end

update_export()
