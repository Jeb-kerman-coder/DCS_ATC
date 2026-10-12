-- =============================================================
-- DCS FRIENDLY AIRCRAFT TELEMETRY BRIDGE  +  WINGMAN COMMAND LINK
-- Out: broadcasts all friendly airplanes + helicopters over UDP as JSON
-- In : receives orders from the Python wingman (flight, RTB, ROE,
--      orbit, follow, intercept/attack, radar, ...) and applies them
--      to an AI aircraft
-- Ev : reports weapon shots, takeoff/landing, kills and radar contacts
--      back to Python (UDP 5018) so the wingman can call them out
-- AWACS: sends YOUR position + the air picture (bandits) to the ATC app
--      (UDP 5015) so AWACS / GCI can give bogey dopes, pictures and tasking
-- =============================================================

-- Run once per mission (the auto-loader hook AND a manual "Do Script File"
-- must not both start it - the command port can only be bound once).
if WINGMAN_BRIDGE_LOADED then
    return
end
WINGMAN_BRIDGE_LOADED = true

local UDP_HOST = "127.0.0.1"
local UDP_PORT = 5016
local UPDATE_INTERVAL = 0.5
local UNITS_PER_PACKET = 25      -- keeps each datagram well under the UDP limit

-- Which coalition counts as "friendly"?
--   coalition.side.BLUE / coalition.side.RED  -> fixed
--   nil                                       -> auto-detect from the first human player
local FRIENDLY_SIDE = nil

local CATEGORIES = {
    Group.Category.AIRPLANE,
    Group.Category.HELICOPTER
}

-- ---- command link (Python -> DCS) ----------------------------
local CMD_HOST = "127.0.0.1"
local CMD_PORT = 5017
local CMD_POLL_INTERVAL = 0.2    -- seconds between checks for new orders
local MAX_CMDS_PER_POLL = 20

-- Headings you speak are MAGNETIC (what the cockpit shows). DCS works in
-- TRUE headings. Set this to the theatre's magnetic variation, EAST positive
-- (true = magnetic + variation). Leave 0 if you don't care about a few degrees.
local MAGNETIC_VARIATION_DEG = 0

-- Order limits / behaviour
local MIN_ALT_FT = 500
local MAX_ALT_FT = 60000
local MIN_SPEED_KTS = 100
local MAX_SPEED_KTS = 1500
local ROUTE_LEG_M = 200000       -- how far ahead the "fly this heading" waypoint is placed
local REISSUE_MIN_INTERVAL = 8   -- seconds between route refreshes
local HEADING_TOLERANCE_DEG = 3  -- re-aim the route if the track drifts more than this

-- Pursuit (intercept / merge / attack / investigate)
local PURSUE_REFRESH = 6         -- seconds between route refreshes while chasing
local PURSUE_SPEED_KTS = 550
local INVESTIGATE_STOP_NM = 2    -- investigate closes to this range, then flies straight
local POINT_ARRIVE_NM = 3        -- "fly to point" orders end this close to the point
local ENGAGE_MAX_DIST_M = 100000 -- how far out the AI may pick off air targets en route
local DEFAULT_CONTACT_RANGE_NM = 20
local THREAT_SEARCH_NM = 80      -- "nearest hostile" search radius around the lead

-- Break / bugout
local BREAK_DESCENT_FT = 5000
local BREAK_MIN_AGL_M = 600
local BREAK_MIN_SPEED_KTS = 400
local BUGOUT_SPEED_KTS = 900

-- Formation offsets for FOLLOW, in the leader's frame:
-- x = forward(+)/back(-), y = up, z = right(+)/left(-), metres.
-- If the wingman forms up on the wrong side, swap the signs of z.
local FORMATIONS = {
    right   = { x = -60,  y = 0, z = 60 },
    left    = { x = -60,  y = 0, z = -60 },
    trail   = { x = -150, y = 0, z = 0 },
    abreast = { x = 0,    y = 0, z = 120 },
}


-- ---- AWACS feed (DCS -> ATC app) -----------------------------
local AWACS_HOST = "127.0.0.1"
local AWACS_PORT = 5015
local AWACS_INTERVAL = 1.0           -- seconds between pictures

-- Where does the picture come from?
--   "auto"  a friendly AWACS aircraft in the mission (see below) if one is
--           airborne, otherwise every hostile aircraft in range
--   "awacs" ONLY what friendly AWACS aircraft detect on radar (realistic)
--   "all"   every hostile aircraft in range, no radar needed (simple)
local AWACS_SOURCE = "auto"

-- A friendly, AI-flown aircraft counts as an AWACS when its DCS type is in
-- this list, or its unit/group name contains AWACS_NAME_HINT ("" = off).
local AWACS_TYPES = {
    ["E-3A"] = true, ["E-2C"] = true, ["E-2D"] = true,
    ["A-50"] = true, ["KJ-2000"] = true,
}
local AWACS_NAME_HINT = "AWACS"

local AWACS_MAX_RANGE_NM = 200       -- ignore contacts farther than this from you
local AWACS_MAX_CONTACTS = 100       -- nearest N are sent (one UDP packet)
local AWACS_INCLUDE_FRIENDLIES = false

-- Multiplayer: whose position is "ownship"? nil = the first human pilot
-- found. Set to your exact DCS player name to pin it to you.
local AWACS_PLAYER_NAME = nil


-- =============================================================
-- LOG HELPER
-- =============================================================

local function log(message)
    env.info("WINGMAN BRIDGE: " .. tostring(message))
end


-- =============================================================
-- LOAD DCS SOCKET
-- =============================================================

-- DCS blocks `package` for mission scripts unless MissionScripting.lua is
-- edited (see the README / chat). Say so clearly instead of crashing.
if not package or not package.loadlib then
    local why = "DCS has blocked 'package' for mission scripts. Edit "
        .. "DCS World\\Scripts\\MissionScripting.lua and remove (or comment "
        .. "out) the lines that set _G['package'], _G['require'] and "
        .. "_G['loadlib'] to nil, then restart DCS."
    log("FAILED TO LOAD SOCKET: " .. why)
    pcall(function() trigger.action.outText("WINGMAN BRIDGE: " .. why, 30) end)
    return
end

-- WINGMAN_DCS_DIR is set by the auto-loader hook (the real install folder);
-- the default Program Files path is the fallback for a manual load.
local socket_paths = {}

if WINGMAN_DCS_DIR then
    local dir = (tostring(WINGMAN_DCS_DIR):gsub("[\\/]+$", ""))
    table.insert(socket_paths, dir .. "\\bin\\lua-socket.dll")
    table.insert(socket_paths, dir .. "\\lua-socket.dll")
end

table.insert(
    socket_paths,
    "C:\\Program Files\\Eagle Dynamics\\DCS World\\bin\\lua-socket.dll"
)

local socket_lib, load_err

for _, socket_path in ipairs(socket_paths) do
    socket_lib, load_err = package.loadlib(socket_path, "luaopen_socket_core")
    if socket_lib then
        break
    end
end

if not socket_lib then
    log("FAILED TO LOAD SOCKET: " .. tostring(load_err))
    return
end

local socket = socket_lib()

if not socket then
    log("FAILED TO INITIALIZE SOCKET")
    return
end

local udp = socket.udp()

if not udp then
    log("FAILED TO CREATE UDP SOCKET")
    return
end

local ok, err = udp:setpeername(UDP_HOST, UDP_PORT)

if not ok then
    log("FAILED TO SET UDP PEER: " .. tostring(err))
    return
end

log("UDP SOCKET READY -> " .. UDP_HOST .. ":" .. UDP_PORT)


-- =============================================================
-- HELPERS
-- =============================================================

local function json_escape(value)
    value = tostring(value)
    value = string.gsub(value, "\\", "\\\\")
    value = string.gsub(value, '"', '\\"')
    value = string.gsub(value, "\n", "\\n")
    value = string.gsub(value, "\r", "\\r")
    value = string.gsub(value, "\t", "\\t")
    return value
end

local function num(value, decimals)
    value = tonumber(value) or 0
    if value ~= value or value == math.huge or value == -math.huge then
        value = 0
    end
    return string.format("%." .. (decimals or 2) .. "f", value)
end

local function side_name(side)
    if side == coalition.side.BLUE then return "blue" end
    if side == coalition.side.RED then return "red" end
    return "neutral"
end

local function get_heading(unit)
    local position = unit:getPosition()
    if not position or not position.x then
        return 0
    end
    -- DCS: x = north, z = east
    local heading = math.deg(math.atan2(position.x.z, position.x.x))
    if heading < 0 then
        heading = heading + 360
    end
    return heading
end


-- =============================================================
-- FRIENDLY SIDE RESOLUTION
-- =============================================================

local resolved_side = FRIENDLY_SIDE

