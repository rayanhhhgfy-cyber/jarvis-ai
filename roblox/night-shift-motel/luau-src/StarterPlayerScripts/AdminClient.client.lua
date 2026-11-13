-- AdminClient: tabbed admin panel. ONLY built for UserId 6157267885 (erdl18).
-- The server re-checks the UserId on every action; this GUI simply does not
-- exist for anyone else.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local player = Players.LocalPlayer
local ADMIN_ID = 6157267885
if player.UserId ~= ADMIN_ID then return end

local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local old = pg:FindFirstChild("NSM_Admin")
if old then old:Destroy() end

local gui = Instance.new("ScreenGui")
gui.Name = "NSM_Admin"
gui.ResetOnSpawn = false
gui.Parent = pg

local function mk(class, props, parent)
	local o = Instance.new(class)
	for k, v in pairs(props) do o[k] = v end
	o.Parent = parent
	return o
end

local function fire(action, data)
	remotes.Admin:FireServer(action, data)
end

local adminBtn = mk("TextButton", { Size = UDim2.new(0, 110, 0, 42), Position = UDim2.new(1, -118, 0, 6), BackgroundColor3 = Color3.fromRGB(120, 20, 20), TextColor3 = Color3.fromRGB(255, 220, 220), TextScaled = true, Font = Enum.Font.Arcade, Text = "ADMIN", ZIndex = 20 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, adminBtn)

local panel = mk("Frame", { Size = UDim2.new(0.94, 0, 0.85, 0), Position = UDim2.new(0.03, 0, 0.075, 0), BackgroundColor3 = Color3.fromRGB(14, 14, 18), BackgroundTransparency = 0.05, Visible = false, ZIndex = 21 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 10) }, panel)
mk("UIStroke", { Color = Color3.fromRGB(120, 20, 20), Thickness = 2 }, panel)

local tabs = { "GAME", "GUESTS", "ECONOMY", "DESKS", "HUNT", "MAP", "PLAYERS", "TOGGLES", "LOG" }
local tabFrame = mk("Frame", { Size = UDim2.new(0, 110, 1, -10), Position = UDim2.new(0, 5, 0, 5), BackgroundTransparency = 1, ZIndex = 22 }, panel)
mk("UIListLayout", { Padding = UDim.new(0, 4) }, tabFrame)
local content = mk("Frame", { Size = UDim2.new(1, -130, 1, -50), Position = UDim2.new(0, 120, 0, 40), BackgroundTransparency = 1, ZIndex = 22 }, panel)
local titleBar = mk("TextLabel", { Size = UDim2.new(1, -130, 0, 32), Position = UDim2.new(0, 120, 0, 4), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 90, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "ADMIN PANEL", TextXAlignment = Enum.TextXAlignment.Left, ZIndex = 22 }, panel)
local closeBtn = mk("TextButton", { Size = UDim2.new(0, 60, 0, 28), Position = UDim2.new(1, -66, 0, 4), BackgroundColor3 = Color3.fromRGB(120, 20, 20), TextColor3 = Color3.fromRGB(255, 230, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "X", ZIndex = 23 }, panel)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, closeBtn)

local pages = {}
local function page(name)
	local f = mk("ScrollingFrame", { Size = UDim2.new(1, 0, 1, 0), BackgroundTransparency = 1, AutomaticCanvasSize = Enum.AutomaticSize.Y, CanvasSize = UDim2.new(0, 0, 0, 0), ScrollBarThickness = 6, Visible = false, ZIndex = 22 }, content)
	mk("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder }, f)
	pages[name] = f
	return f
end
for _, name in ipairs(tabs) do
	page(name)
	local b = mk("TextButton", { Size = UDim2.new(1, 0, 0, 34), BackgroundColor3 = Color3.fromRGB(40, 40, 52), TextColor3 = Color3.fromRGB(230, 230, 240), TextScaled = true, Font = Enum.Font.Arcade, Text = name, ZIndex = 23 }, tabFrame)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, b)
	b.MouseButton1Click:Connect(function()
		for n, f in pairs(pages) do f.Visible = (n == name) end
		titleBar.Text = "ADMIN — " .. name
		if name == "LOG" then fire("getLog") end
		if name == "PLAYERS" then fire("listPlayers") end
	end)
end

local function row(parent, order)
	local f = mk("Frame", { LayoutOrder = order, Size = UDim2.new(1, -8, 0, 40), BackgroundColor3 = Color3.fromRGB(24, 24, 32), ZIndex = 22 }, parent)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, f)
	return f
end

local order = 0
local function addBtn(parent, text, action, data)
	order = order + 1
	local f = row(parent, order)
	local b = mk("TextButton", { Size = UDim2.new(1, -10, 1, -8), Position = UDim2.new(0, 5, 0, 4), BackgroundColor3 = Color3.fromRGB(70, 30, 30), TextColor3 = Color3.fromRGB(255, 220, 220), TextScaled = true, Font = Enum.Font.Arcade, Text = text, ZIndex = 23 }, f)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, b)
	b.MouseButton1Click:Connect(function()
		fire(action, data)
	end)
	return b, f
