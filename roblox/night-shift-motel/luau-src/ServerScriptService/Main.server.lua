-- Main: game state machine, guest flow, decisions, consequences.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Debris = game:GetService("Debris")

local Config = require(ReplicatedStorage:WaitForChild("GameConfig"))
local MapBuilder = require(script.Parent:WaitForChild("MapBuilder"))
local GuestGen = require(script.Parent:WaitForChild("GuestGen"))
local VFXServer = require(script.Parent:WaitForChild("VFXServer"))
local SanityServer = require(script.Parent:WaitForChild("SanityServer"))
local HuntManager = require(script.Parent:WaitForChild("HuntManager"))
local ChoresServer = require(script.Parent:WaitForChild("ChoresServer"))
local ShopServer = require(script.Parent:WaitForChild("ShopServer"))
local AdminServer = require(script.Parent:WaitForChild("AdminServer"))

-- REMOTES
local Remotes = Instance.new("Folder")
Remotes.Name = "Remotes"
local remoteNames = {
	"StateUpdate", "Notify", "GuestUpdate", "Inspect", "InspectResult", "Ask", "Answer",
	"Decide", "Sanity", "Hallucinate", "Shake", "HuntState", "Dawn", "TitleCard",
	"ChoreDialog", "ChoreReply", "Admin", "AdminData", "QuickChat", "NextNight",
	"Shop", "PowerFlicker", "EndScreen", "Downed",
}
for _, name in ipairs(remoteNames) do
	local re = Instance.new("RemoteEvent")
	re.Name = name
	re.Parent = Remotes
end
Remotes.Parent = ReplicatedStorage

-- STATE
local State = {
	phase = "Lobby",
	night = 1,
	money = Config.StartMoney,
	rep = 0,
	queueLeft = 0,
	humansLeft = 0,
	monstersLeft = 0,
	rulesRevealed = 3,
	desksBought = 1,
	forceNext = nil,
	quotaGuests = nil,
	quotaMonsters = nil,
	warmerReadyAt = workspace:GetServerTimeNow() + Config.WarmerMinutes * 60,
	guestsPerNight = Config.Nights[1].guests,
	monstersPerNight = Config.Nights[1].monsters,
	snapshotMoney = Config.StartMoney,
	snapshotRep = 0,
	admittedMonsters = {},
	admittedHumans = {},
	activeGuests = {},
	guestsFolder = nil,
	correctCalls = 0,
	wrongCalls = 0,
	monstersCaught = 0,
	earnedTonight = 0,
	choresDone = false,
	toggles = { god = false, infiniteMoney = false, noSanityDrain = false, instantCoffee = false, freeze = false },
	huntTime = Config.HuntSeconds,
	monsterSpeed = Config.MonsterSpeed,
	log = {},
}

local function log(text)
	table.insert(State.log, os.date("%H:%M:%S") .. " " .. text)
	if #State.log > 200 then table.remove(State.log, 1) end
	print("[NSM] " .. text)
end

local Map = MapBuilder.Build({ Config = Config })
local ctx = { Config = Config, Remotes = Remotes, State = State, Map = Map, log = log }
State.ctx = ctx

local Controls = {}
ctx.Controls = Controls

VFXServer.Init(ctx)
SanityServer.Init(ctx)
HuntManager.Init(ctx)
ChoresServer.Init(ctx)
ShopServer.Init(ctx)
AdminServer.Init(ctx)
ctx.Sanity = SanityServer
ctx.VFX = VFXServer
ctx.GuestGen = GuestGen
ctx.Hunt = HuntManager
ctx.Chores = ChoresServer
ctx.Shop = ShopServer

local function stars()
	if State.rep <= 0 then return 1 end
	return math.clamp(math.ceil(State.rep / 20), 1, 5)
end

local function sendState()
	local rooms = {}
	for _, num in ipairs(Config.RoomNumbers) do
		table.insert(rooms, { num = num, state = Map.Rooms[num].state })
	end
	Remotes.StateUpdate:FireAllClients({
		money = State.money,
		rep = State.rep,
		stars = stars(),
		night = State.night,
		phase = State.phase,
		queueLeft = State.queueLeft,
		rules = State.rulesRevealed,
		ruleTexts = Config.Rules,
		desksBought = State.desksBought,
		deskPrices = Config.DeskPrices,
		coffeePrice = State.ctx.Sanity.GetCoffeePrice and State.ctx.Sanity.GetCoffeePrice() or Config.CoffeePrice,
		warmerReadyAt = State.warmerReadyAt,
		warmerMinutes = Config.WarmerMinutes,
		rooms = rooms,
		objective = Config.Objectives[State.night],
		hints = Config.Nights[State.night].hints,
	})
