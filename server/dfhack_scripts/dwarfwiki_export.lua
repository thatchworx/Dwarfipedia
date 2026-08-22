-- dwarfwiki_export.lua
-- ============================================================================
-- Dumps the current fortress's roster, stocks, and related state to a JSON
-- file for DwarfWiki's Fortress dashboard to read. Run via:
--   dfhack-run dwarfwiki_export "C:/path/to/output.json"
-- (DwarfWiki's server does this for you when you click Refresh.)
--
-- Uses DFHack's documented dfhack.units.*/dfhack.items.*/dfhack.buildings.*
-- helper functions wherever one exists, since those are maintained across
-- versions specifically so scripts like this don't break on raw
-- df-structures field/shape changes. Every per-record read is wrapped in
-- pcall, so one bad field is skipped and logged to `_warnings` in the
-- output rather than failing the whole export.
-- ============================================================================

local utils = require('utils')
local json = require('json')

local args = {...}
local OUT_PATH = args[1]
if not OUT_PATH then
  qerror("dwarfwiki_export: no output path given. Usage: dfhack-run dwarfwiki_export <path.json>")
end

local warnings = {}
-- getReadableName() and friends return CP437-encoded text, not UTF-8 (per
-- DFHack's own docs), which breaks strict-UTF-8 JSON parsing on the
-- Python side if left unconverted. Every string that reaches the output
-- goes through df2utf plus a control-character strip before use.
local function sanitize(s)
  s = tostring(s)
  local ok, utf8s = pcall(dfhack.df2utf, s)
  if ok and utf8s then s = utf8s end
  s = s:gsub('[\r\n]+', ' ')
  s = s:gsub('%c', '')
  return s
end
local function warn(msg)
  table.insert(warnings, sanitize(msg))
end

-- Runs fn(...), returns its result on success or nil (and logs `label`) on
-- any error, so one bad field doesn't fail the whole export.
local function safe(label, fn, ...)
  local ok, result = pcall(fn, ...)
  if ok then return result end
  warn(label .. ": " .. tostring(result))
  return nil
end

-- ----------------------------------------------------------------------
-- Environment / meta
-- ----------------------------------------------------------------------
local meta = {
  exported_at = os.date("!%Y-%m-%dT%H:%M:%SZ"),
  df_version = safe("df_version", function() return dfhack.getDFVersion() end) or "unknown",
  dfhack_version = safe("dfhack_version", function() return dfhack.getDFHackVersion() end) or "unknown",
}
local ok_year, cur_year = pcall(function() return df.global.cur_year end)
if ok_year then meta.cur_year = cur_year end
local ok_tick, cur_tick = pcall(function() return df.global.cur_year_tick end)
if ok_tick then meta.cur_year_tick = cur_tick end

local fort_name = safe("fortress_name", function()
  return dfhack.translation.translateName(df.global.world.world_data.active_site[0].name, true)
end)
meta.fortress_name = sanitize(fort_name or "Unnamed fortress")

-- ----------------------------------------------------------------------
-- Dwarves (units.active, filtered to citizens of this fortress)
-- ----------------------------------------------------------------------
-- Attributes, skills, labors, needs/stress, and a health summary are
-- included; the personality.thoughts log (long emotional-event text) is
-- deliberately left out.
local PHYS_ATTRS = {
  'STRENGTH','AGILITY','TOUGHNESS','ENDURANCE','RECUPERATION',
  'DISEASE_RESISTANCE',
}
local MENT_ATTRS = {
  'ANALYTICAL_ABILITY','FOCUS','WILLPOWER','CREATIVITY','INTUITION',
  'PATIENCE','MEMORY','LINGUISTIC_ABILITY','SPATIAL_SENSE','KINESTHETIC_SENSE',
  'EMPATHY','SOCIAL_AWARENESS','MUSICALITY',
}

local dwarves = {}
for _, unit in ipairs(df.global.world.units.active) do
  local ok_civ, isCitizen = pcall(dfhack.units.isCitizen, unit)
  if ok_civ and isCitizen then
    local d = {}
    d.id = unit.id
    d.name = sanitize(safe("unit " .. unit.id .. " name", function()
      return dfhack.units.getReadableName(unit)
    end) or ("Unit #" .. unit.id))
    d.profession = sanitize(safe("unit " .. unit.id .. " profession", function()
      return dfhack.units.getProfessionName(unit)
    end) or "?")
    d.age = safe("unit " .. unit.id .. " age", function() return dfhack.units.getAge(unit, true) end)
    d.sex = safe("unit " .. unit.id .. " sex", function()
      if unit.sex == 0 then return "female" elseif unit.sex == 1 then return "male" else return "unknown" end
    end)
    d.migrant = safe("unit " .. unit.id .. " migrant", function() return unit.flags1.important_historical_figure == false end)

    -- physical / mental attributes
    d.attributes = {}
    for _, a in ipairs(PHYS_ATTRS) do
      local v = safe("unit " .. unit.id .. " phys " .. a, function()
        return dfhack.units.getPhysicalAttrValue(unit, df.physical_attribute_type[a])
      end)
      if v then d.attributes[a] = v end
    end
    for _, a in ipairs(MENT_ATTRS) do
      local v = safe("unit " .. unit.id .. " ment " .. a, function()
        return dfhack.units.getMentalAttrValue(unit, df.mental_attribute_type[a])
      end)
      if v then d.attributes[a] = v end
    end

    -- skills (name + level via the official nominal-skill helper, not raw
    -- experience math, so this matches what the game itself would show)
    d.skills = {}
    local ok_skills, soul = pcall(function() return unit.status.current_soul end)
    if ok_skills and soul then
      local ok_iter, skillList = pcall(function() return soul.skills end)
      if ok_iter and skillList then
        for _, sk in ipairs(skillList) do
          local sid = sk.id
          local sname = safe("skill name " .. tostring(sid), function()
            return df.job_skill.attrs[sid].caption
          end)
          local level = safe("skill level " .. tostring(sid), function()
            return dfhack.units.getNominalSkill(unit, sid, false)
          end)
          if sname and level then
            table.insert(d.skills, {name = sanitize(sname), level = level, experience = sk.experience})
          end
        end
      end
    end

    -- enabled labors (only the "on" ones, to keep this compact)
    d.labors = {}
    local ok_lab, laborsArr = pcall(function() return unit.status.labors end)
    if ok_lab and laborsArr then
      for laborId, enabled in ipairs(laborsArr) do
        if enabled then
          local lname = safe("labor name " .. tostring(laborId), function()
            return df.unit_labor[laborId - 1]
          end)
          if lname then table.insert(d.labors, sanitize(lname)) end
        end
      end
    end

    -- needs + stress (kept; explicitly NOT the .thoughts log)
    d.stress = safe("unit " .. unit.id .. " stress", function()
      return soul.personality.stress
    end)
    d.needs = {}
    local ok_needs, needsArr = pcall(function() return soul.personality.needs end)
    if ok_needs and needsArr then
      for _, n in ipairs(needsArr) do
        local nname = safe("need name", function() return df.need_type[n.id] end)
        if nname then
          table.insert(d.needs, {need = sanitize(nname), level = n.focus_level})
        end
      end
    end

    -- health summary (counts, not a full body diagram. Enough for a
    -- roster column, not a surgery screen)
    d.dead = safe("unit " .. unit.id .. " dead", function() return dfhack.units.isDead(unit) end) or false
    d.wound_count = safe("unit " .. unit.id .. " wounds", function() return #unit.body.wounds end) or 0

    table.insert(dwarves, d)
  end
end

-- ----------------------------------------------------------------------
-- Stocks. Aggregated counts, not one row per physical item (keeps the
-- file small and is what a "stock levels" table actually wants).
-- ----------------------------------------------------------------------
local stockTotals = {}   -- key: "type|material" -> {label=, material=, count=}
-- Each flag is checked independently rather than in one combined pcall:
-- DFHack bitfields error on an unrecognized flag name (unlike a plain Lua
-- table, which would just return nil), so checking all three together
-- means one bad name on a given build silently excludes every item.
local function itemFlag(item, name)
  local ok, v = pcall(function() return item.flags[name] end)
  if ok then return v end
  return false
end
for _, item in ipairs(df.global.world.items.all) do
  local include = not itemFlag(item, 'garbage_collect')
    and not itemFlag(item, 'forbidden')
    and not itemFlag(item, 'dump')
  if include then
    local label = safe("item " .. item.id .. " desc", function()
      return dfhack.items.getReadableDescription(item)
    end)
    if label then label = sanitize(label) end
    local matinfo = safe("item " .. item.id .. " mat", function()
      return dfhack.matinfo.decode(item)
    end)
    local matname = matinfo and safe("item " .. item.id .. " matname", function()
      return matinfo:toString()
    end) or "unknown material"
    matname = sanitize(matname)
    if label then
      local key = label .. "|" .. matname
      if not stockTotals[key] then
        stockTotals[key] = {label = label, material = matname, count = 0}
      end
      local stack = safe("item " .. item.id .. " stack", function()
        return item:getStackSize()
      end) or 1
      stockTotals[key].count = stockTotals[key].count + stack
    end
  end
end
local stocks = {}
for _, v in pairs(stockTotals) do table.insert(stocks, v) end

-- ----------------------------------------------------------------------
-- Squads
-- ----------------------------------------------------------------------
local squads = {}
local ok_sq, allSquads = pcall(function() return df.global.world.squads.all end)
if ok_sq and allSquads then
  for _, sq in ipairs(allSquads) do
    local s = {id = sq.id}
    s.name = sanitize(safe("squad " .. sq.id .. " name", function()
      return dfhack.translation.translateName(sq.name, true)
    end) or ("Squad #" .. sq.id))
    s.members = {}
    local ok_pos, positions = pcall(function() return sq.positions end)
    if ok_pos and positions then
      for _, pos in ipairs(positions) do
        local uid = safe("squad position occupant", function() return pos.occupant end)
        if uid and uid >= 0 then
          local u = safe("find unit " .. uid, function() return df.unit.find(uid) end)
          if u then
            table.insert(s.members, sanitize(safe("squad member name", function()
              return dfhack.units.getReadableName(u)
            end) or ("Unit #" .. uid)))
          end
        end
      end
    end
    table.insert(squads, s)
  end
end

-- ----------------------------------------------------------------------
-- Jobs. World.jobs.list is a linked list, not a plain array, so it's
-- walked link-by-link rather than with ipairs. Capped defensively in
-- case of a malformed/circular list on some save.
-- ----------------------------------------------------------------------
local jobs = {}
local ok_jl, firstLink = pcall(function() return df.global.world.jobs.list.next end)
if ok_jl then
  local link, guard = firstLink, 0
  while link and guard < 3000 do
    local job = safe("job link item", function() return link.item end)
    if job then
      local jname = safe("job name " .. tostring(job.id), function()
        return dfhack.job.getName(job)
      end)
      local worker = safe("job worker", function() return dfhack.job.getWorker(job) end)
      local workerName = worker and sanitize(safe("job worker name", function()
        return dfhack.units.getReadableName(worker)
      end) or "") or nil
      table.insert(jobs, {id = job.id, name = sanitize(jname or "job"), worker = workerName})
    end
    link = safe("job link next", function() return link.next end)
    guard = guard + 1
  end
end

-- ----------------------------------------------------------------------
-- Rooms. Any building with an assigned owner (bedrooms, offices, etc).
-- ----------------------------------------------------------------------
local rooms = {}
local ok_bl, allBuildings = pcall(function() return df.global.world.buildings.all end)
if ok_bl and allBuildings then
  for _, bld in ipairs(allBuildings) do
    local owner = safe("building owner " .. tostring(bld.id), function()
      return dfhack.buildings.getOwner(bld)
    end)
    if owner then
      local rname = safe("building name " .. tostring(bld.id), function()
        return dfhack.buildings.getName(bld)
      end)
      table.insert(rooms, {
        id = bld.id,
        name = sanitize(rname or "Room"),
        owner = sanitize(safe("room owner name", function()
          return dfhack.units.getReadableName(owner)
        end) or "?"),
      })
    end
  end
end

-- ----------------------------------------------------------------------
-- Nobles. Dfhack.units.getNoblePositions is the documented, stable way
-- to ask "what noble roles does this unit hold", rather than digging
-- through entity assignment structures directly.
-- ----------------------------------------------------------------------
local nobles = {}
for _, unit in ipairs(df.global.world.units.active) do
  local ok_civ, isCitizen = pcall(dfhack.units.isCitizen, unit)
  if ok_civ and isCitizen then
    local positions = safe("noble positions " .. unit.id, function()
      return dfhack.units.getNoblePositions(unit)
    end)
    if positions then
      for _, p in ipairs(positions) do
        local pname = safe("noble position name", function()
          return p.position.name[0]
        end) or safe("noble position code", function() return p.position.code end) or "Noble"
        table.insert(nobles, {
          unit_id = unit.id,
          name = sanitize(safe("noble unit name", function()
            return dfhack.units.getReadableName(unit)
          end) or "?"),
          position = sanitize(pname),
        })
      end
    end
  end
end

-- ----------------------------------------------------------------------
-- Justice and Trade. DFHack's crime/caravan structures are less
-- standardized than units/items, so each section is wrapped in one pcall
-- around the whole block rather than per-record: if the shape doesn't
-- match this DFHack build, it fails as one clear warning and an empty
-- list.
-- ----------------------------------------------------------------------
local justice = {}
local ok_just, crimes = pcall(function() return df.global.world.crimes.all end)
if ok_just and crimes then
  for _, c in ipairs(crimes) do
    local ctype = safe("crime type", function() return tostring(c.classification) end) or "crime"
    local culprit = safe("crime culprit", function()
      local u = df.unit.find(c.culprit)
      return u and dfhack.units.getReadableName(u) or nil
    end)
    table.insert(justice, {id = c.id, type = sanitize(ctype), culprit = culprit and sanitize(culprit) or nil,
      year = safe("crime year", function() return c.year end)})
  end
else
  warn("justice: df.global.world.crimes.all not available on this DFHack build")
end

local trade = {}
local ok_trade, caravans = pcall(function() return df.global.plotinfo.caravans end)
if ok_trade and caravans then
  for _, car in ipairs(caravans) do
    local ename = safe("caravan entity", function()
      local ent = df.historical_entity.find(car.entity)
      return ent and dfhack.translation.translateName(ent.name, true) or nil
    end)
    table.insert(trade, {
      entity = ename and sanitize(ename) or "Unknown traders",
      time_remaining = safe("caravan time", function() return car.time_remaining end),
      trade_state = safe("caravan state", function() return tostring(car.trade_state) end),
    })
  end
else
  warn("trade: df.global.plotinfo.caravans not available on this DFHack build")
end

-- ----------------------------------------------------------------------
-- Headline totals. The small, cheap numbers used for the history graph.
-- Everything above is the "current state" payload; this block is what
-- gets appended to a rolling log on the server side.
-- ----------------------------------------------------------------------
local headline = {
  population = #dwarves,
  item_count = safe("item total", function() return #df.global.world.items.all end) or 0,
  building_count = safe("building total", function() return #df.global.world.buildings.all end) or 0,
}

local out = {
  meta = meta,
  headline = headline,
  dwarves = dwarves,
  stocks = stocks,
  squads = squads,
  jobs = jobs,
  rooms = rooms,
  nobles = nobles,
  justice = justice,
  trade = trade,
  _warnings = warnings,
}

local encoded = json.encode(out)
-- Decode our own output before committing it to disk, if this DFHack
-- build's json encoder mishandles something, a small always-valid
-- fallback beats a corrupt file the server can't parse. The raw
-- pre-fallback output is saved alongside the real file for debugging.
local wrote_full = true
local self_check_ok = pcall(json.decode, encoded)
if not self_check_ok then
  wrote_full = false
  local debug_path = OUT_PATH .. ".broken"
  local df_ = io.open(debug_path, "wb")
  if df_ then df_:write(encoded); df_:close() end
  table.insert(warnings, "export produced invalid JSON on this run and was "
    .. "replaced with this fallback. The roster/stocks below are empty "
    .. "as a result. The raw broken output was saved next to this file "
    .. "as current.json.broken for debugging.")
  encoded = json.encode({
    meta = meta, headline = {population = 0, item_count = 0, building_count = 0},
    dwarves = {}, stocks = {}, squads = {}, jobs = {}, rooms = {}, nobles = {},
    justice = {}, trade = {}, _warnings = warnings,
  })
end

-- Binary mode: Windows text-mode writes silently rewrite "\n" to "\r\n",
-- which has no business happening inside an encoded JSON payload.
local f = io.open(OUT_PATH, "wb")
if not f then
  qerror("dwarfwiki_export: could not open output path for writing: " .. OUT_PATH)
end
f:write(encoded)
f:close()

if wrote_full then
  print("dwarfwiki_export: wrote " .. #dwarves .. " dwarves, " .. #stocks ..
        " stock lines, " .. #warnings .. " warnings -> " .. OUT_PATH)
else
  print("dwarfwiki_export: JSON encoding failed. Wrote an EMPTY fallback "
        .. "(0 dwarves, 0 stocks) instead. See " .. OUT_PATH .. ".broken -> " .. OUT_PATH)
end