end

local function addValueBtn(parent, text, action, buildData, default)
	order = order + 1
	local f = row(parent, order)
	f.Size = UDim2.new(1, -8, 0, 44)
	local box = mk("TextBox", { Size = UDim2.new(0, 110, 1, -10), Position = UDim2.new(0, 5, 0, 5), BackgroundColor3 = Color3.fromRGB(40, 40, 52), TextColor3 = Color3.fromRGB(255, 255, 255), TextScaled = true, Font = Enum.Font.Code, Text = tostring(default), ZIndex = 23 }, f)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, box)
	local b = mk("TextButton", { Size = UDim2.new(1, -135, 1, -10), Position = UDim2.new(0, 125, 0, 5), BackgroundColor3 = Color3.fromRGB(30, 70, 110), TextColor3 = Color3.fromRGB(220, 235, 255), TextScaled = true, Font = Enum.Font.Arcade, Text = text, ZIndex = 23 }, f)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, b)
	b.MouseButton1Click:Connect(function()
		fire(action, buildData(box.Text))
	end)
	return box
end

-- GAME
local g = pages.GAME
addBtn(g, "START GAME", "start")
addBtn(g, "PAUSE / RESUME GUESTS", "pause", true)
addBtn(g, "END GAME (back to lobby)", "endGame")
addValueBtn(g, "SET NIGHT (1-5)", "setNight", function(v) return tonumber(v) end, 1)
addBtn(g, "SKIP TO NEXT NIGHT", "nextNight")
addBtn(g, "RESTART CURRENT NIGHT", "restartNight")
addBtn(g, "SKIP TO DAWN", "skipDawn")
addBtn(g, "WIN NOW", "win")
addBtn(g, "LOSE NOW", "lose")
addBtn(g, "RESET EVERYTHING (fresh Night 1)", "reset")

-- GUESTS
local gu = pages.GUESTS
addBtn(gu, "SPAWN A GUEST NOW", "spawnGuest")
addBtn(gu, "FORCE NEXT: HUMAN", "forceHuman")
addBtn(gu, "FORCE NEXT: MONSTER", "forceMonster")
addBtn(gu, "CLEAR FORCE", "clearForce")
addBtn(gu, "REMOVE CURRENT GUEST(S)", "removeCurrent")
addBtn(gu, "CLEAR WHOLE QUEUE", "clearQueue")
addValueBtn(gu, "SET GUESTS PER NIGHT", "setQuotaGuests", function(v) return tonumber(v) end, 5)
addValueBtn(gu, "SET MONSTERS PER NIGHT", "setQuotaMonsters", function(v) return tonumber(v) end, 1)

-- ECONOMY
local e = pages.ECONOMY
addValueBtn(e, "SET TEAM MONEY", "setMoney", function(v) return tonumber(v) end, 100)
addValueBtn(e, "GIVE MONEY", "giveMoney", function(v) return tonumber(v) end, 50)
addValueBtn(e, "SET REPUTATION", "setRep", function(v) return tonumber(v) end, 0)
addValueBtn(e, "SET MY SANITY", "setSanity", function(v) return { player = player.Name, value = tonumber(v) } end, 100)
addBtn(e, "REFILL EVERYONE'S SANITY", "refillSanity")
addValueBtn(e, "SET COFFEE PRICE", "setCoffeePrice", function(v) return tonumber(v) end, 5)

-- DESKS
local d = pages.DESKS
addBtn(d, "GIVE DESK 2 FREE", "giveDesk", 2)
addBtn(d, "GIVE DESK 3 FREE", "giveDesk", 3)
addBtn(d, "REMOVE LAST DESK", "removeDesk", 3)
addBtn(d, "UNLOCK ALL DESKS", "unlockAllDesks")
addValueBtn(d, "SET DESK 2 PRICE", "setDeskPrice", function(v) return { slot = 2, price = tonumber(v) } end, 150)
addValueBtn(d, "SET DESK 3 PRICE", "setDeskPrice", function(v) return { slot = 3, price = tonumber(v) } end, 300)

-- HUNT
local h = pages.HUNT
addBtn(h, "START HUNT NOW", "startHunt")
addBtn(h, "STOP HUNT", "stopHunt")
addBtn(h, "SPAWN A MONSTER NOW", "spawnMonster")
addBtn(h, "REMOVE ALL MONSTERS", "removeMonsters")
addValueBtn(h, "SET HUNT TIMER (seconds)", "setHuntTimer", function(v) return tonumber(v) end, 60)
addValueBtn(h, "SET MONSTER WALK SPEED", "setMonsterSpeed", function(v) return tonumber(v) end, 16)