end
ctx.sendState = sendState
ctx.stars = stars

local function notify(player, text, kind)
	if player then
		Remotes.Notify:FireClient(player, text, kind)
	else
		Remotes.Notify:FireAllClients(text, kind)
	end
end
ctx.notify = notify

-- WALKING HELPER
local function walkTo(model, pos, timeout)
	local hum = model:FindFirstChildOfClass("Humanoid")
	local hrp = model:FindFirstChild("HumanoidRootPart")
	if not hum or not hrp then return end
	local t0 = os.clock()
	hum:MoveTo(pos)
	while os.clock() - t0 < (timeout or 20) do
		task.wait(0.2)
		if not hrp.Parent then return end
		if (hrp.Position - pos).Magnitude < 3.5 then return end
		hum:MoveTo(pos)
	end
end
ctx.walkTo = walkTo

-- DOORS
local function setDoor(num, open)
	local d = Map.Doors[num]
	if not d then return end
	d.isOpen = open
	if open then
		d.part.CFrame = d.openCF
		d.prompt.ActionText = "Close"
	else
		d.part.CFrame = d.closed
		d.prompt.ActionText = d.locked and "Locked" or "Open"
	end
end
ctx.setDoor = setDoor

local function setDoorLock(num, locked)
	local d = Map.Doors[num]
	if not d then return end
	d.locked = locked
	d.prompt.ActionText = d.isOpen and "Close" or (locked and "Locked" or "Open")
end
ctx.setDoorLock = setDoorLock

for num, d in pairs(Map.Doors) do
	d.prompt.Triggered:Connect(function(player)
		if d.breaking then return end
		if d.locked then
			notify(player, "This door is locked.", "info")
			return
		end
		setDoor(num, not d.isOpen)
		VFXServer.Play("lock", d.part, 0.6)
	end)
	d.barPrompt.Triggered:Connect(function(player)
		if State.phase ~= "Hunt" then return end
		if d.barricaded then return end
		d.barricaded = true
		d.chair.CFrame = d.closed * CFrame.new(0, 0, 1.6) * CFrame.Angles(0, math.rad(90), 0) * CFrame.new(0, 0.4, 0)
		d.chair.Anchored = true
		notify(player, "Door barricaded. The monster will take longer to break in.", "good")
	end)
end

Map.SecurityPrompt.Triggered:Connect(function()
	Map.SecurityDoorOpen = not Map.SecurityDoorOpen
	Map.SecurityDoor.CanCollide = not Map.SecurityDoorOpen
	Map.SecurityDoor.Transparency = Map.SecurityDoorOpen and 0.7 or 0
	VFXServer.Play("lock", Map.SecurityDoor, 0.6)
end)

-- DESKS
local function setDeskBought(slot, bought)
	local desk = Map.Desks[slot]
	if not desk then return end
	desk.bought = bought
	for _, d in ipairs(desk.furniture:GetDescendants()) do
		if d:IsA("BasePart") then
			d.Transparency = bought and 0 or 1
			if d:IsA("Seat") then d.CanCollide = bought end
		end
		if d:IsA("ProximityPrompt") then d.Enabled = bought end
	end
	desk.seat.CanCollide = bought
end
ctx.setDeskBought = setDeskBought

local playerDesks = {}
local function deskOccupant(slot)
	for _, pl in ipairs(Players:GetPlayers()) do
		if playerDesks[pl] == slot then return pl end
	end
	return nil
end
ctx.deskOccupant = deskOccupant

