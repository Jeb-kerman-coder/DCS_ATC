-- =============================================================
-- DCS ATC / WINGMAN - automatic loader
-- Lives in  Saved Games\DCS\Scripts\Hooks  (put there by the DCS ATC app).
-- DCS runs it on its own at startup; every time a mission finishes loading
-- it starts the bridge script, so nothing has to be added in the Mission
-- Editor. Missions that already include the bridge are fine (it only runs
-- once per mission).
-- =============================================================

local wingman_loader = {}

function wingman_loader.onMissionLoadEnd()

    local ok, err = pcall(function()

        local script = lfs.writedir() .. "Scripts\\WingmanBridge\\wingman_bridge.lua"

        local file = io.open(script, "r")

        if not file then
            net.log("WINGMAN LOADER: bridge script not found: " .. script)
            return
        end

        file:close()

        -- DCS install folder, so the bridge can find lua-socket.dll
        -- wherever DCS is installed (Steam, other drive, ...)
        local dcs_dir = lfs.currentdir()

        local code = string.format(
            "WINGMAN_DCS_DIR = %q; "
            .. "local f, e = loadfile(%q); "
            .. "if f then f() else env.info('WINGMAN LOADER: ' .. tostring(e)) end",
            dcs_dir, script
        )

        net.dostring_in("mission", "a_do_script(" .. string.format("%q", code) .. ")")

        net.log("WINGMAN LOADER: bridge started for this mission")

    end)

    if not ok then
        net.log("WINGMAN LOADER: failed - " .. tostring(err))
    end
end

-- Tell the DCS ATC app where DCS is installed (it needs to find
-- Scripts\\MissionScripting.lua), whatever drive / Steam library that is.
pcall(function()

    local folder = lfs.writedir() .. "Scripts\\WingmanBridge\\"

    lfs.mkdir(lfs.writedir() .. "Scripts")
    lfs.mkdir(folder)

    local file = io.open(folder .. "dcs_install_dir.txt", "w")

    if file then
        file:write(lfs.currentdir())
        file:close()
    end

end)

DCS.setUserCallbacks(wingman_loader)

net.log("WINGMAN LOADER: ready")