-- MAP / WEATHER
local m = pages.MAP
addBtn(m, "RAIN ON", "rainOn")
addBtn(m, "RAIN OFF", "rainOff")
addValueBtn(m, "RAIN INTENSITY (0.1-3)", "rainIntensity", function(v) return tonumber(v) end, 1)
addBtn(m, "FOG ON", "fogOn")
addBtn(m, "FOG OFF", "fogOff")
addBtn(m, "SIGN ON", "signOn")
addBtn(m, "SIGN OFF", "signOff")
addValueBtn(m, "SIGN COLOR (R,G,B 0-255)", "signColor", function(v)
	local parts = string.split(v, ",")
	return Color3.fromRGB(tonumber(parts[1]) or 255, tonumber(parts[2]) or 40, tonumber(parts[3]) or 40)
end, "255,40,40")
addBtn(m, "ALL LIGHTS ON", "lightsOn")
addBtn(m, "ALL LIGHTS OFF", "lightsOff")
addBtn(m, "TRIGGER POWER FLICKER NOW", "flicker")
addBtn(m, "LOCK ALL ROOM DOORS", "lockDoors")
addBtn(m, "UNLOCK ALL ROOM DOORS", "unlockDoors")
addBtn(m, "OPEN ALL DOORS", "openDoors")
addBtn(m, "CLOSE ALL DOORS", "closeDoors")

-- PLAYERS
local p = pages.PLAYERS
local playersList = mk("TextLabel", { LayoutOrder = 1, Size = UDim2.new(1, -8, 0, 120), BackgroundColor3 = Color3.fromRGB(24, 24, 32), TextColor3 = Color3.fromRGB(200, 200, 215), TextSize = 16, Font = Enum.Font.Code, Text = "Press PLAYERS tab to refresh...", TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, ZIndex = 22 }, p)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, playersList)
mk("TextBox", { LayoutOrder = 2, Size = UDim2.new(1, -8, 0, 34), BackgroundColor3 = Color3.fromRGB(40, 40, 52), TextColor3 = Color3.fromRGB(255, 255, 255), TextScaled = true, Font = Enum.Font.Code, Text = player.Name, PlaceholderText = "player name", Name = "TargetBox", ZIndex = 22 }, p)
local targetBox = p:FindFirstChild("TargetBox")
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, targetBox)
addBtn(p, "TELEPORT PLAYER -> LOBBY", "teleport", { where = "lobby", player = "TARGET" })
addBtn(p, "TELEPORT PLAYER -> SECURITY ROOM", "teleport", { where = "security", player = "TARGET" })
addBtn(p, "TELEPORT PLAYER -> ME", "teleport", { where = "me", player = "TARGET" })
addValueBtn(p, "TELEPORT PLAYER -> ROOM (101-106)", "teleportRoom", function(v) return { where = v, player = "TARGET" } end, "101")
addBtn(p, "HEAL / UN-DOWN PLAYER", "heal", "TARGET")
addBtn(p, "KICK PLAYER", "kick", "TARGET")

-- TOGGLES
local tg = pages.TOGGLES
addBtn(tg, "GOD MODE (cannot be caught)", "toggle", "god")
addBtn(tg, "INFINITE MONEY", "toggle", "infiniteMoney")
addBtn(tg, "NO SANITY DRAIN", "toggle", "noSanityDrain")
addBtn(tg, "INSTANT COFFEE WARMER", "toggle", "instantCoffee")
addBtn(tg, "FREEZE GUESTS (stop arrivals)", "toggle", "freeze")

-- LOG
local lg = pages.LOG
local logBox = mk("TextLabel", { LayoutOrder = 1, Size = UDim2.new(1, -8, 0, 900), BackgroundColor3 = Color3.fromRGB(10, 10, 14), TextColor3 = Color3.fromRGB(140, 255, 160), TextSize = 14, Font = Enum.Font.Code, Text = "", TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, ZIndex = 22 }, lg)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, logBox)

remotes.AdminData.OnClientEvent:Connect(function(payload)
	if payload.kind == "log" then
		local txt = ""
		for _, line in ipairs(payload.entries) do
			txt = txt .. line .. "\n"
		end
		logBox.Text = txt
	elseif payload.kind == "players" then
		local txt = ""
		for _, pl in ipairs(payload.list) do
			txt = txt .. pl.name .. "  ($" .. pl.money .. ", rep " .. pl.rep .. ", sanity " .. pl.sanity .. ")\n"
		end
		playersList.Text = txt
	elseif payload.kind == "open" then
		panel.Visible = true
	end
end)

adminBtn.MouseButton1Click:Connect(function()
	panel.Visible = not panel.Visible
end)
closeBtn.MouseButton1Click:Connect(function()
	panel.Visible = false
end)

-- fill "TARGET" with the name typed in the PLAYERS tab
local oldFire = fire
fire = function(action, data)
	if type(data) == "table" and data.player == "TARGET" then
		data.player = targetBox.Text
	elseif data == "TARGET" then
		data = targetBox.Text
	end
	oldFire(action, data)
end