for slot, desk in pairs(Map.Desks) do
	desk.prompt.Triggered:Connect(function(player)
		local char = player.Character
		local hum = char and char:FindFirstChildOfClass("Humanoid")
		if hum then
			desk.seat:Sit(hum)
		end
	end)
	desk.seat:GetPropertyChangedSignal("Occupant"):Connect(function()
		local occ = desk.seat.Occupant
		if occ then
			local pl = Players:GetPlayerFromCharacter(occ.Parent)
			if pl then
				playerDesks[pl] = slot
				notify(pl, "You are serving Desk " .. slot .. ". Wait for a guest.", "info")
			end
		else
			for pl, s in pairs(playerDesks) do
				if s == slot then playerDesks[pl] = nil end
			end
		end
	end)
end

-- GUEST SPAWNING
local function pickFreeDesk()
	local order = { 1, 2, 3 }
	for _, slot in ipairs(order) do
		local desk = Map.Desks[slot]
		if desk and desk.bought then
			local busy = false
			for _, g in pairs(State.activeGuests) do
				if g.desk == slot then busy = true end
			end
			if not busy then return slot end
		end
	end
	return nil
end

local function firstFreeRoom()
	for _, num in ipairs(Config.RoomNumbers) do
		if Map.Rooms[num].state == "clean" and not Map.Rooms[num].occupant then
			return num
		end
	end
	return nil
end
ctx.firstFreeRoom = firstFreeRoom

local function anyCleanRooms()
	for _, num in ipairs(Config.RoomNumbers) do
		if Map.Rooms[num].state == "clean" and not Map.Rooms[num].occupant then return true end
	end
	return false
end
ctx.anyCleanRooms = anyCleanRooms

local function startKnocking(num)
	local d = Map.Doors[num]
	if not d or d.knock then return end
	local s = Instance.new("Sound")
	s.SoundId = "rbxasset://sounds/snap.mp3"
	s.Volume = 1.4
	s.Pitch = 0.55
	s.Parent = d.part
	d.knock = task.spawn(function()
		while d.part.Parent and Map.Rooms[num].state == "monsterRoom" do
			s:Play()
			task.wait(1.6)
		end
	end)
end

local function stopKnocking(num)
	local d = Map.Doors[num]
	if d and d.knock then
		task.cancel(d.knock)
		d.knock = nil
		local s = d.part:FindFirstChildOfClass("Sound")
		if s then s:Destroy() end
	end
end

local function guestLeave(guest, destination)
	State.activeGuests[guest.id] = nil
	Remotes.GuestUpdate:FireAllClients({ desk = guest.desk, id = guest.id, present = false })
	task.spawn(function()
		if guest.model.Parent then
			if destination.Z > 0 then
				walkTo(guest.model, Vector3.new(0, 3.5, 8), 20)
			else
				walkTo(guest.model, Vector3.new(0, 3.5, -18), 20)
			end
			walkTo(guest.model, destination, 25)
			if guest.model.Parent then guest.model:Destroy() end
		end
	end)
end
ctx.guestLeave = guestLeave

