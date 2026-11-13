-- AdminServer: erdl18 (UserId 6157267885) ONLY. The server re-checks the UserId
-- on EVERY admin action. Nothing else can trigger any of this.
local Players = game:GetService("Players")

local AdminServer = {}
local ctx, Config, Remotes, State, Map, Controls

local ADMIN_ID = 6157267885

local function isAdmin(player)
	return player ~= nil and player.UserId == ADMIN_ID
end

local function sendLog(player)
	Remotes.AdminData:FireClient(player, { kind = "log", entries = State.log })
end

local function sendPlayers(player)
	local list = {}
	for _, pl in ipairs(Players:GetPlayers()) do
		table.insert(list, {
			name = pl.Name,
			userId = pl.UserId,
			money = State.money,
			rep = State.rep,
			sanity = ctx.Sanity.Get(pl),
			desk = Controls.playerDesks[pl],
		})
	end
	Remotes.AdminData:FireClient(player, { kind = "players", list = list })
end

local function findPlayer(name)
	for _, pl in ipairs(Players:GetPlayers()) do
		if pl.Name:lower() == tostring(name):lower() then return pl end
	end
	return nil
end

local actions

actions = {
	-- GAME
	start = function()
		if State.phase == "Lobby" or State.phase == "GameOver" then
			Controls.startNight(math.max(1, State.night))
		end
	end,
	pause = function(data)
		State.toggles.paused = data == true or data == "true"
		Controls.log("Admin paused=" .. tostring(State.toggles.paused))
	end,
	endGame = function()
		State.phase = "Lobby"
		ctx.Hunt.Stop()
		ctx.sendState()
	end,
	setNight = function(data)
		local n = math.clamp(math.floor(tonumber(data) or 1), 1, 5)
		ctx.Hunt.Stop()
		Controls.startNight(n)
	end,
	nextNight = function()
		if State.phase == "Dawn" or State.phase == "Shop" then
			if State.night >= 5 then
				State.phase = "Win"
				Remotes.EndScreen:FireAllClients(true, { money = State.money, stars = Controls.stars() })
			else
				Controls.startNight(State.night + 1)
			end
		end
	end,
	restartNight = function()
		State.money = State.snapshotMoney
		State.rep = State.snapshotRep
		Controls.startNight(State.night)
	end,
	skipDawn = function()
		if State.phase == "Dawn" or State.phase == "Shop" then
			actions.nextNight()
		end
	end,
	win = function()
		State.phase = "Win"
		Remotes.EndScreen:FireAllClients(true, { money = State.money, stars = Controls.stars() })
	end,
	lose = function()
		ctx.Hunt.lose()
	end,
	reset = function()
		ctx.Hunt.Stop()
		State.phase = "Lobby"
		State.night = 1
		State.money = Config.StartMoney
		State.rep = 0
		State.desksBought = 1
		ctx.Controls.setDeskBought(2, false)
		ctx.Controls.setDeskBought(3, false)
		State.rulesRevealed = 3
		Controls.resetRooms()
		ctx.Sanity.RefillAll()
		ctx.sendState()
		Controls.startNight(1)
	end,

	-- GUESTS
	spawnGuest = function()
		Controls.spawnGuest()
	end,
	forceHuman = function() State.forceNext = "human" end,
	forceMonster = function() State.forceNext = "monster" end,
	clearForce = function() State.forceNext = nil end,
	setTells = function(data)
		local guest = Controls.getGuest(data.guestId)
		if guest then
			guest.tells = data.tells or {}
			Controls.log("Admin set tells on guest " .. data.guestId)
		end
	end,
	removeCurrent = function()
		for id, g in pairs(State.activeGuests) do
			if g.model then g.model:Destroy() end
			State.activeGuests[id] = nil
			Remotes.GuestUpdate:FireAllClients({ desk = g.desk, id = id, present = false })
		end
	end,
	clearQueue = function()
		State.queueLeft = 0
		Controls.removeCurrent()
		Controls.log("Guest queue cleared")
	end,
	setQuotaGuests = function(data) State.quotaGuests = math.max(1, math.floor(tonumber(data) or 5)) end,
	setQuotaMonsters = function(data) State.quotaMonsters = math.max(0, math.floor(tonumber(data) or 1)) end,

	-- ECONOMY
	setMoney = function(data)
		State.money = math.floor(tonumber(data) or 0)
		ctx.sendState()
	end,
	giveMoney = function(data)
		State.money = State.money + math.floor(tonumber(data) or 0)
		ctx.sendState()
	end,
	setRep = function(data)
		State.rep = tonumber(data) or 0
		ctx.sendState()
	end,
	setSanity = function(data)
		local pl = findPlayer(data.player)
		if pl then ctx.Sanity.Set(pl, tonumber(data.value) or 100) end
	end,
	refillSanity = function() ctx.Sanity.RefillAll() end,
	setCoffeePrice = function(data)
		State.coffeePrice = math.max(0, math.floor(tonumber(data) or 5))
		ctx.sendState()
	end,

	-- DESKS
	giveDesk = function(data)
		local slot = math.clamp(math.floor(tonumber(data) or 2), 2, 3)
		if slot > State.desksBought then
			State.desksBought = slot
			Controls.setDeskBought(slot, true)
			ctx.sendState()
		end
	end,
	removeDesk = function(data)
		local slot = math.clamp(math.floor(tonumber(data) or 3), 2, 3)
		if slot >= State.desksBought then
			State.desksBought = slot - 1
			Controls.setDeskBought(slot, false)
			ctx.sendState()
		end
	end,
	unlockAllDesks = function()
		State.desksBought = 3
		Controls.setDeskBought(2, true)
		Controls.setDeskBought(3, true)
		ctx.sendState()
	end,
	setDeskPrice = function(data)
		local slot = tonumber(data.slot)
		local price = math.max(0, math.floor(tonumber(data.price) or 150))
		if slot == 2 or slot == 3 then
			Config.DeskPrices[slot] = price
			ctx.sendState()
		end
	end,

	-- HUNT
	startHunt = function()
		local monsters = {}
		for _, g in pairs(State.activeGuests) do
			if g.isMonster then table.insert(monsters, g) end
		end
		if #monsters == 0 then
			monsters = State.admittedMonsters
		end
		if #monsters == 0 then
			Controls.log("No monsters to hunt; spawn one first")
			return
		end
		task.spawn(function() ctx.Hunt.Run(ctx, monsters) end)
	end,
	stopHunt = function() ctx.Hunt.Stop() end,
	spawnMonster = function()
		State.forceNext = "monster"
		Controls.spawnGuest()
	end,
	removeMonsters = function()
		for _, g in pairs(State.activeGuests) do
			if g.isMonster and g.model then g.model:Destroy() end
		end
		for _, m in ipairs(State.admittedMonsters) do
			if m.model and m.model.Parent then m.model:Destroy() end
		end
		State.admittedMonsters = {}
	end,
	setHuntTimer = function(data) State.huntTime = math.max(5, math.floor(tonumber(data) or 60)) end,
	setMonsterSpeed = function(data) State.monsterSpeed = math.clamp(tonumber(data) or 16, 4, 40) end,

	-- MAP / WEATHER
	rain = function(data)
		ctx.VFX.SetRain(data.on, data.intensity)
	end,
	fog = function(data) ctx.VFX.SetFog(data == true or data == "on") end,
	sign = function(data)
		ctx.VFX.SetSign(data.on, data.color)
	end,
	lights = function(data) ctx.VFX.SetLights(data == true or data == "on") end,
	flicker = function()
		task.spawn(function() ctx.VFX.PowerFlicker(10) end)
	end,
	lockDoors = function()
		for num in pairs(Map.Doors) do Controls.setDoorLock(num, true) Controls.setDoor(num, false) end
	end,
	unlockDoors = function()
		for num in pairs(Map.Doors) do Controls.setDoorLock(num, false) end
	end,
	openDoors = function()
		for num in pairs(Map.Doors) do Controls.setDoor(num, true) end
	end,
	closeDoors = function()
		for num in pairs(Map.Doors) do Controls.setDoor(num, false) end
	end,
	teleport = function(data)
		local pl = findPlayer(data.player)
		if not pl then return end
		local char = pl.Character
		local hrp = char and char:FindFirstChild("HumanoidRootPart")
		if not hrp then return end
		local where = data.where
		if where == "lobby" then
			hrp.CFrame = CFrame.new(0, 4, 4)
		elseif where == "me" then
			local me = Players:GetPlayerByUserId(ADMIN_ID)
			local mhrp = me and me.Character and me.Character:FindFirstChild("HumanoidRootPart")
			if mhrp then hrp.CFrame = mhrp.CFrame * CFrame.new(2, 0, 2) end
		elseif where == "security" then
			hrp.CFrame = CFrame.new(-26.5, 4, 12.5)
		else
			local num = tonumber(where)
			if num and num >= 101 and num <= 106 then
				hrp.CFrame = CFrame.new((num - 101) * 10 - 25, 4, -40)
			end
		end
	end,

	-- PLAYERS
	heal = function(data)
		local pl = findPlayer(data)
		if pl then
			local hum = pl.Character and pl.Character:FindFirstChildOfClass("Humanoid")
			if hum then hum.Health = hum.MaxHealth end
			local hrp = pl.Character and pl.Character:FindFirstChild("HumanoidRootPart")
			if hrp then hrp.Anchored = false end
			Remotes.Downed:FireClient(pl, false)
			ctx.Sanity.Set(pl, 100)
		end
	end,
	kick = function(data)
		local pl = findPlayer(data)
		if pl then pl:Kick("Removed by admin.") end
	end,

	-- TOGGLES
	toggle = function(data)
		local name = tostring(data)
		if State.toggles[name] ~= nil then
			State.toggles[name] = not State.toggles[name]
			Controls.log("Toggle " .. name .. " = " .. tostring(State.toggles[name]))
			ctx.sendState()
		end
	end,

	-- LOG
	getLog = function(player) sendLog(player) end,
	listPlayers = function(player) sendPlayers(player) end,

	-- ALIASES used by the panel buttons
	rainOn = function() ctx.VFX.SetRain(true, 1) end,
	rainOff = function() ctx.VFX.SetRain(false) end,
	rainIntensity = function(data) ctx.VFX.SetRain(true, math.clamp(tonumber(data) or 1, 0.1, 3)) end,
	fogOn = function() ctx.VFX.SetFog(true) end,
	fogOff = function() ctx.VFX.SetFog(false) end,
	signOn = function() ctx.VFX.SetSign(true) end,
	signOff = function() ctx.VFX.SetSign(false) end,
	signColor = function(data) ctx.VFX.SetSign(true, data) end,
	lightsOn = function() ctx.VFX.SetLights(true) end,
	lightsOff = function() ctx.VFX.SetLights(false) end,
	teleportRoom = function(data) actions.teleport(data) end,
}

function AdminServer.Init(c)
	ctx = c
	Config = c.Config
	Remotes = c.Remotes
	State = c.State
	Map = c.Map
	Controls = c.Controls

	Remotes.Admin.OnServerEvent:Connect(function(player, action, data)
		if not isAdmin(player) then
			Controls.log("REJECTED admin action from " .. player.Name .. " (UserId " .. player.UserId .. ")")
			return
		end
		local fn = actions[action]
		if not fn then return end
		local ok, err = pcall(fn, data, player)
		if not ok then
			Controls.log("Admin action error (" .. tostring(action) .. "): " .. tostring(err))
		end
	end)

	Players.PlayerAdded:Connect(function(player)
		if isAdmin(player) then
			player:SetAttribute("NSM_Admin", true)
			player.Chatted:Connect(function(msg)
				if msg == ":admin" then
					Remotes.AdminData:FireClient(player, { kind = "open" })
				end
			end)
		end
	end)
end

function AdminServer.IsAdmin(player)
	return isAdmin(player)
end

return AdminServer