local function resolve_friendly_side()

    if resolved_side then
        return resolved_side
    end

    for _, side in ipairs({ coalition.side.BLUE, coalition.side.RED }) do
        for _, category in ipairs(CATEGORIES) do
            local groups = coalition.getGroups(side, category)
            if groups then
                for _, group in ipairs(groups) do
                    local units = group:getUnits()
                    if units then
                        for _, unit in ipairs(units) do
                            if unit:isExist() and unit:getPlayerName() then
                                resolved_side = side
                                log("AUTO-DETECTED FRIENDLY SIDE: " .. side_name(side))
                                return resolved_side
                            end
                        end
                    end
                end
            end
        end
    end

    return nil   -- no human player yet
end


-- =============================================================
-- COLLECT FRIENDLY AIRCRAFT
-- =============================================================

local function get_friendly_units(side)

    local aircraft = {}

    for _, category in ipairs(CATEGORIES) do

        local groups = coalition.getGroups(side, category)

        if groups then
            for _, group in ipairs(groups) do
                if group and group:isExist() then
                    local units = group:getUnits()
                    if units then
                        for _, unit in ipairs(units) do
                            if unit and unit:isExist() then
                                table.insert(aircraft, { unit = unit, group = group })
                            end
                        end
                    end
                end
            end
        end
    end

    return aircraft
end


-- =============================================================
-- BUILD ONE UNIT
-- =============================================================

local function build_unit_json(unit, group)

    local point = unit:getPoint()
    if not point then
        return nil
    end

    local velocity = unit:getVelocity() or { x = 0, y = 0, z = 0 }
    local speed_ms = math.sqrt(
        velocity.x * velocity.x +
        velocity.y * velocity.y +
        velocity.z * velocity.z
    )

    local lat, lon = coord.LOtoLL(point)

    local fuel = unit:getFuel() or 0
    local life = unit:getLife() or 0
    local life0 = unit:getLife0() or 1
    local player = unit:getPlayerName()
    local desc = unit:getDesc()
    local category = (desc and desc.category == Unit.Category.HELICOPTER) and "helicopter" or "airplane"

    return "{"
        .. '"id":' .. tostring(unit:getID()) .. ","
        .. '"name":"' .. json_escape(unit:getName()) .. '",'
        .. '"type":"' .. json_escape(unit:getTypeName()) .. '",'
        .. '"category":"' .. category .. '",'
        .. '"callsign":"' .. json_escape(unit:getCallsign() or "") .. '",'
        .. '"group":"' .. json_escape(group:getName()) .. '",'
        .. '"group_id":' .. tostring(group:getID()) .. ","
        .. '"coalition":"' .. side_name(unit:getCoalition()) .. '",'
        .. '"player":' .. (player and ('"' .. json_escape(player) .. '"') or "null") .. ","

        .. '"position":{'
        .. '"x":' .. num(point.x) .. ","
        .. '"y":' .. num(point.y) .. ","
        .. '"z":' .. num(point.z)
        .. "},"

        .. '"lat":' .. num(lat, 6) .. ","
        .. '"lon":' .. num(lon, 6) .. ","
        .. '"altitude_ft":' .. num(point.y * 3.28084, 1) .. ","
        .. '"heading_deg":' .. num(get_heading(unit), 1) .. ","
        .. '"speed_kts":' .. num(speed_ms * 1.943844, 1) .. ","
        .. '"vertical_speed_fpm":' .. num(velocity.y * 196.8504, 0) .. ","
        .. '"velocity":{'
        .. '"x":' .. num(velocity.x) .. ","
        .. '"y":' .. num(velocity.y) .. ","
        .. '"z":' .. num(velocity.z)
        .. "},"

        .. '"fuel":' .. num(fuel, 3) .. ","
        .. '"life":' .. num(life, 1) .. ","
        .. '"life_max":' .. num(life0, 1) .. ","
        .. '"alive":true'
        .. "}"
end


-- =============================================================
-- BUILD + SEND TELEMETRY
-- =============================================================

local packet_count = 0

local function send_packet(parts, part_index, part_total, friendly_side)

    local payload =
        "{"
        .. '"timestamp":' .. num(timer.getTime(), 2) .. ","
        .. '"friendly_coalition":"' .. side_name(friendly_side) .. '",'
        .. '"part":' .. part_index .. ","
        .. '"parts":' .. part_total .. ","
        .. '"units":[' .. table.concat(parts, ",") .. "]"
        .. "}"

    local send_ok, send_result = pcall(function()
        return udp:send(payload)
    end)

    if not send_ok then
        log("UDP SEND ERROR: " .. tostring(send_result))
        return
    end

    packet_count = packet_count + 1
    if packet_count == 1 then
        log("FIRST TELEMETRY PACKET SENT")
    end
end

