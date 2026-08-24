local dbs = { "quests" }
local function patchtable(base, diff)
  for k, v in pairs(diff) do
    if type(v) == "string" and v == "_" then
      base[k] = nil
    else
      base[k] = v
    end
  end
end
for _, db in pairs(dbs) do
  if pfDB[db]["data-turtle"] then patchtable(pfDB[db]["data"], pfDB[db]["data-turtle"]) end
end

for loc, _ in pairs(pfDB.locales or {}) do
  if pfDB["quests"][loc] and pfDB["quests"][loc.."-turtle"] then
    patchtable(pfDB["quests"][loc], pfDB["quests"][loc.."-turtle"])
  end
end
