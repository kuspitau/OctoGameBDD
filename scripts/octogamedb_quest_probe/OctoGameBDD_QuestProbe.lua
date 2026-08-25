local PROBE_PREFIX = "OQPB1"
local CLASSICAPI_REVISION = "e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd"
local MAX_QUEUE = 50

local frame = CreateFrame("Frame")
local queue = {}
local queuePos = 1
local currentQuestID = nil
local running = false
local nextRequestAt = nil

local function chat(message)
    if DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("|cffffcc00OctoGameBDD QuestProbe:|r " .. message)
    end
end

local function encode(value)
    value = tostring(value or "")
    return string.gsub(value, "([^%w%-%._ ])", function(character)
        return string.format("%%%02X", string.byte(character))
    end)
end

local function nowUTC()
    if date and time then
        return date("!%Y-%m-%dT%H:%M:%SZ", time())
    end
    return "unknown"
end

local function clientBuild()
    if GetBuildInfo then
        local version, build, buildDate = GetBuildInfo()
        return tostring(version or "") .. "/" .. tostring(build or "") .. "/" .. tostring(buildDate or "")
    end
    return "unknown"
end

local function realmName()
    if GetRealmName then
        return GetRealmName() or "unknown"
    end
    return "unknown"
end

local function ensureDB()
    if not OctoGameBDDQuestProbeDB then
        OctoGameBDDQuestProbeDB = {}
    end
    if not OctoGameBDDQuestProbeDB.records then
        OctoGameBDDQuestProbeDB.records = {}
    end
    if not OctoGameBDDQuestProbeDB.order then
        OctoGameBDDQuestProbeDB.order = {}
    end
    OctoGameBDDQuestProbeDB.format = PROBE_PREFIX
    OctoGameBDDQuestProbeDB.classicapi_reference_revision = CLASSICAPI_REVISION
end

local function addRecord(questID, status, requirements, rewards, choices, srcItemID, errorText)
    ensureDB()
    local parts = {
        PROBE_PREFIX,
        "quest_id=" .. tostring(questID),
        "status=" .. tostring(status),
        "captured_at=" .. encode(nowUTC()),
        "realm=" .. encode(realmName()),
        "client_build=" .. encode(clientBuild()),
        "classicapi_revision=" .. CLASSICAPI_REVISION,
        "requirements=" .. tostring(requirements or ""),
        "reward_items=" .. tostring(rewards or ""),
        "reward_choices=" .. tostring(choices or ""),
        "src_item_id=" .. tostring(srcItemID or ""),
        "error=" .. encode(errorText or "")
    }
    local record = table.concat(parts, "|")
    if not OctoGameBDDQuestProbeDB.records[questID] then
        table.insert(OctoGameBDDQuestProbeDB.order, questID)
    end
    OctoGameBDDQuestProbeDB.records[questID] = record
end

local function positivePairs(list, requireItemKind)
    if type(list) ~= "table" then
        return ""
    end
    local result = {}
    local count = table.getn(list)
    local index
    for index = 1, count do
        local value = list[index]
        if type(value) == "table" then
            local kindOK = true
            if requireItemKind then
                kindOK = value.kind == "item"
            end
            local itemID = tonumber(value.id or value.itemID or 0) or 0
            local amount = tonumber(value.count or value.amount or 0) or 0
            if kindOK and itemID > 0 and amount > 0 then
                table.insert(result, tostring(itemID) .. ":" .. tostring(amount))
            end
        end
    end
    return table.concat(result, ",")
end

local function finishCurrent(status, errorText)
    local questID = currentQuestID
    if questID then
        addRecord(questID, status, "", "", "", "", errorText)
        chat("quest " .. questID .. " -> " .. status .. (errorText and (" (" .. errorText .. ")") or ""))
    end
    currentQuestID = nil
end

local function requestNext()
    nextRequestAt = nil
    if queuePos > table.getn(queue) then
        running = false
        currentQuestID = nil
        chat("capture complete; /reload or log out to flush SavedVariables")
        return
    end
    if not C_QuestLog or type(C_QuestLog.RequestLoadQuestByID) ~= "function" or type(C_QuestLog.GetQuestDetails) ~= "function" then
        running = false
        currentQuestID = queue[queuePos]
        finishCurrent("missing_classicapi", "required C_QuestLog functions are unavailable")
        chat("stopped: ClassicAPI quest functions are unavailable")
        return
    end
    currentQuestID = queue[queuePos]
    queuePos = queuePos + 1
    chat("requesting quest " .. currentQuestID)
    local ok, err = pcall(C_QuestLog.RequestLoadQuestByID, currentQuestID)
    if not ok then
        finishCurrent("request_error", tostring(err))
        nextRequestAt = GetTime() + 0.75
    end
end

local function consumeCurrent(eventQuestID, eventSuccess)
    if not currentQuestID then
        return
    end
    if eventQuestID and tonumber(eventQuestID) and tonumber(eventQuestID) ~= currentQuestID then
        return
    end
    if not eventSuccess then
        finishCurrent("query_failed", "QUEST_DATA_LOAD_RESULT reported failure")
        nextRequestAt = GetTime() + 0.75
        return
    end
    local ok, details = pcall(C_QuestLog.GetQuestDetails, currentQuestID)
    if not ok then
        finishCurrent("details_error", tostring(details))
        nextRequestAt = GetTime() + 0.75
        return
    end
    if type(details) ~= "table" then
        finishCurrent("details_unavailable", "GetQuestDetails returned no table")
        nextRequestAt = GetTime() + 0.75
        return
    end
    local requirements = positivePairs(details.requirements, true)
    local rewards = positivePairs(details.rewardItems, false)
    local choices = positivePairs(details.choiceItems or details.rewardChoices, false)
    local srcItemID = tonumber(details.srcItemID or 0) or 0
    addRecord(
        currentQuestID,
        "success",
        requirements,
        rewards,
        choices,
        srcItemID > 0 and srcItemID or "",
        ""
    )
    chat("quest " .. currentQuestID .. " -> success")
    currentQuestID = nil
    nextRequestAt = GetTime() + 0.75
end

local function startCapture(text)
    if running then
        chat("a capture is already running")
        return
    end
    local ids = {}
    local seen = {}
    local token
    for token in string.gfind(text or "", "%d+") do
        local questID = tonumber(token)
        if questID and questID > 0 and not seen[questID] then
            table.insert(ids, questID)
            seen[questID] = true
        end
    end
    if table.getn(ids) == 0 then
        chat("usage: /oqpb 818 815 40788 40675")
        return
    end
    if table.getn(ids) > MAX_QUEUE then
        chat("refusing " .. table.getn(ids) .. " IDs; maximum per manual run is " .. MAX_QUEUE)
        return
    end
    queue = ids
    queuePos = 1
    currentQuestID = nil
    running = true
    ensureDB()
    requestNext()
end

frame:RegisterEvent("VARIABLES_LOADED")
frame:RegisterEvent("QUEST_DATA_LOAD_RESULT")
frame:SetScript("OnUpdate", function()
    if running and nextRequestAt and GetTime() >= nextRequestAt and not currentQuestID then
        requestNext()
    end
end)

frame:SetScript("OnEvent", function()
    if event == "VARIABLES_LOADED" then
        ensureDB()
        return
    end
    if event == "QUEST_DATA_LOAD_RESULT" and running then
        consumeCurrent(arg1, arg2)
    end
end)

SLASH_OCTOGAMEDBQUESTPROBE1 = "/oqpb"
SlashCmdList["OCTOGAMEDBQUESTPROBE"] = startCapture
