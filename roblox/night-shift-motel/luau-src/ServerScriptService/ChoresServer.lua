-- ChoresServer: morning chores — messy rooms (eaten guests) and overstayers.
local ChoresServer = {}
local ctx, Config, Remotes, State, Map
local chores = {}

local ARGUMENTS = {
	"I paid for another night!",
	"Just five more minutes...",
	"Do you know who I am?",
}
local WRONG_REPLIES = {
	"Okay... sleep in, I guess.",
	"Take your time, sir.",
	"Fine, whatever you want.",
}
local GIVE_UP = {
	"Ugh. FINE. I am going.",
	"Unbelievable service here...",
	"You have not heard the end of this.",
}

function ChoresServer.Init(c)
	ctx = c
	Config = c.Config
	Remotes = c.Remotes
	State = c.State
	Map = c.Map
end

local function buildMess(num)
	local x = (num - 101) * 10 - 25
	local folder = Instance.new("Folder")
	folder.Name = "Mess" .. num
	folder.Parent = Map
	local function mp(pos, size, color, rot)
		local p = Instance.new("Part")
		p.Anchored = true
		p.Size = size
		p.CFrame = CFrame.new(pos) * CFrame.Angles(0, rot or 0, 0)
		p.Color = color
		p.Material = Enum.Material.SmoothPlastic
		p.Parent = folder
		return p
	end
	mp(Vector3.new(x - 3, 0.6, -42), Vector3.new(1.6, 1.2, 1.2), Color3.fromRGB(120, 95, 60), 0.5)
	mp(Vector3.new(x - 1.5, 0.4, -44), Vector3.new(1.2, 0.8, 1), Color3.fromRGB(100, 80, 55), 1.2)
	mp(Vector3.new(x + 2.5, 0.35, -43.5), Vector3.new(1.4, 0.7, 1.4), Color3.fromRGB(110, 75, 50), 2)
	mp(Vector3.new(x + 1, 0.5, -45.5), Vector3.new(1.6, 1, 1.2), Color3.fromRGB(120, 40, 40), 0.9)
	mp(Vector3.new(x, 0.12, -41), Vector3.new(5, 0.05, 5), Color3.fromRGB(35, 20, 20))
	local stain = mp(Vector3.new(x - 2.5, 0.13, -43.5), Vector3.new(3.4, 0.06, 3.4), Color3.fromRGB(30, 15, 15))
	stain.Shape = Enum.PartType.Cylinder
	stain.Size = Vector3.new(0.06, 3.4, 3.4)
	stain.CFrame = CFrame.new(x - 2.5, 0.13, -43.5) * CFrame.Angles(0, 0, math.rad(90))
	local bed = Map:FindFirstChild("Bed" .. num, true)
	if bed then bed.CFrame = bed.CFrame * CFrame.Angles(0, 0, math.rad(8)) end
	local promptHolder = mp(Vector3.new(x, 2, -41), Vector3.new(0.4, 0.4, 0.4), Color3.fromRGB(255, 220, 120))
	promptHolder.Transparency = 1
	local prompt = Instance.new("ProximityPrompt")
	prompt.ActionText = "Clean the room"
	prompt.ObjectText = "Room " .. num
	prompt.HoldDuration = 5
	prompt.MaxActivationDistance = 12
	prompt.RequiresLineOfSight = false
	prompt.Parent = promptHolder
	prompt.Triggered:Connect(function(player)
		folder:Destroy()
		Map.Rooms[num].state = "clean"
		for _, ch in ipairs(chores) do
			if ch.room == num and ch.kind == "messy" then ch.done = true end
		end
		ctx.notify(nil, "Room " .. num .. " cleaned.", "good")
		ctx.VFX.Play("water", workspace, 0.6)
		ChoresServer.CheckAllDone()
		ctx.sendState()
	end)
	return folder
end

