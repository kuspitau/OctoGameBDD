
        do -- zones
          local phantom_zones = { 5600 }
          local zone_locales = { "enUS" }
          for _, locale in pairs(zone_locales) do
            local tbl = pfDB["zones"][locale .. "-turtle"]
            if tbl then
              for _, zid in pairs(phantom_zones) do
                tbl[zid] = nil
              end
            end
          end
        end
        