local function spawnGuest()
	local slot = pickFreeDesk()
	if not slot then return false end
	local nightCfg = Config.Nights[State.night]
	local isMonster
	if State.forceNext == "human" or State.forceNext == "monster" then
		isMonster = State.forceNext == "monster"
		State.forceNext = nil
	elseif State.monstersLeft > 0 and (State.humansLeft <= 0 or math.random() < State.monstersLeft / (State.monstersLeft + State.humansLeft)) then
		isMonster = true
	else
		isMonster = false
	end

	local tells = {}
	local cameraApp = "normal"
	if isMonster then
		State.monstersLeft = State.monstersLeft - 1
		local visible = {}
		for _, t in ipairs(Config.Tells) do
			if t.cat ~= "Camera" then table.insert(visible, t.id) end
		end
		local cameraOnly = nightCfg.cameraOnly and math.random() < 0.3
		if cameraOnly then
			cameraApp = "absent"
			tells = { "NoCamera" }
		else
			local count = math.random(2, 4)
			local chosen = {}
			local cats = {}
			local pool = {}
			for _, id in ipairs(visible) do table.insert(pool, id) end
			if math.random() < 0.25 then table.insert(pool, "DistortedCam") cameraApp = "distorted" end
			local guard = 0
			while #chosen < count and guard < 60 do
				guard = guard + 1
				local id = pool[math.random(#pool)]
				local already = false
				for _, c in ipairs(chosen) do if c == id then already = true end end
				if not already then
					local cat
					for _, t in ipairs(Config.Tells) do if t.id == id then cat = t.cat end end
					local catCount = 0
					for _, c in ipairs(cats) do if c == cat then catCount = catCount + 1 end end
					if catCount == 0 or #chosen >= 2 then
						table.insert(chosen, id)
						if catCount == 0 then table.insert(cats, cat) end
					end
				end
			end
			-- ensure at least 2 categories
			if #cats < 2 then
				for _, t in ipairs(Config.Tells) do
					local found = false
					for _, c in ipairs(cats) do if c == t.cat then found = true end end
					if not found and t.cat ~= "Camera" then
						table.insert(chosen, t.id)
						table.insert(cats, t.cat)
						break
					end
				end
			end
			tells = chosen
		end
	else
		State.humansLeft = State.humansLeft - 1
	end

	local idFrom = Config.Cities[math.random(#Config.Cities)]
	local guest = GuestGen.Create(ctx, {
		isMonster = isMonster,
		tells = tells,
		cameraApp = cameraApp,
		walkSpeed = 16,
		desk = slot,
		spawnPos = Vector3.new(math.random(-6, 6), 3.5, 56),
		idFrom = idFrom,
	})
	guest.model.Parent = map
	State.activeGuests[guest.id] = guest

	local bell = Map.Desks[slot].bell
	bell.Pitch = guest.angry and 1.6 or 1
	bell:Play()
	notify(nil, (guest.angry and "AN ANGRY GUEST" or "GUEST ARRIVED") .. " at Desk " .. slot, "guest")
	Remotes.GuestUpdate:FireAllClients({
		desk = slot, id = guest.id, present = true,
		name = guest.spokenName, angry = guest.angry,
		cameraApp = guest.cameraApp,
		extraQ = Config.ExtraQuestions[math.random(#Config.ExtraQuestions)].id,
	})

	task.spawn(function()
		walkTo(guest.model, Vector3.new(0, 3.5, 8), 20)
		walkTo(guest.model, Map.Desks[slot].pos, 20)
		GuestGen.Say(guest, "Evening. Name's " .. guest.spokenName .. ". I need a room.")
	end)
	return true
end
ctx.spawnGuest = spawnGuest

-- INSPECTION / QUESTIONS / DECISIONS
local function getGuest(guestId)
	return State.activeGuests[guestId]
end

local function visibleTellsIn(guest, cat)
	local labels = {}
	for _, id in ipairs(guest.tells) do
		for _, t in ipairs(Config.Tells) do
			if t.id == id and t.cat == cat then table.insert(labels, t.label) end
		end
	end
	return labels
end
ctx.visibleTellsIn = visibleTellsIn

Remotes.Inspect.OnServerEvent:Connect(function(player, guestId, category)
	local guest = getGuest(guestId)
	if not guest then return end
	if State.phase ~= "Night" then return end
	if playerDesks[player] ~= guest.desk then return end
	if category == "open" then
		Remotes.InspectResult:FireClient(player, guest.id, "open", {}, (guest.model:FindFirstChild("Head") or guest.model.PrimaryPart).CFrame)
	else
		local labels = visibleTellsIn(guest, category)
		Remotes.InspectResult:FireClient(player, guest.id, category, labels, nil)
	end
end)

Remotes.Ask.OnServerEvent:Connect(function(player, guestId, qid)
	local guest = getGuest(guestId)
	if not guest then return end
	if State.phase ~= "Night" then return end
	if playerDesks[player] ~= guest.desk then return end
	local text
	if qid == "from" then
		text = guest.answers.from
	elseif qid == "id" then
		text = "Sure. Here it is."
	elseif qid == "year" then
		text = guest.answers.year
	elseif qid == "job" then
		text = guest.answers.job
	elseif qid == "stay" then
		text = guest.answers.stay
	else
		return
	end
	GuestGen.Say(guest, text)
	Remotes.Answer:FireClient(player, guest.id, qid, text, guest.idCard)
end)

local function applyMoney(amount)
	if State.toggles.infiniteMoney then return end
	State.money = State.money + amount
	if amount > 0 then State.earnedTonight = State.earnedTonight + amount end
end
ctx.applyMoney = applyMoney

local function applyRep(amount)
	State.rep = State.rep + amount
end
ctx.applyRep = applyRep

Remotes.Decide.OnServerEvent:Connect(function(player, guestId, admit)
	local guest = getGuest(guestId)
	if not guest then return end
	if State.phase ~= "Night" then return end
	if playerDesks[player] ~= guest.desk then return end

	if admit then
		if not anyCleanRooms() then
			notify(player, "No clean rooms! Clean rooms in the morning first.", "bad")
			return
		end
		local num = firstFreeRoom()
		if not num then
			notify(player, "No clean rooms!", "bad")
			return
		end
		if guest.isMonster then
			Map.Rooms[num].state = "monsterRoom"
			Map.Rooms[num].occupant = guest
			guest.roomNumber = num
			table.insert(State.admittedMonsters, guest)
			startKnocking(num)
			task.spawn(function()
				task.wait(0.4)
				for i = 1, 6 do
					Map.RoomLights[num].Transparency = 1
					local pl = Map.RoomLights[num]:FindFirstChildOfClass("PointLight")
					if pl then pl.Enabled = not pl.Enabled end
					task.wait(0.15)
				end
				Map.RoomLights[num].Transparency = 0
			end)
			VFXServer.Shake(1.2)
			VFXServer.Play("rumble", workspace, 0.8, 0.5)
			notify(nil, "Something feels wrong about Room " .. num .. "...", "bad")
			SanityServer.Drain(player, 15, "admitted a monster")
			log("Desk " .. guest.desk .. ": ADMITTED A MONSTER -> Room " .. num)
		else
			Map.Rooms[num].state = "occupied"
			Map.Rooms[num].occupant = guest
			guest.roomNumber = num
			table.insert(State.admittedHumans, guest)
			applyMoney(Config.AdmitHumanMoney)
			applyRep(Config.AdmitHumanRep)
			State.correctCalls = State.correctCalls + 1
			VFXServer.Play("bell", workspace, 0.9, 1.4)
			notify(nil, "Correct call! +$" .. Config.AdmitHumanMoney, "good")
			log("Desk " .. guest.desk .. ": admitted human " .. guest.spokenName .. " -> Room " .. num)
		end
		local num2 = num
		guestLeave(guest, Vector3.new(0, 3.5, -26))
		task.spawn(function()
			task.wait(2)
			walkTo(guest.model, Vector3.new(num2 and ((num2 - 101) * 10 - 25) or 0, 3.5, -38), 25)
			if guest.model.Parent then
				local hum = guest.model:FindFirstChildOfClass("Humanoid")
				if hum then hum.WalkSpeed = 0 end
			end
		end)
	else
		if guest.isMonster then
			applyMoney(Config.DenyMonsterMoney)
			applyRep(Config.DenyMonsterRep)
			State.correctCalls = State.correctCalls + 1
			State.monstersCaught = State.monstersCaught + 1
			VFXServer.Play("bell", workspace, 0.9, 1.4)
			notify(nil, "Correct call! Monster turned away. +$" .. Config.DenyMonsterMoney, "good")
			log("Desk " .. guest.desk .. ": turned away a MONSTER")
		else
			applyMoney(Config.DenyHumanMoney)
			applyRep(Config.DenyHumanRep)
			State.wrongCalls = State.wrongCalls + 1
			notify(nil, "You turned away a real human. -$10", "bad")
			SanityServer.Drain(player, 5, "turned away a human")
			log("Desk " .. guest.desk .. ": turned away human " .. guest.spokenName)
			if math.random() < Config.AngryReturnChance and not guest.angry then
				task.spawn(function()
					task.wait(math.random(20, 45))
					if State.phase ~= "Night" then return end
					local slot2 = pickFreeDesk()
					if not slot2 then return end
					local angry = GuestGen.Create(ctx, {
						isMonster = false, tells = {}, cameraApp = "normal",
						walkSpeed = 20, desk = slot2, angry = true,
						spawnPos = Vector3.new(math.random(-6, 6), 3.5, 56),
						idFrom = guest.idCard.from,
					})
					angry.model.Parent = map
					State.activeGuests[angry.id] = angry
					Map.Desks[slot2].bell.Pitch = 1.6
					Map.Desks[slot2].bell:Play()
					notify(nil, "The guest you turned away is BACK, and he is angry.", "bad")
					Remotes.GuestUpdate:FireAllClients({ desk = slot2, id = angry.id, present = true, name = angry.spokenName .. " (angry)", cameraApp = "normal", extraQ = Config.ExtraQuestions[math.random(#Config.ExtraQuestions)].id })
					task.spawn(function()
						walkTo(angry.model, Vector3.new(0, 3.5, 8), 15)
						walkTo(angry.model, Map.Desks[slot2].pos, 15)
						GuestGen.Say(angry, "You turned ME away?! I demand a room. NOW.")
					end)
				end)
			end
		end
		guestLeave(guest, Vector3.new(math.random(-8, 8), 3.5, 58))
	end
	sendState()
end)

-- NIGHT FLOW
local function resetRooms()
	for _, num in ipairs(Config.RoomNumbers) do
		local r = Map.Rooms[num]
		if r.state ~= "messy" and r.state ~= "overstayer" then
			-- unfinished morning chores (messy/overstayer) stay blocked into the next night
			if r.occupant and r.occupant.model then r.occupant.model:Destroy() end
			r.occupant = nil
			r.state = "clean"
			stopKnocking(num)
			setDoor(num, true)
			setDoorLock(num, false)
			local d = Map.Doors[num]
			d.barricaded = false
			d.breaking = false
			d.part.CanCollide = true
			d.part.Transparency = 0
			d.chair.Anchored = true
			d.chair.CFrame = CFrame.new((num - 101) * 10 - 25 + 2, 0.9, -38)
			d.chair.Transparency = 0
		end
	end
end
ctx.resetRooms = resetRooms

local function servingDone()
	if State.queueLeft > 0 then return false end
	for _ in pairs(State.activeGuests) do
		return false
	end
	return true
end

local function startNight(n)
	State.night = n
	State.phase = "Night"
	State.correctCalls = 0
	State.wrongCalls = 0
	State.monstersCaught = 0
	State.earnedTonight = 0
	State.admittedMonsters = {}
	State.admittedHumans = {}
	State.snapshotMoney = State.money
	State.snapshotRep = State.rep
	State.choresDone = false
	local cfg = Config.Nights[n]
	State.guestsPerNight = State.quotaGuests or cfg.guests
	State.monstersPerNight = State.quotaMonsters or cfg.monsters
	State.queueLeft = State.guestsPerNight
	State.humansLeft = State.guestsPerNight - State.monstersPerNight
	State.monstersLeft = State.monstersPerNight
	State.rulesRevealed = 3
	for i = 2, n do
		State.rulesRevealed = State.rulesRevealed + (Config.Nights[i].newRules or 0)
	end
	State.rulesRevealed = math.min(State.rulesRevealed, #Config.Rules)
	resetRooms()
	VFXServer.NightLight()
	VFXServer.SetRain(true, 1)
	VFXServer.SetFog(true)
	local bonus = State.rep
	if bonus ~= 0 then
		applyMoney(bonus)
		log("Night " .. n .. " starting bonus from reputation: $" .. bonus)
	end
	local newRules = {}
	for i = State.rulesRevealed - (cfg.newRules or 0) + 1, State.rulesRevealed do
		if i >= 1 then table.insert(newRules, Config.Rules[i]) end
	end
	Remotes.TitleCard:FireAllClients(n, Config.Objectives[n], newRules, cfg.hints)
	sendState()
	log("Night " .. n .. " started: " .. State.guestsPerNight .. " guests, " .. State.monstersPerNight .. " monsters")

	task.spawn(function()
		task.wait(6)
		while State.phase == "Night" and State.queueLeft > 0 do
			if not State.toggles.freeze and not State.toggles.paused then
				spawnGuest()
			end
			task.wait(Config.NextGuestDelay)
		end
		while State.phase == "Night" and not servingDone() do
			task.wait(1)
		end
		if State.phase ~= "Night" then return end
		if #State.admittedMonsters > 0 then
			local survived = HuntManager.Run(ctx, State.admittedMonsters)
			if not survived then return end
		else
			notify(nil, "No monsters got in tonight. Quiet night...", "good")
		end
		VFXServer.DawnLight()
		ChoresServer.Process(ctx, State.admittedMonsters, State.admittedHumans)
		State.phase = "Dawn"
		sendState()
		Remotes.Dawn:FireAllClients({
			night = State.night,
			earned = State.earnedTonight,
			correct = State.correctCalls,
			wrong = State.wrongCalls,
			caught = State.monstersCaught,
			chores = ChoresServer.GetChoreList(),
			isFinalNight = State.night >= 5,
		})
		log("Dawn after night " .. State.night)
	end)
end
ctx.startNight = startNight

Remotes.NextNight.OnServerEvent:Connect(function(player)
	if State.phase == "GameOver" then
		State.money = State.snapshotMoney
		State.rep = State.snapshotRep
		for _, pl in ipairs(Players:GetPlayers()) do
			local char = pl.Character
			local hrp = char and char:FindFirstChild("HumanoidRootPart")
			if hrp then
				hrp.Anchored = false
				hrp.CFrame = CFrame.new(0, 4, 50)
			end
			local hum = char and char:FindFirstChildOfClass("Humanoid")
			if hum then hum.WalkSpeed = 16 end
			Remotes.Downed:FireClient(pl, false)
		end
		startNight(State.night)
		return
	end
	if State.phase == "Win" then
		State.phase = "Lobby"
		State.night = 1
		State.money = Config.StartMoney
		State.rep = 0
		State.desksBought = 1
		setDeskBought(2, false)
		setDeskBought(3, false)
		State.rulesRevealed = 3
		startNight(1)
		return
	end
	if State.phase ~= "Dawn" and State.phase ~= "Shop" then return end
	if State.night >= 5 then
		State.phase = "Win"
		sendState()
		Remotes.EndScreen:FireAllClients(true, { money = State.money, stars = stars() })
		log("WIN: survived all 5 nights")
		return
	end
	State.phase = "Shop"
	sendState()
	startNight(State.night + 1)
end)

Remotes.Shop.OnServerEvent:Connect(function(player, action, data)
	ShopServer.Handle(player, action, data)
end)

Remotes.ChoreReply.OnServerEvent:Connect(function(player, room, choice)
	ChoresServer.HandleReply(player, room, choice)
end)

Remotes.QuickChat.OnServerEvent:Connect(function(player, text)
	if type(text) ~= "string" or #text > 60 then return end
	local char = player.Character
	local head = char and char:FindFirstChild("Head")
	if head then
		local bb = Instance.new("BillboardGui")
		bb.Size = UDim2.new(0, 220, 0, 50)
		bb.StudsOffset = Vector3.new(0, 2.2, 0)
		bb.AlwaysOnTop = true
		bb.MaxDistance = 50
		bb.Parent = head
		local tl = Instance.new("TextLabel")
		tl.Size = UDim2.new(1, 0, 1, 0)
		tl.BackgroundColor3 = Color3.fromRGB(30, 30, 40)
		tl.BackgroundTransparency = 0.3
		tl.TextColor3 = Color3.fromRGB(255, 240, 160)
		tl.TextScaled = true
		tl.Font = Enum.Font.GothamBold
		tl.Text = text
		tl.Parent = bb
		Debris:AddItem(bb, 4)
	end
end)

Players.PlayerAdded:Connect(function(player)
	SanityServer.AddPlayer(player)
	sendState()
	if #Players:GetPlayers() == 1 and State.phase == "Lobby" then
		task.delay(5, function()
			if State.phase == "Lobby" then startNight(1) end
		end)
	end
end)

Players.PlayerRemoving:Connect(function(player)
	SanityServer.RemovePlayer(player)
	playerDesks[player] = nil
end)

-- CONTROLS (used by the admin panel)
Controls.sendState = sendState
Controls.log = log
Controls.notify = notify
Controls.setDoor = setDoor
Controls.setDoorLock = setDoorLock
Controls.setDeskBought = setDeskBought
Controls.setKnocking = startKnocking
Controls.stopKnocking = stopKnocking
Controls.pickFreeDesk = pickFreeDesk
Controls.getGuest = getGuest
Controls.walkTo = walkTo
Controls.applyMoney = applyMoney
Controls.applyRep = applyRep
Controls.spawnGuest = spawnGuest
Controls.startNight = startNight
Controls.resetRooms = resetRooms
Controls.stars = stars
Controls.playerDesks = playerDesks

log("Night Shift Motel server loaded. Waiting for players...")