local function buildOverstayer(guest, num)
	local model = guest.model
	if not model or not model.Parent then return end
	local head = model:FindFirstChild("Head")
	if not head then return end
	local prompt = Instance.new("ProximityPrompt")
	prompt.ActionText = "Tell them to leave"
	prompt.ObjectText = "Room " .. num
	prompt.MaxActivationDistance = 12
	prompt.RequiresLineOfSight = false
	prompt.Parent = head
	prompt.Triggered:Connect(function(player)
		Remotes.ChoreDialog:FireClient(player, num, ARGUMENTS[math.random(#ARGUMENTS)])
	end)
	guest.overstayPrompt = prompt
end

function ChoresServer.HandleReply(player, num, choice)
	local r = Map.Rooms[num]
	if not r or r.state ~= "overstayer" or not r.occupant then return end
	if choice == 2 then
		local guest = r.occupant
		ctx.GuestGen.Say(guest, GIVE_UP[math.random(#GIVE_UP)])
		r.state = "cleaning"
		if guest.overstayPrompt then guest.overstayPrompt:Destroy() end
		task.spawn(function()
			task.wait(1.5)
			ctx.walkTo(guest.model, Vector3.new((num - 101) * 10 - 25, 3.5, -30), 15)
			ctx.walkTo(guest.model, Vector3.new(0, 3.5, -26), 20)
			ctx.walkTo(guest.model, Vector3.new(math.random(-8, 8), 3.5, 58), 25)
			if guest.model.Parent then guest.model:Destroy() end
			r.state = "clean"
			r.occupant = nil
			for _, ch in ipairs(chores) do
				if ch.room == num and ch.kind == "overstayer" then ch.done = true end
			end
			ctx.notify(nil, "Room " .. num .. " is free again.", "good")
			ChoresServer.CheckAllDone()
			ctx.sendState()
		end)
	else
		if r.occupant then
			ctx.GuestGen.Say(r.occupant, WRONG_REPLIES[math.random(#WRONG_REPLIES)] .. " (" .. ARGUMENTS[math.random(#ARGUMENTS)] .. ")")
		end
	end
end

function ChoresServer.CheckAllDone()
	for _, ch in ipairs(chores) do
		if not ch.done then return end
	end
	if #chores > 0 and not State.choresDone then
		State.choresDone = true
		ctx.Controls.applyMoney(Config.CleanBonusMoney)
		ctx.Controls.applyRep(Config.CleanBonusRep)
		ctx.notify(nil, "ALL CHORES DONE! Clean motel bonus: +$" .. Config.CleanBonusMoney .. " and +" .. Config.CleanBonusRep .. " reputation.", "good")
		ctx.Controls.log("All morning chores completed")
		ctx.sendState()
	end
end

function ChoresServer.Process(c, monsters, humans)
	chores = {}
	State.choresDone = false
	local eaten = {}
	for _, monster in ipairs(monsters) do
		local candidates = {}
		for _, h in ipairs(humans) do
			if not eaten[h] and h.model and h.model.Parent and h.roomNumber then
				table.insert(candidates, h)
			end
		end
		if #candidates > 0 then
			local victim = candidates[math.random(#candidates)]
			eaten[victim] = true
			local num = victim.roomNumber
			if victim.model.Parent then victim.model:Destroy() end
			Map.Rooms[num].state = "messy"
			Map.Rooms[num].occupant = nil
			buildMess(num)
			table.insert(chores, { room = num, kind = "messy", done = false })
			ctx.Controls.log("Monster from Room " .. tostring(monster.roomNumber) .. " ate the guest in Room " .. num)
		end
	end
	for _, h in ipairs(humans) do
		if not eaten[h] and h.model and h.model.Parent and h.roomNumber and Map.Rooms[h.roomNumber].state == "occupied" then
			if math.random() < Config.OverstayChance then
				Map.Rooms[h.roomNumber].state = "overstayer"
				buildOverstayer(h, h.roomNumber)
				table.insert(chores, { room = h.roomNumber, kind = "overstayer", done = false })
				ctx.Controls.log("Guest in Room " .. h.roomNumber .. " refuses to check out")
			else
				local num = h.roomNumber
				Map.Rooms[num].state = "cleaning"
				local g = h
				task.spawn(function()
					ctx.walkTo(g.model, Vector3.new((num - 101) * 10 - 25, 3.5, -30), 15)
					ctx.walkTo(g.model, Vector3.new(0, 3.5, -26), 20)
					ctx.walkTo(g.model, Vector3.new(math.random(-8, 8), 3.5, 58), 25)
					if g.model.Parent then g.model:Destroy() end
					if Map.Rooms[num].state == "cleaning" then Map.Rooms[num].state = "clean" end
					Map.Rooms[num].occupant = nil
					ctx.sendState()
				end)
			end
		end
	end
	return chores
end

function ChoresServer.GetChoreList()
	local list = {}
	for _, ch in ipairs(chores) do
		table.insert(list, { room = ch.room, kind = ch.kind, done = ch.done })
	end
	return list
end

return ChoresServer