local function send_telemetry()

    local side = resolve_friendly_side()

    if side then

        local success, result = pcall(function()

            local entries = get_friendly_units(side)
            local json_units = {}

            for _, entry in ipairs(entries) do
                local json = build_unit_json(entry.unit, entry.group)
                if json then
                    table.insert(json_units, json)
                end
            end

            return json_units
        end)

        if not success then
            log("TELEMETRY BUILD ERROR: " .. tostring(result))
        else
            local total_parts = math.max(1, math.ceil(#result / UNITS_PER_PACKET))

            for part = 1, total_parts do
                local chunk = {}
                local first = (part - 1) * UNITS_PER_PACKET + 1
                local last = math.min(part * UNITS_PER_PACKET, #result)

                for i = first, last do
                    table.insert(chunk, result[i])
                end

                send_packet(chunk, part, total_parts, side)
            end
        end
    end

    return timer.getTime() + UPDATE_INTERVAL
end


-- =============================================================
-- COMMAND LINK  (Python -> DCS)
--
-- One UDP datagram per order, fields split by "|" (key=value):
--   FLIGHT|unit=U|hdg=225|alt=15000|spd=250|rel=-90   (rel = turn, + right)
--   ROE|unit=U|mode=free / tight / return / hold
--   COUNTERMEASURES|unit=U|mode=on / off
--   RADAR|unit=U|mode=on / off
--   EMCON|unit=U|mode=on / off
--   RTB|unit=U
--   ORBIT|unit=U[|alt=ft][|spd=kts]
--   FOLLOW|unit=U[|formation=right / left / trail / abreast]
--   BREAK|unit=U|dir=left / right
--   BUGOUT|unit=U
--   ENGAGE|unit=U|mode=intercept / merge / defend / investigate / attack
--          [|target=<group name>][|brg=deg|ref=rel / abs|rng=nm|alt=ft]
--   INBOUND|unit=U[|brg=deg|ref=rel / abs|rng=nm]
--   RESUME|unit=U   back to the original mission route
--   WATCH|unit=U    start reporting this aircraft's events/contacts (see EVENTS)
--   CLEAR|unit=U    stop managing the aircraft, leave it on its last route
-- =============================================================

local cmd_udp = socket.udp()
local cmd_ready = false

if cmd_udp then
    pcall(function() cmd_udp:setoption("reuseaddr", true) end)
    local bind_ok, bind_err = cmd_udp:setsockname(CMD_HOST, CMD_PORT)
    if bind_ok then
        cmd_udp:settimeout(0)          -- never block the DCS sim thread
        cmd_ready = true
        log("COMMAND SOCKET LISTENING ON " .. CMD_HOST .. ":" .. CMD_PORT)
    else
        log("FAILED TO BIND COMMAND SOCKET: " .. tostring(bind_err))
    end
else
    log("FAILED TO CREATE COMMAND SOCKET")
end

-- Active orders, keyed by unit name. Every order has a `kind`:
--   HOLD   fly a heading / altitude / speed (re-aimed when it drifts)
--   PURSUE chase a group or a point (intercept, attack, investigate, inbound)
local orders = {}

-- DCS can't read an AI's ROE back, so remember what we set.
local roe_state = {}

local FT_TO_M = 0.3048
local KTS_TO_MS = 0.514444
local NM_TO_M = 1852

local function clamp(value, low, high)
    if value < low then return low end
    if value > high then return high end
    return value
end

local function horizontal_speed(unit)
    local v = unit:getVelocity() or { x = 0, y = 0, z = 0 }
    return math.sqrt(v.x * v.x + v.z * v.z)
end

local function dist2d(a, b)
    local dx = a.x - b.x
    local dz = a.z - b.z
    return math.sqrt(dx * dx + dz * dz)
end

-- True bearing from one point to another (x = north, z = east).
local function bearing_true(from, to)
    local b = math.deg(math.atan2(to.z - from.z, to.x - from.x))
    if b < 0 then
        b = b + 360
    end
    return b
end

local function point_at(origin, bearing, distance)
    local r = math.rad(bearing)
    return {
        x = origin.x + math.cos(r) * distance,
        y = origin.y,
        z = origin.z + math.sin(r) * distance,
    }
end

local function ground_height(p)
    local ok_h, h = pcall(function()
        return land.getHeight({ x = p.x, y = p.z })
    end)
    if ok_h and type(h) == "number" then
        return h
    end
    return 0
end

local function normalize_name(s)
    local cleaned = string.gsub(tostring(s), "[^%w]", "")
    return string.lower(cleaned)
end

local function combo(tasks)
    return { id = "ComboTask", params = { tasks = tasks } }
end

-- ---- finding things ---------------------------------------------

-- Only ever steer friendly, AI-flown aircraft (airborne unless allow_ground).
local function find_controllable_unit(name, allow_ground)

    if not name or name == "" then
        return nil, "no unit name"
    end

    local unit = Unit.getByName(name)

    if not unit or not unit:isExist() then
        return nil, "unit not found: " .. tostring(name)
    end

    if unit:getPlayerName() then
        return nil, "refusing to control a human-flown aircraft"
    end

    local side = resolve_friendly_side()
    if side and unit:getCoalition() ~= side then
        return nil, "unit is not friendly"
    end

    if not allow_ground and not unit:inAir() then
        return nil, "unit is not airborne"
    end

    return unit
end

-- The nearest human-flown friendly aircraft: "the lead".
local function find_leader(near_unit)

    local side = resolve_friendly_side()
    if not side then
        return nil
    end

    local best, best_d = nil, nil
    local here = near_unit:getPoint()

    for _, entry in ipairs(get_friendly_units(side)) do
        local u = entry.unit
        if u:getPlayerName() then
            local d = dist2d(u:getPoint(), here)
            if not best_d or d < best_d then
                best, best_d = u, d
            end
        end
    end

    return best
end

local function enemy_side(side)
    if side == coalition.side.BLUE then
        return coalition.side.RED
    end
    return coalition.side.BLUE
end

-- Hostile aircraft currently flying, as { unit, group } entries.
local function enemy_air_units()

    local out = {}
    local side = resolve_friendly_side()
    if not side then
        return out
    end

    for _, category in ipairs(CATEGORIES) do
        local groups = coalition.getGroups(enemy_side(side), category)
        if groups then
            for _, group in ipairs(groups) do
                if group and group:isExist() then
                    local units = group:getUnits()
                    if units then
                        for _, u in ipairs(units) do
                            if u and u:isExist() and u:inAir() then
                                table.insert(out, { unit = u, group = group })
                            end
                        end
                    end
                end
            end
        end
    end

    return out
end

local function nearest_enemy_air(point, max_distance)

    local best, best_d = nil, max_distance

    for _, entry in ipairs(enemy_air_units()) do
        local d = dist2d(entry.unit:getPoint(), point)
        if not best_d or d <= best_d then
            best, best_d = entry, d
        end
    end

    return best
end

-- Enemy group (any category) whose name matches what was said.
-- "bandit 1" matches "Bandit-1", "BANDIT 1 flight", ...
local function find_enemy_group_by_name(spoken, near)

    local side = resolve_friendly_side()
    local wanted = normalize_name(spoken)

    if not side or wanted == "" then
        return nil
    end

    local best, best_score, best_d = nil, 0, nil

    for _, group in ipairs(coalition.getGroups(enemy_side(side)) or {}) do
        if group and group:isExist() then

            local score = 0
            local gname = normalize_name(group:getName())

            if gname == wanted then
                score = 3
            elseif string.find(gname, wanted, 1, true) then
                score = 2
            else
                for _, u in ipairs(group:getUnits() or {}) do
                    local uname = normalize_name(u:getName())
                    if uname == wanted or string.find(uname, wanted, 1, true) then
                        score = 1
                        break
                    end
                end
            end

            if score > 0 then
                local units = group:getUnits()
                local d = (units and units[1] and dist2d(units[1]:getPoint(), near)) or 0
                if score > best_score or (score == best_score and best_d and d < best_d) then
                    best, best_score, best_d = group, score, d
                end
            end
        end
    end

    return best
end

-- Closest usable airfield: owned by us OR neutral (many missions leave
-- airfields neutral, and coalition.getAirbases() only lists owned ones).
-- Ships are never used; helicopters may also use helipads.
local function nearest_friendly_airbase(unit)

    local side = resolve_friendly_side()
    if not side then
        return nil
    end

    local desc = unit:getDesc()
    local is_heli = desc and Unit.Category and desc.category == Unit.Category.HELICOPTER
    local from = unit:getPoint()

    local candidates, seen = {}, {}

    local function consider(base)
        local ok_n, base_name = pcall(base.getName, base)
        if ok_n and not seen[base_name] then
            seen[base_name] = true
            table.insert(candidates, base)
        end
    end

    for _, base in ipairs(coalition.getAirbases(side) or {}) do
        consider(base)
    end

    local neutral = (coalition.side.NEUTRAL or 0)
    local ok_w, everything = pcall(function() return world.getAirbases() end)

    if ok_w then
        for _, base in ipairs(everything or {}) do
            if base:getCoalition() == neutral then
                consider(base)
            end
        end
    end

    local best, best_d = nil, nil

    for _, base in ipairs(candidates) do
        local base_desc = base:getDesc()
        local category = base_desc and base_desc.category
        local usable
        if not Airbase or category == nil then
            usable = true
        elseif is_heli then
            usable = (category ~= Airbase.Category.SHIP)
        else
            usable = (category == Airbase.Category.AIRDROME)
        end

        if usable then
            local d = dist2d(base:getPoint(), from)
            if not best_d or d < best_d then
                best, best_d = base, d
            end
        end
    end

    if not best then
        log(string.format("NO USABLE AIRBASE (%d candidates considered)", #candidates))
    end

    return best
end

-- Where a reported contact is: from the lead's position, a bearing
-- (ref "rel" = off the lead's nose, otherwise a compass bearing)
-- and a range in nm.
local function contact_point(leader, fields)

    local brg = tonumber(fields.brg)
    if not brg then
        return nil
    end

    local true_bearing
    if fields.ref == "rel" then
        true_bearing = (get_heading(leader) + brg) % 360
    else
        true_bearing = (brg + MAGNETIC_VARIATION_DEG) % 360
    end

    local range_m = (tonumber(fields.rng) or DEFAULT_CONTACT_RANGE_NM) * NM_TO_M

    return point_at(leader:getPoint(), true_bearing, range_m), range_m
end

-- Returns (enemy entry or nil, reported point or nil).
local function resolve_threat(leader, fields)

    local point, range_m = contact_point(leader, fields)

    if point then
        local radius = math.max(10 * NM_TO_M, range_m * 0.35)
        return nearest_enemy_air(point, radius), point
    end

    return nearest_enemy_air(leader:getPoint(), THREAT_SEARCH_NM * NM_TO_M), nil
end

-- ---- AI options (ROE, radar, countermeasures) -------------------

local function ai_id(name, fallback)
    local ids = AI and AI.Option and AI.Option.Air and AI.Option.Air.id
    return (ids and ids[name]) or fallback
end

local function ai_val(option, name, fallback)
    local vals = AI and AI.Option and AI.Option.Air and AI.Option.Air.val
    local set = vals and vals[option]
    return (set and set[name]) or fallback
end

local OPT = {
    ROE     = ai_id("ROE", 0),
    RADAR   = ai_id("RADAR_USING", 3),
    FLARE   = ai_id("FLARE_USING", 4),
    SILENCE = ai_id("SILENCE", 7),
    ECM     = ai_id("ECM_USING", 13),
}

local ROE_VALUES = {
    free      = ai_val("ROE", "WEAPON_FREE", 0),
    tight     = ai_val("ROE", "OPEN_FIRE", 2),
    ["return"] = ai_val("ROE", "RETURN_FIRE", 3),
    hold      = ai_val("ROE", "WEAPON_HOLD", 4),
}

-- lower = more permissive
local ROE_RANK = { free = 1, tight = 2, ["return"] = 3, hold = 4 }

local function set_option(unit, option_id, value)

    local controller = unit:getController()
    if not controller then
        return false
    end

    local ok_set, set_err = pcall(function()
        controller:setOption(option_id, value)
    end)

    if not ok_set then
        log("SET OPTION FAILED: " .. tostring(set_err))
    end

    return ok_set
end

local function set_roe(unit, mode)

    local value = ROE_VALUES[mode]
    if value == nil then
        return false
    end

    if set_option(unit, OPT.ROE, value) then
        roe_state[unit:getName()] = mode
        log("ROE " .. unit:getName() .. " -> " .. mode)
        return true
    end

    return false
end

-- Raise ROE to at least `mode` (never tightens it).
local function ensure_roe(unit, mode)

    local current = roe_state[unit:getName()]

    if current == nil or ROE_RANK[current] > ROE_RANK[mode] then
        set_roe(unit, mode)
    end
end

local function set_countermeasures(unit, on)
    -- DCS exposes a flare option for AI; there is no separate chaff
    -- option, so "flares" and "chaff" both drive this one setting.
    local value
    if on then
        value = ai_val("FLARE_USING", "WHEN_FLYING_NEAR_ENEMIES", 3)
    else
        value = ai_val("FLARE_USING", "NEVER_USE", 0)
    end
    return set_option(unit, OPT.FLARE, value)
end

local function set_radar(unit, on)
    local value
    if on then
        value = ai_val("RADAR_USING", "USE_FOR_CONTINUOUS_SEARCH", 3)
    else
        value = ai_val("RADAR_USING", "NEVER_USE", 0)
    end
    return set_option(unit, OPT.RADAR, value)
end

local function set_emcon(unit, on)
    -- EMCON: radar, jammer and AI radio calls all quiet.
    local ecm_off = ai_val("ECM_USING", "NEVER_USE", 0)
    local ecm_on = ai_val("ECM_USING", "USE_IF_DETECTED_LOCK_BY_RADAR", 2)

    set_radar(unit, not on)
    set_option(unit, OPT.ECM, on and ecm_off or ecm_on)
    set_option(unit, OPT.SILENCE, on and true or false)
    return true
end

-- ---- routes -----------------------------------------------------

local function make_waypoint(x, z, alt_m, speed_ms)
    return {
        type = "Turning Point",
        action = "Turning Point",
        x = x,
        y = z,                       -- route "y" is the world Z (east) axis
        alt = alt_m,
        alt_type = "BARO",
        speed = speed_ms,
        speed_locked = true,
        task = combo({}),
    }
end

local function set_mission(unit, points)

    local controller = unit:getController()
    if not controller then
        return false, "unit has no controller"
    end

    controller:setTask({ id = "Mission", params = { route = { points = points } } })
    return true
end

local function engage_targets_task(n)
    return {
        number = n, auto = false, enabled = true, id = "EngageTargets",
        params = { maxDist = ENGAGE_MAX_DIST_M, targetTypes = { "Air" }, priority = 0 },
    }
end

-- HOLD: here -> a far point on the wanted heading, at the wanted
-- altitude and speed.
local function issue_route(unit, order)

    local p = unit:getPoint()
    local far = point_at(p, order.hdg_true, ROUTE_LEG_M)

    order.tx = far.x
    order.tz = far.z

    local current_speed = math.max(horizontal_speed(unit), 60)

    -- Let the AI engage air targets it finds on its own while flying the
    -- leg (it still needs ROE: weapons free / tight).
    local start_wp = make_waypoint(p.x, p.z, p.y, current_speed)
    start_wp.task = combo({ engage_targets_task(1) })

    local issued, issue_err = set_mission(unit, {
        start_wp,
        make_waypoint(order.tx, order.tz, order.alt_m, order.spd_ms),
    })

    if issued then
        order.last_issue = timer.getTime()
    end

    return issued, issue_err
end

-- Start (or replace) a HOLD order.
local function start_hold(unit, hdg_true, alt_m, spd_ms)

    local order = {
        kind = "HOLD",
        hdg_true = hdg_true % 360,
        alt_m = alt_m,
        spd_ms = spd_ms,
        last_issue = 0,
    }

    orders[unit:getName()] = order

    local issued, issue_err = issue_route(unit, order)
    if not issued then
        orders[unit:getName()] = nil
        log("HOLD FAILED: " .. tostring(issue_err))
    end

    return issued
end

-- Keep flying straight on whatever the aircraft is doing now.
local function hold_here(unit)
    local p = unit:getPoint()
    return start_hold(unit, get_heading(unit), p.y, math.max(horizontal_speed(unit), 60))
end

-- PURSUE ---------------------------------------------------------

local function attack_unit_task(n, u)
    return {
        number = n, auto = false, enabled = true, id = "AttackUnit",
        params = {
            unitId = u:getID(), expend = "Auto", weaponType = 1073741822,
            attackQtyLimit = false, groupAttack = false,
        },
    }
end

local function attack_group_task(n, g)
    return {
        number = n, auto = false, enabled = true, id = "AttackGroup",
        params = {
            groupId = g:getID(), expend = "Auto", weaponType = 1073741822,
            attackQtyLimit = false, groupAttack = true,
        },
    }
end

local ZERO_VEL = { x = 0, y = 0, z = 0 }

-- What are we chasing right now? nil when it is gone.
local function target_info(order)

    if order.group_name then

        local group = Group.getByName(order.group_name)
        if not group or not group:isExist() then
            return nil
        end

        local alive = {}
        for _, u in ipairs(group:getUnits() or {}) do
            if u:isExist() then
                table.insert(alive, u)
            end
        end

        if #alive == 0 then
            return nil
        end

        local category = group:getCategory()
        local is_air = (category == Group.Category.AIRPLANE or category == Group.Category.HELICOPTER)

        return {
            pos = alive[1]:getPoint(),
            vel = alive[1]:getVelocity() or ZERO_VEL,
            units = alive, group = group, is_air = is_air,
        }
    end

    if order.target_point then
        return { pos = order.target_point, vel = ZERO_VEL, units = {}, is_air = false }
    end

    return nil
end

-- Returns true, or false + reason (target lost / arrived).
local function issue_pursue(unit, order)

    local info = target_info(order)
    if not info then
        return false, "target lost"
    end

    local p = unit:getPoint()
    local dist = dist2d(p, info.pos)

    if order.stop_m and dist <= order.stop_m then
        return false, "arrived"
    end

    -- lead the target a little so we cut it off instead of tail-chasing
    local lead_s = clamp(dist / math.max(order.spd_ms, 100), 0, 90)
    local tx = info.pos.x + info.vel.x * lead_s
    local tz = info.pos.z + info.vel.z * lead_s

    local alt
    if info.group and not info.is_air then
        alt = math.max(info.pos.y + 4000, 3000)        -- ground target: come in high
    elseif info.group then
        alt = info.pos.y                                 -- air target: match its altitude
    else
        alt = order.alt_m or p.y
    end
    alt = math.max(alt, MIN_ALT_FT * FT_TO_M)

    local wp1 = make_waypoint(p.x, p.z, p.y, math.max(horizontal_speed(unit), 60))
    local wp2 = make_waypoint(tx, tz, alt, order.spd_ms)

    if order.attack then

        wp1.task = combo({ engage_targets_task(1) })

        local tasks = {}

        if info.group and info.is_air then
            for i, u in ipairs(info.units) do
                if i > 4 then break end
                table.insert(tasks, attack_unit_task(#tasks + 1, u))
            end
        elseif info.group then
            table.insert(tasks, attack_group_task(1, info.group))
        end

        wp2.task = combo(tasks)
    end

    local issued, issue_err = set_mission(unit, { wp1, wp2 })

    if not issued then
        return false, issue_err
    end

    order.last_issue = timer.getTime()
    return true
end

local function start_pursue(unit, order)

    local name = unit:getName()

    order.kind = "PURSUE"
    order.last_issue = 0
    orders[name] = order

    local issued, why = issue_pursue(unit, order)

    if not issued then
        log("PURSUIT ENDED (" .. tostring(why) .. "): " .. name)
        hold_here(unit)
    end

    return issued
end

-- ---- command parsing ---------------------------------------------

local function parse_command(line)

    local action = nil
    local fields = {}

    for token in string.gmatch(line, "[^|]+") do
        if not action then
            action = string.upper(token)
        else
            local key, value = string.match(token, "^([%w_]+)=(.*)$")
            if key then
                fields[key] = value
            end
        end
    end

    return action, fields
end

-- ---- command handlers --------------------------------------------

-- Shows up in the sim as well as dcs.log, so a refused order is never silent.
local function notify(text)
    pcall(function() trigger.action.outText("WINGMAN: " .. text, 8) end)
end

local function reject(what, why)
    log(what .. " REJECTED: " .. tostring(why))
    notify(what .. " refused - " .. tostring(why))
end

local function handle_flight(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)

    if not unit then
        return reject("FLIGHT ORDER", why)
    end

    -- A flight order takes over from any chase.
    local order = orders[name]
    if order and order.kind ~= "HOLD" then
        orders[name] = nil
        order = nil
    end

    -- First order for this aircraft: start from what it is doing now,
    -- so "just change heading" keeps its altitude and speed.
    if not order then
        order = {
            kind = "HOLD",
            hdg_true = get_heading(unit),
            alt_m = unit:getPoint().y,
            spd_ms = math.max(horizontal_speed(unit), 60),
            last_issue = 0,
        }
        orders[name] = order
    end

    local hdg = tonumber(fields.hdg)
    local rel = tonumber(fields.rel)

    if hdg then
        order.hdg_true = (hdg + MAGNETIC_VARIATION_DEG) % 360
    elseif rel then
        order.hdg_true = (order.hdg_true + rel) % 360     -- relative turns need no variation
    end

    local alt_ft = tonumber(fields.alt)
    if alt_ft then
        alt_ft = clamp(alt_ft, MIN_ALT_FT, MAX_ALT_FT)

        -- Respect the airframe's ceiling where DCS reports one.
        local desc = unit:getDesc()
        local ceiling_m = desc and tonumber(desc.Hmax)
        if ceiling_m and ceiling_m > 0 then
            alt_ft = math.min(alt_ft, ceiling_m / FT_TO_M)
        end

        order.alt_m = alt_ft * FT_TO_M
    end

    local spd_kts = tonumber(fields.spd)
    if spd_kts then
        order.spd_ms = clamp(spd_kts, MIN_SPEED_KTS, MAX_SPEED_KTS) * KTS_TO_MS
    end

    local issued, issue_err = issue_route(unit, order)

    if issued then
        log(string.format(
            "FLIGHT ORDER %s: hdg(true) %.0f  alt %.0f ft  spd %.0f kts",
            name,
            order.hdg_true,
            order.alt_m / FT_TO_M,
            order.spd_ms / KTS_TO_MS
        ))
    else
        log("FLIGHT ORDER FAILED: " .. tostring(issue_err))
        orders[name] = nil
    end
end

local function handle_roe(fields)
    local unit, why = find_controllable_unit(fields.unit, true)
    if not unit then
        return reject("ROE", why)
    end
    if not set_roe(unit, fields.mode) then
        log("ROE FAILED: bad mode " .. tostring(fields.mode))
    end
end

local function handle_countermeasures(fields)
    local unit, why = find_controllable_unit(fields.unit, true)
    if not unit then
        return reject("COUNTERMEASURES", why)
    end
    local on = (fields.mode ~= "off")
    if set_countermeasures(unit, on) then
        log("COUNTERMEASURES " .. unit:getName() .. (on and " ON" or " OFF"))
    end
end

local function handle_radar(fields)
    local unit, why = find_controllable_unit(fields.unit, true)
    if not unit then
        return reject("RADAR", why)
    end
    local on = (fields.mode ~= "off")
    if set_radar(unit, on) then
        log("RADAR " .. unit:getName() .. (on and " ON" or " OFF"))
    end
end

local function handle_emcon(fields)
    local unit, why = find_controllable_unit(fields.unit, true)
    if not unit then
        return reject("EMCON", why)
    end
    local on = (fields.mode ~= "off")
    set_emcon(unit, on)
    log("EMCON " .. unit:getName() .. (on and " ON" or " OFF"))
end

local function handle_rtb(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("RTB", why)
    end

    local p = unit:getPoint()
    local base = nearest_friendly_airbase(unit)

    if not base then
        return reject("RTB", "no usable airfield found")
    end

    local bp = base:getPoint()

    local land_wp = {
        type = "LAND",
        action = "Landing",
        x = bp.x,
        y = bp.z,
        alt = ground_height(bp),
        alt_type = "BARO",
        speed = 140,
        speed_locked = true,
        airdromeId = base:getID(),
        formation_template = "",
        ETA = 0,
        ETA_locked = false,
        properties = { addopt = {} },
        task = combo({}),
    }

    orders[name] = nil      -- nothing may fight the landing route

    local issued, issue_err = set_mission(unit, {
        make_waypoint(p.x, p.z, p.y, math.max(horizontal_speed(unit), 60)),
        land_wp,
    })

    if issued then
        log(string.format(
            "RTB %s -> %s (airdromeId %s, %.0f nm)",
            name, tostring(base:getName()), tostring(base:getID()),
            dist2d(p, bp) / NM_TO_M
        ))
        notify(name .. " returning to " .. tostring(base:getName()))
    else
        log("RTB FAILED: " .. tostring(issue_err))
        notify("RTB failed - " .. tostring(issue_err))
    end
end

local function handle_orbit(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("ORBIT", why)
    end

    local p = unit:getPoint()

    local alt_m = p.y
    local alt_ft = tonumber(fields.alt)
    if alt_ft then
        alt_m = clamp(alt_ft, MIN_ALT_FT, MAX_ALT_FT) * FT_TO_M
    end

    local spd_ms = math.max(horizontal_speed(unit), 100)
    local spd_kts = tonumber(fields.spd)
    if spd_kts then
        spd_ms = clamp(spd_kts, MIN_SPEED_KTS, MAX_SPEED_KTS) * KTS_TO_MS
    end

    orders[name] = nil

    unit:getController():setTask({
        id = "Orbit",
        params = {
            pattern = "Circle",
            point = { x = p.x, y = p.z },
            speed = spd_ms,
            altitude = alt_m,
        },
    })

    log("ORBIT " .. name)
end

local function handle_follow(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("FOLLOW", why)
    end

    local leader = find_leader(unit)
    if not leader then
        return reject("FOLLOW", "no human-flown aircraft to follow")
    end

    local group = leader:getGroup()
    local offset = FORMATIONS[fields.formation or "right"] or FORMATIONS.right

    orders[name] = nil

    unit:getController():setTask({
        id = "Follow",
        params = {
            groupId = group:getID(),
            pos = { x = offset.x, y = offset.y, z = offset.z },
            lastWptIndexFlag = false,
            lastWptIndex = 1,
        },
    })

    log("FOLLOW " .. name .. " -> " .. tostring(leader:getName()))
end

local function handle_break(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("BREAK", why)
    end

    local sign = (fields.dir == "left") and -1 or 1
    local p = unit:getPoint()

    local alt_m = math.max(
        p.y - BREAK_DESCENT_FT * FT_TO_M,
        ground_height(p) + BREAK_MIN_AGL_M,
        MIN_ALT_FT * FT_TO_M
    )

    local spd_ms = math.max(horizontal_speed(unit), BREAK_MIN_SPEED_KTS * KTS_TO_MS)

    if start_hold(unit, get_heading(unit) + 90 * sign, alt_m, spd_ms) then
        log("BREAK " .. (fields.dir or "right") .. " " .. name)
    end
end

local function handle_bugout(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("BUGOUT", why)
    end

    local p = unit:getPoint()
    local threat = nearest_enemy_air(p, 100 * NM_TO_M)

    local away
    if threat then
        away = bearing_true(p, threat.unit:getPoint()) + 180
    else
        away = get_heading(unit) + 180
    end

    set_roe(unit, "return")

    if start_hold(unit, away, p.y, BUGOUT_SPEED_KTS * KTS_TO_MS) then
        log("BUGOUT " .. name)
    end
end

local function handle_engage(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("ENGAGE", why)
    end

    local mode = fields.mode or "intercept"
    local leader = find_leader(unit) or unit

    local order = {
        spd_ms = PURSUE_SPEED_KTS * KTS_TO_MS,
        attack = true,
    }

    if mode == "attack" then

        local group = find_enemy_group_by_name(fields.target, unit:getPoint())

        if not group then
            return reject("ENGAGE", "no hostile group matching '" .. tostring(fields.target) .. "'")
        end

        order.group_name = group:getName()
        ensure_roe(unit, "tight")

    else

        local entry, point = resolve_threat(leader, fields)

        if entry then
            order.group_name = entry.group:getName()
        elseif point then
            -- nothing there (yet): fly to the reported position
            order.target_point = point
            order.alt_m = tonumber(fields.alt) and tonumber(fields.alt) * FT_TO_M or nil
            order.attack = false
            order.stop_m = POINT_ARRIVE_NM * NM_TO_M
        else
            return reject("ENGAGE", "no hostile aircraft found")
        end

        if mode == "investigate" then
            order.attack = false
            order.stop_m = INVESTIGATE_STOP_NM * NM_TO_M
        elseif mode == "merge" then
            ensure_roe(unit, "free")
        elseif mode == "defend" then
            ensure_roe(unit, "free")
            set_countermeasures(unit, true)
        end
    end

    if start_pursue(unit, order) then
        log(string.format(
            "ENGAGE %s: %s %s",
            name, mode, tostring(order.group_name or "reported position")
        ))
    end
end

local function handle_inbound(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("INBOUND", why)
    end

    local p = unit:getPoint()
    local leader = find_leader(unit) or unit

    local target = contact_point(leader, fields)
    local label = "reported position"

    if not target then
        local base = nearest_friendly_airbase(unit)
        if not base then
            return reject("INBOUND", "no point and no friendly airbase")
        end
        target = base:getPoint()
        label = tostring(base:getName())
    end

    local started = start_pursue(unit, {
        target_point = target,
        alt_m = p.y,
        spd_ms = math.max(horizontal_speed(unit), 120),
        attack = false,
        stop_m = POINT_ARRIVE_NM * NM_TO_M,
    })

    if started then
        log("INBOUND " .. name .. " -> " .. label)
    end
end

-- The route the mission designer gave this group, from env.mission.
local function find_mission_route(group_name)

    local mission = env and env.mission
    if not mission or not mission.coalition then
        return nil
    end

    local function translate(n)
        if env.getValueDictByKey then
            local ok_t, text = pcall(env.getValueDictByKey, n)
            if ok_t and text then
                return text
            end
        end
        return n
    end

    for _, coalition_data in pairs(mission.coalition) do
        for _, country in pairs(coalition_data.country or {}) do
            for _, kind in ipairs({ "plane", "helicopter" }) do
                local block = country[kind]
                if block and block.group then
                    for _, g in pairs(block.group) do
                        if g.name and translate(g.name) == group_name then
                            return g.route and g.route.points
                        end
                    end
                end
            end
        end
    end

    return nil
end

local function handle_resume(fields)

    local name = fields.unit
    local unit, why = find_controllable_unit(name)
    if not unit then
        return reject("RESUME", why)
    end

    orders[name] = nil

    local route = find_mission_route(unit:getGroup():getName())

    if not route or #route == 0 then
        log("RESUME: original route not found, aircraft left on its last route")
        return
    end

    local p = unit:getPoint()

    -- Find the leg of the route we are closest to and rejoin at its far
    -- end. (Judging "already passed it?" from the next leg goes wrong on
    -- sharp turns.)
    local best, best_d = nil, nil

    for i = 1, #route - 1 do
        local a, b = route[i], route[i + 1]
        local abx, abz = b.x - a.x, b.y - a.y
        local len2 = abx * abx + abz * abz

        local t = 0
        if len2 > 0 then
            t = clamp(((p.x - a.x) * abx + (p.z - a.y) * abz) / len2, 0, 1)
        end

        local dx = p.x - (a.x + abx * t)
        local dz = p.z - (a.y + abz * t)
        local d = math.sqrt(dx * dx + dz * dz)

        if not best_d or d < best_d then
            best, best_d = i + 1, d
        end
    end

    best = best or 1      -- single-waypoint route

    local points = { make_waypoint(p.x, p.z, p.y, math.max(horizontal_speed(unit), 60)) }
    for i = best, #route do
        table.insert(points, route[i])
    end

    local issued, issue_err = set_mission(unit, points)

    if issued then
        log("RESUME " .. name .. " from waypoint " .. best)
    else
        log("RESUME FAILED: " .. tostring(issue_err))
    end
end

local function handle_clear(fields)
    -- Stop managing the aircraft; it keeps flying its last route.
    if fields.unit and orders[fields.unit] then
        orders[fields.unit] = nil
        log("ORDERS CLEARED: " .. fields.unit)
    end
end

-- =============================================================
-- EVENTS  (DCS -> Python, UDP 5018)
--
-- Things the wingman announces on its own. Only units registered with
-- WATCH|unit=<name> are reported (Python does this at startup).
--   {"type":"WEAPON","unit":U,"callout":"FOX_3","weapon":"AIM-120C"}
--   {"type":"TAKEOFF"|"LAND","unit":U}
--   {"type":"KILL","unit":U,"air":true,"target":"MiG-29S"}
--   {"type":"CONTACT","unit":U,"kind":"radar"|"visual","rel_deg":0,
--    "brg":90,"range_nm":20.0,"alt_ft":25000,"count":2,"target_type":null}
-- Contact angles/ranges are measured from the lead (the human pilot),
-- so "12 o'clock" means off YOUR nose.
-- =============================================================

local EVENT_HOST = "127.0.0.1"
local EVENT_PORT = 5018
local CONTACT_SCAN_INTERVAL = 2     -- seconds between sensor sweeps
local CONTACT_MIN_GAP = 4           -- seconds between two contact calls
local CONTACT_FORGET_AFTER = 30     -- unseen this long = "new contact" next time
local CONTACT_MAX_RANGE_NM = 120
local GUN_CALL_GAP = 10

local event_udp = socket.udp()
local watched = {}                  -- unit name -> true
local tracks = {}                   -- unit name -> { [group id] = last time seen }
local last_contact_call = {}        -- unit name -> time
local last_gun_call = {}            -- unit name -> time
local next_scan = 0

local function jstr(value)
    return '"' .. json_escape(value) .. '"'
end

local function send_event(body)
    if event_udp then
        -- unconnected send + pcall: a missing listener must never hurt the sim
        pcall(function()
            event_udp:sendto("{" .. body .. "}", EVENT_HOST, EVENT_PORT)
        end)
    end
end

-- ---- what kind of weapon was that? ------------------------------

local function weapon_constants()
    local w = Weapon or {}
    return
        w.Category or { SHELL = 0, MISSILE = 1, ROCKET = 2, BOMB = 3, TORPEDO = 4 },
        w.MissileCategory or { AAM = 1, SAM = 2, BM = 3, ANTI_SHIP = 4, CRUISE = 5, OTHER = 6 },
        w.GuidanceType or { INS = 1, IR = 2, RADAR_ACTIVE = 3, RADAR_SEMIACTIVE = 4,
                            RADAR_PASSIVE = 5, TV = 6, LASER = 7, TELE = 8 }
end

-- Fallbacks by name for when DCS doesn't report guidance ("." matches - or _).
local FOX1_NAMES = { "AIM.7", "R.27R", "R.27ER", "R.24R", "R.33", "SUPER.530", "RB.?71" }
local FOX2_NAMES = { "AIM.9", "AIM.92", "R.73", "R.60", "R.27T", "R.27ET", "R.40T",
                     "MAGIC", "R550", "PL.5", "PYTHON", "IRIS", "MICA.IR" }
local FOX3_NAMES = { "AIM.120", "AIM.54", "AIM.174", "R.77", "MICA.EM", "METEOR",
                     "PL.12", "SD.10", "AAM.4" }
local ARM_NAMES  = { "AGM.88", "AGM.45", "ALARM", "KH.25MP", "KH.31P", "KH.58", "AGM.122" }

local function name_matches(upper, patterns)
    for _, pattern in ipairs(patterns) do
        if string.find(upper, pattern) then
            return true
        end
    end
    return false
end

-- Returns brevity code (FOX_1/2/3, MAGNUM, RIFLE, PICKLE, ROCKETS) or nil.
local function weapon_callout(weapon)

    local ok_d, desc = pcall(function() return weapon:getDesc() end)
    desc = (ok_d and desc) or {}

    local weapon_name = ""
    pcall(function() weapon_name = weapon:getTypeName() or "" end)
    local upper = string.upper(weapon_name)

    local WC, MC, GT = weapon_constants()

    if desc.category == WC.BOMB then
        return "PICKLE", weapon_name
    end

    if desc.category == WC.ROCKET then
        return "ROCKETS", weapon_name
    end

    if desc.category ~= WC.MISSILE then
        return nil, weapon_name                    -- gun shells etc.
    end

    -- anti-radiation missiles
    if desc.guidance == GT.RADAR_PASSIVE or name_matches(upper, ARM_NAMES) then
        return "MAGNUM", weapon_name
    end

    local is_aam = (desc.missileCategory == MC.AAM)
        or (desc.missileCategory == nil
            and (name_matches(upper, FOX1_NAMES) or name_matches(upper, FOX2_NAMES)
                 or name_matches(upper, FOX3_NAMES)))

    if not is_aam then
        return "RIFLE", weapon_name                -- air-to-ground / cruise / anti-ship
    end

    -- Fox 1 = semi-active radar, Fox 2 = infrared, Fox 3 = active radar
    if desc.guidance == GT.IR then return "FOX_2", weapon_name end
    if desc.guidance == GT.RADAR_SEMIACTIVE then return "FOX_1", weapon_name end
    if desc.guidance == GT.RADAR_ACTIVE then return "FOX_3", weapon_name end

    if name_matches(upper, FOX2_NAMES) then return "FOX_2", weapon_name end
    if name_matches(upper, FOX1_NAMES) then return "FOX_1", weapon_name end

    return "FOX_3", weapon_name
end

-- ---- DCS world events ---------------------------------------------

local event_handler = {}

function event_handler:onEvent(event)

    local handled, handle_err = pcall(function()

        local initiator = event and event.initiator
        if not initiator then
            return
        end

        local ok_n, name = pcall(function() return initiator:getName() end)
        if not ok_n or not watched[name] then
            return
        end

        -- never narrate the human pilot's own actions
        local ok_p, player = pcall(function() return initiator:getPlayerName() end)
        if ok_p and player then
            return
        end

        local E = world.event
        local id = event.id
        local base = '"unit":' .. jstr(name) .. ',"t":' .. num(timer.getTime(), 1)

        if id == E.S_EVENT_SHOT then

            if not event.weapon then
                return
            end

            local callout, weapon_name = weapon_callout(event.weapon)

            if callout then
                log("EVENT " .. name .. " " .. callout .. " (" .. tostring(weapon_name) .. ")")
                send_event('"type":"WEAPON",' .. base
                    .. ',"callout":"' .. callout .. '","weapon":' .. jstr(weapon_name))
            end

        elseif id == E.S_EVENT_SHOOTING_START then

            local now = timer.getTime()
            if not last_gun_call[name] or now - last_gun_call[name] >= GUN_CALL_GAP then
                last_gun_call[name] = now
                send_event('"type":"WEAPON",' .. base .. ',"callout":"GUNS","weapon":"gun"')
            end

        elseif id == E.S_EVENT_TAKEOFF then

            log("EVENT " .. name .. " takeoff")
            send_event('"type":"TAKEOFF",' .. base)

        elseif id == E.S_EVENT_LAND then

            log("EVENT " .. name .. " landed")
            send_event('"type":"LAND",' .. base)

        elseif E.S_EVENT_KILL and id == E.S_EVENT_KILL then

            local target = event.target
            local air, target_type = false, ""

            if target then
                pcall(function()
                    local d = target:getDesc()
                    air = (d ~= nil) and (d.category == Unit.Category.AIRPLANE
                                          or d.category == Unit.Category.HELICOPTER)
                    target_type = target:getTypeName() or ""
                end)

                -- friendly fire is not a "splash"
                local same_side = false
                pcall(function() same_side = (target:getCoalition() == initiator:getCoalition()) end)
                if same_side then
                    return
                end
            end

            log("EVENT " .. name .. " kill " .. tostring(target_type))
            send_event('"type":"KILL",' .. base
                .. ',"air":' .. (air and "true" or "false")
                .. ',"target":' .. jstr(target_type))
        end
    end)

    if not handled then
        log("EVENT HANDLER ERROR: " .. tostring(handle_err))
    end
end

local handler_ok, handler_err = pcall(function()
    world.addEventHandler(event_handler)
end)

if handler_ok then
    log("EVENT HANDLER REGISTERED")
else
    log("EVENT HANDLER FAILED: " .. tostring(handler_err))
end

-- ---- contacts: what the wingman's sensors can see -----------------

local function add_detection(into, kind, entry, enemy)

    local obj = entry and entry.object
    if not obj then
        return
    end

    local ok_o, gid = pcall(function()
        if not obj:isExist() or obj:getCoalition() ~= enemy or not obj:inAir() then
            return nil
        end
        return obj:getGroup():getID()
    end)

    if not ok_o or not gid then
        return
    end

    local bucket = into[gid]

    if bucket and bucket.kind ~= kind then
        return                       -- already seen on radar; ignore the visual duplicate
    end

    if not bucket then
        bucket = { kind = kind, units = {}, type_known = false }
        into[gid] = bucket
    end

    table.insert(bucket.units, obj)

    if entry.type then
        bucket.type_known = true
    end
end

local function scan_unit_contacts(unit, name, now, enemy, D)

    local controller = unit:getController()
    if not controller then
        return
    end

    local found = {}

    local ok_r, radar_list = pcall(function()
        return controller:getDetectedTargets(D.RADAR, D.IRST)
    end)
    if ok_r and radar_list then
        for _, entry in ipairs(radar_list) do
            add_detection(found, "radar", entry, enemy)
        end
    end

    local ok_v, visual_list = pcall(function()
        return controller:getDetectedTargets(D.VISUAL, D.OPTIC)
    end)
    if ok_v and visual_list then
        for _, entry in ipairs(visual_list) do
            add_detection(found, "visual", entry, enemy)
        end
    end

    local seen = tracks[name] or {}
    tracks[name] = seen

    local lead = find_leader(unit) or unit
    local lead_point = lead:getPoint()

    local best, best_range = nil, nil

    for gid, bucket in pairs(found) do

        if seen[gid] and (now - seen[gid]) <= CONTACT_FORGET_AFTER then
            seen[gid] = now                              -- still the same contact
        else
            -- a new contact: remember the closest unit of the group
            local nearest, nearest_d = nil, nil
            for _, obj in ipairs(bucket.units) do
                local d = dist2d(obj:getPoint(), lead_point)
                if not nearest_d or d < nearest_d then
                    nearest, nearest_d = obj, d
                end
            end

            if nearest and nearest_d <= CONTACT_MAX_RANGE_NM * NM_TO_M
               and (not best_range or nearest_d < best_range) then
                best_range = nearest_d
                best = { gid = gid, bucket = bucket, unit = nearest }
            end
        end
    end

    -- forget groups not seen for a while
    for gid, last in pairs(seen) do
        if now - last > 120 then
            seen[gid] = nil
        end
    end

    if not best then
        return
    end

    -- one call at a time; anything left over is still "new" next sweep
    if last_contact_call[name] and (now - last_contact_call[name]) < CONTACT_MIN_GAP then
        return
    end

    last_contact_call[name] = now
    seen[best.gid] = now

    local tp = best.unit:getPoint()
    local true_bearing = bearing_true(lead_point, tp)
    local rel = (true_bearing - get_heading(lead) + 360) % 360
    local brg_mag = (true_bearing - MAGNETIC_VARIATION_DEG + 360) % 360

    local target_type = "null"
    if best.bucket.type_known and #best.bucket.units == 1 then
        local ok_t, type_name = pcall(function() return best.unit:getTypeName() end)
        if ok_t and type_name then
            target_type = jstr(type_name)
        end
    end

    log(string.format("CONTACT %s: %s rel %.0f range %.0f nm", name, best.bucket.kind, rel, best_range / NM_TO_M))

    send_event('"type":"CONTACT","unit":' .. jstr(name)
        .. ',"t":' .. num(now, 1)
        .. ',"kind":"' .. best.bucket.kind .. '"'
        .. ',"rel_deg":' .. num(rel, 0)
        .. ',"brg":' .. num(brg_mag, 0)
        .. ',"range_nm":' .. num(best_range / NM_TO_M, 2)
        .. ',"alt_ft":' .. num(tp.y / FT_TO_M, 0)
        .. ',"count":' .. #best.bucket.units
        .. ',"target_type":' .. target_type)
end

local function scan_contacts()

    local now = timer.getTime()
    if now < next_scan then
        return
    end
    next_scan = now + CONTACT_SCAN_INTERVAL

    local side = resolve_friendly_side()
    if not side then
        return
    end

    local D = (Controller and Controller.Detection)
        or { VISUAL = 1, OPTIC = 2, RADAR = 4, IRST = 8 }

    for name in pairs(watched) do
        local unit = Unit.getByName(name)
        if unit and unit:isExist() and unit:inAir() and not unit:getPlayerName() then
            local scanned, scan_err = pcall(scan_unit_contacts, unit, name, now, enemy_side(side), D)
            if not scanned then
                log("CONTACT SCAN ERROR: " .. tostring(scan_err))
            end
        end
    end
end

local function handle_watch(fields)
    local name = fields.unit
    if name and name ~= "" and not watched[name] then
        watched[name] = true
        log("WATCHING " .. name .. " (callouts on)")
    end
end

local HANDLERS = {
    FLIGHT          = handle_flight,
    ROE             = handle_roe,
    COUNTERMEASURES = handle_countermeasures,
    RADAR           = handle_radar,
    EMCON           = handle_emcon,
    RTB             = handle_rtb,
    ORBIT           = handle_orbit,
    FOLLOW          = handle_follow,
    BREAK           = handle_break,
    BUGOUT          = handle_bugout,
    ENGAGE          = handle_engage,
    INBOUND         = handle_inbound,
    RESUME          = handle_resume,
    WATCH           = handle_watch,
    CLEAR           = handle_clear,
}

local function handle_command(line)

    line = string.gsub(line, "[\r\n]+$", "")

    local action, fields = parse_command(line)
    local handler = action and HANDLERS[action]

    if handler then
        handler(fields)
    else
        log("UNKNOWN COMMAND: " .. tostring(line))
    end
end

-- Keeps orders true: re-aims a drifting HOLD, refreshes a PURSUE,
-- and forgets aircraft that died or landed.
local function maintain_orders()

    local now = timer.getTime()

    for name, order in pairs(orders) do

        local unit = Unit.getByName(name)

        if not unit or not unit:isExist() or not unit:inAir() then
            orders[name] = nil
            log("ORDERS DROPPED (aircraft gone or landed): " .. name)

        elseif order.kind == "PURSUE" then

            if (now - order.last_issue) >= PURSUE_REFRESH then
                local issued, why = issue_pursue(unit, order)
                if not issued then
                    log("PURSUIT ENDED (" .. tostring(why) .. "): " .. name)
                    hold_here(unit)
                end
            end

        elseif order.tx and (now - order.last_issue) >= REISSUE_MIN_INTERVAL then

            local p = unit:getPoint()
            local dx = order.tx - p.x
            local dz = order.tz - p.z

            local bearing = math.deg(math.atan2(dz, dx))
            if bearing < 0 then
                bearing = bearing + 360
            end

            local error_deg = math.abs(((bearing - order.hdg_true + 540) % 360) - 180)
            local remaining = math.sqrt(dx * dx + dz * dz)

            if error_deg > HEADING_TOLERANCE_DEG or remaining < ROUTE_LEG_M * 0.4 then
                issue_route(unit, order)
            end
        end
    end
end

local function poll_commands()

    if cmd_ready then
        for _ = 1, MAX_CMDS_PER_POLL do
            local data = cmd_udp:receive()
            if not data then
                break
            end
            local handled, handle_err = pcall(handle_command, data)
            if not handled then
                log("COMMAND ERROR: " .. tostring(handle_err))
            end
        end
    end

    maintain_orders()
    scan_contacts()
end


-- =============================================================
-- AWACS FEED  (DCS -> ATC app, UDP 5015)
--
-- One packet per AWACS_INTERVAL, always the COMPLETE picture (the ATC app
-- forgets any contact that is missing from a packet):
--   {"timestamp":123.4,
--    "ownship":{"x":N,"y":alt_m,"z":E},
--    "contacts":[{"id":16778241,"type":"MiG-29S","x":..,"y":..,"z":..,
--                 "distance_known":true,"type_known":true,
--                 "relationship":"HOSTILE"}, ...]}
-- Coordinates are DCS world metres (x = north, z = east), y = altitude.
-- =============================================================

do
    local awacs_udp = socket.udp()
    local awacs_mode_logged = nil
    local awacs_packets = 0
    local awacs_warned_player = false
    local awacs_last_count = nil
    local awacs_last_count_log = -999

    local function awacs_player(side)

        for _, entry in ipairs(get_friendly_units(side)) do
            local name = entry.unit:getPlayerName()
            if name and (not AWACS_PLAYER_NAME or name == AWACS_PLAYER_NAME) then
                return entry.unit
            end
        end

        return nil
    end

    -- Friendly AI AWACS aircraft that are flying right now.
    local function awacs_aircraft(side)

        local out = {}
        local hint = string.upper(AWACS_NAME_HINT or "")

        for _, entry in ipairs(get_friendly_units(side)) do

            local u = entry.unit

            if not u:getPlayerName() and u:inAir() then

                local ok_t, type_name = pcall(function() return u:getTypeName() end)
                local match = ok_t and AWACS_TYPES[type_name] or false

                if not match and hint ~= "" then
                    match = string.find(string.upper(u:getName()), hint, 1, true)
                        or string.find(string.upper(entry.group:getName()), hint, 1, true)
                end

                if match then
                    table.insert(out, u)
                end
            end
        end

        return out
    end

    -- Adds one aircraft to `found` (keyed by unit id). Returns nothing.
    local function awacs_add(found, obj, side, own_id, own_point, type_known, distance_known)

        local ok_o, item = pcall(function()

            if not obj:isExist() or not obj:inAir() then
                return nil
            end

            local id = obj:getID()
            if id == own_id then
                return nil
            end

            local desc = obj:getDesc()
            local category = desc and desc.category
            if category ~= Unit.Category.AIRPLANE and category ~= Unit.Category.HELICOPTER then
                return nil
            end

            local c = obj:getCoalition()
            local relationship
            if c == side then
                if not AWACS_INCLUDE_FRIENDLIES then
                    return nil
                end
                relationship = "FRIENDLY"
            elseif c == enemy_side(side) then
                relationship = "HOSTILE"
            else
                return nil                       -- neutral coalition
            end

            local p = obj:getPoint()
            local d = dist2d(p, own_point)

            if d > AWACS_MAX_RANGE_NM * NM_TO_M then
                return nil
            end

            return {
                id = id,
                x = p.x, y = p.y, z = p.z,
                d = d,
                type = obj:getTypeName(),
                relationship = relationship,
            }
        end)

        if not ok_o or not item then
            return
        end

        local existing = found[item.id]

        if existing then
            -- seen by two AWACS: keep the best knowledge of either
            existing.type_known = existing.type_known or type_known
            existing.distance_known = existing.distance_known or distance_known
        else
            item.type_known = type_known
            item.distance_known = distance_known
            found[item.id] = item
        end
    end

    local function awacs_contact_json(c)

        return "{"
            .. '"id":' .. string.format("%d", c.id) .. ","
            .. '"type":' .. (c.type_known and jstr(c.type) or "null") .. ","
            .. '"x":' .. num(c.x) .. ","
            .. '"y":' .. num(c.y) .. ","
            .. '"z":' .. num(c.z) .. ","
            .. '"distance_known":' .. (c.distance_known and "true" or "false") .. ","
            .. '"type_known":' .. (c.type_known and "true" or "false") .. ","
            .. '"relationship":"' .. c.relationship .. '"'
            .. "}"
    end

    local function send_awacs_picture()

        if not awacs_udp then
            return
        end

        local side = resolve_friendly_side()
        if not side then
            return
        end

        local player = awacs_player(side)

        if not player then
            if AWACS_PLAYER_NAME and not awacs_warned_player then
                awacs_warned_player = true
                log("AWACS FEED: player '" .. AWACS_PLAYER_NAME .. "' not found")
            end
            return
        end

        local own_point = player:getPoint()
        local own_id = player:getID()

        local D = (Controller and Controller.Detection)
            or { VISUAL = 1, OPTIC = 2, RADAR = 4, IRST = 8 }

        local found = {}

        -- ---- choose where the picture comes from ----

        local sources = awacs_aircraft(side)
        local mode = AWACS_SOURCE

        if mode == "auto" then
            mode = (#sources > 0) and "awacs" or "all"
        end

        if mode ~= awacs_mode_logged then
            awacs_mode_logged = mode
            log(string.format(
                "AWACS FEED: source = %s (%d AWACS aircraft airborne)",
                mode, #sources
            ))
        end

        if mode == "awacs" then

            local flags = { D.RADAR }
            if D.DLINK then
                table.insert(flags, D.DLINK)
            end

            for _, u in ipairs(sources) do

                local controller = u:getController()

                if controller then

                    local ok_d, list = pcall(function()
                        return controller:getDetectedTargets((unpack or table.unpack)(flags))
                    end)

                    if ok_d and list then
                        for _, entry in ipairs(list) do
                            if entry.object then
                                awacs_add(
                                    found, entry.object, side, own_id, own_point,
                                    entry.type == true, entry.distance == true
                                )
                            end
                        end
                    end
                end
            end

        else

            for _, entry in ipairs(enemy_air_units()) do
                awacs_add(found, entry.unit, side, own_id, own_point, true, true)
            end

            if AWACS_INCLUDE_FRIENDLIES then
                for _, entry in ipairs(get_friendly_units(side)) do
                    awacs_add(found, entry.unit, side, own_id, own_point, true, true)
                end
            end
        end

        -- ---- nearest first, capped so it fits one datagram ----

        local list = {}
        for _, item in pairs(found) do
            table.insert(list, item)
        end

        table.sort(list, function(a, b) return a.d < b.d end)

        local parts = {}
        for i = 1, math.min(#list, AWACS_MAX_CONTACTS) do
            parts[i] = awacs_contact_json(list[i])
        end

        local payload =
            "{"
            .. '"timestamp":' .. num(timer.getTime(), 2) .. ","
            .. '"ownship":{'
            .. '"x":' .. num(own_point.x) .. ","
            .. '"y":' .. num(own_point.y) .. ","
            .. '"z":' .. num(own_point.z)
            .. "},"
            .. '"contacts":[' .. table.concat(parts, ",") .. "]"
            .. "}"

        local sent_ok, sent_err = pcall(function()
            return awacs_udp:sendto(payload, AWACS_HOST, AWACS_PORT)
        end)

        if not sent_ok then
            log("AWACS FEED SEND ERROR: " .. tostring(sent_err))
            return
        end

        -- say so whenever the picture changes size (at most every 5 s), so
        -- dcs.log shows whether the AWACS is actually seeing anything
        local now_t = timer.getTime()
        if #parts ~= awacs_last_count and (now_t - awacs_last_count_log) >= 5 then
            awacs_last_count = #parts
            awacs_last_count_log = now_t
            log(string.format(
                "AWACS FEED: picture now has %d contact(s) [%s, %d AWACS aircraft]",
                #parts, mode, #sources
            ))
        end

        awacs_packets = awacs_packets + 1
        if awacs_packets == 1 then
            log("AWACS FEED: FIRST PICTURE SENT (" .. #parts .. " contacts)")
        end
    end

    if awacs_udp then

        log("AWACS FEED READY -> " .. AWACS_HOST .. ":" .. AWACS_PORT)

        timer.scheduleFunction(
            function(_, time)
                local ok_run, run_err = pcall(send_awacs_picture)
                if not ok_run then
                    log("AWACS FEED ERROR: " .. tostring(run_err))
                end
                return time + AWACS_INTERVAL
            end,
            nil,
            timer.getTime() + 1.5
        )

    else
        log("AWACS FEED: FAILED TO CREATE SOCKET")
    end
end


-- =============================================================
-- START
-- =============================================================

log("ONLINE")

timer.scheduleFunction(
    function(_, time)
        local ok_run, next_time = pcall(send_telemetry)
        if not ok_run then
            log("TICK ERROR: " .. tostring(next_time))
            return time + UPDATE_INTERVAL
        end
        return next_time
    end,
    nil,
    timer.getTime() + 1
)

timer.scheduleFunction(
    function(_, time)
        local ok_run, run_err = pcall(poll_commands)
        if not ok_run then
            log("COMMAND TICK ERROR: " .. tostring(run_err))
        end
        return time + CMD_POLL_INTERVAL
    end,
    nil,
    timer.getTime() + 1
)
