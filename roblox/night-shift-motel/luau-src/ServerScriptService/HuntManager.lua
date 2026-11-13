-- HuntManager: lockdown phase. Monsters chase, doors get broken, 60 seconds to dawn.
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")
local Debris = game:GetService("Debris")

local HuntManager = {}
local ctx, Config, Remotes, State, Map
local running = false
local stopRequested = false
local downed = {}

local function isDowned(player)
	return downed[player] == true
end

function HuntManager.Init(c)
	ctx = c
	Config = c.Config
	Remotes = c.Remotes
	State = c.State
	Map = c.Map
end

function HuntManager.lose()
	if not running then return end
	running = false
	State.phase = "GameOver"
	ctx.VFX.Lockdown(false)
	Remotes.HuntState:FireAllClients(false, 0)
	Remotes.EndScreen:FireAllClients(false, { night = State.night })
	ctx.Controls.log("LOSE: all players caught on night " .. State.night)
end

local function downPlayer(player)
	if downed[player] then return end
	if State.toggles.god and player.UserId == Config.AdminUserId then return end
	downed[player] = true
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	local hrp = char and char:FindFirstChild("HumanoidRootPart")
	if hrp then hrp.Anchored = true end
	if hum then hum.WalkSpeed = 0 end
	Remotes.Downed:FireClient(player, true)
	ctx.VFX.Play("caught", workspace, 1)
	ctx.notify(nil, player.Name .. " was caught!", "bad")
	local alive = 0
	for _, pl in ipairs(Players:GetPlayers()) do
		if not downed[pl] then alive = alive + 1 end
	end
	if alive == 0 then
		HuntManager.lose()
	end
end

function HuntManager.Stop()
	if running then
		stopRequested = true
	end
end

local function dissolve(model)
	for _, p in ipairs(model:GetDescendants()) do
		if p:IsA("BasePart") then
			TweenService:Create(p, TweenInfo.new(1.5), { Transparency = 1 }):Play()
		end
	end
	Debris:AddItem(model, 2)
end

function HuntManager.Run(c, monsters)
	ctx = c
	running = true
	stopRequested = false
	downed = {}
	State.phase = "Hunt"
	ctx.sendState()

	ctx.VFX.Lockdown(true)
	ctx.VFX.Play("rumble", workspace, 1, 0.35, false)
	ctx.notify(nil, "LOCKDOWN — SOMETHING IS IN THE ROOMS", "bad")
	Remotes.HuntState:FireAllClients(true, State.huntTime)
	ctx.Controls.log("Hunt started: " .. #monsters .. " monster(s) loose")

	local hunters = {}
	for _, guest in ipairs(monsters) do
		local model = guest.model
		if model and model.Parent then
			local hum = model:FindFirstChildOfClass("Humanoid")
			local hrp = model:FindFirstChild("HumanoidRootPart")
			if hum and hrp then
				hum.WalkSpeed = State.monsterSpeed
				for _, p in ipairs(model:GetDescendants()) do
					if p:IsA("BasePart") and p.Name ~= "HumanoidRootPart" then
						if p.Name == "Eye" then
							p.Color = Color3.fromRGB(255, 30, 30)
						else
							p.Color = Color3.fromRGB(25, 22, 26)
						end
					end
				end
				local cd = model:FindFirstChildWhichIsA("ClickDetector", true)
				if cd then cd:Destroy() end
				hrp.CFrame = CFrame.new(guest.roomNumber and (guest.roomNumber - 101) * 10 - 25 or 0, 3.5, -30)
				hunters[model] = { hum = hum, hrp = hrp, lastPath = 0 }
				hrp.Touched:Connect(function(hit)
					local pl = Players:GetPlayerFromCharacter(hit.Parent)
					if pl and not isDowned(pl) then
						if State.toggles.god and pl.UserId == Config.AdminUserId then return end
						downPlayer(pl)
					end
				end)
			end
		end
	end

	local endTime = os.clock() + State.huntTime
	local lastTick = os.clock()

	while running and os.clock() < endTime do
		task.wait(0.35)
		if stopRequested then break end
		if os.clock() - lastTick >= 1 then
			lastTick = os.clock()
			Remotes.HuntState:FireAllClients(true, math.max(0, math.ceil(endTime - os.clock())))
			for _, pl in ipairs(Players:GetPlayers()) do
				ctx.Sanity.Drain(pl, 1, "hunt")
			end
		end
		for model, h in pairs(hunters) do
			if model.Parent then
				local target, bestDist = nil, math.huge
				for _, pl in ipairs(Players:GetPlayers()) do
					local char = pl.Character
					local hrp = char and char:FindFirstChild("HumanoidRootPart")
					if hrp and not isDowned(pl) then
						local dist = (hrp.Position - h.hrp.Position).Magnitude
						if dist < bestDist then bestDist = dist target = hrp end
					end
				end
				if target then
					local pos = target.Position
					if pos.Z < -34 then
						local roomNum = 100 + math.clamp(math.floor((pos.X + 30) / 10) + 1, 1, 6)
						local d = Map.Doors[roomNum]
						if d and not d.isOpen then
							local doorPos = d.closed.Position
							if (h.hrp.Position - doorPos).Magnitude > 5 then
								h.hum:MoveTo(doorPos)
							elseif not d.breaking then
								d.breaking = true
								local breakTime = Config.DoorBreakSeconds + (d.barricaded and Config.BarricadeBonus or 0)
								ctx.notify(nil, "Something is breaking down the door of Room " .. roomNum .. "!", "bad")
								ctx.VFX.Play("rumble", d.part, 1, 0.5)
								task.spawn(function()
									task.wait(breakTime)
									if d.part.Parent then
										d.isOpen = true
										d.part.CanCollide = false
										d.part.Transparency = 0.8
										if d.barricaded and d.chair then
											d.chair.Transparency = 1
										end
										ctx.VFX.Play("breakDoor", d.part, 1)
										ctx.VFX.Shake(1)
									end
								end)
							end
						else
							if os.clock() - h.lastPath > 1 then
								h.lastPath = os.clock()
								ctx.walkPathAsync(model, pos)
							end
						end
					elseif os.clock() - h.lastPath > 1 then
						h.lastPath = os.clock()
						ctx.walkPathAsync(model, pos)
					end
				end
			end
		end
	end

	running = false
	if stopRequested then
		ctx.VFX.Lockdown(false)
		Remotes.HuntState:FireAllClients(false, 0)
		for model in pairs(hunters) do
			if model.Parent then model:Destroy() end
		end
		ctx.Controls.log("Hunt stopped by admin")
		return true
	end

	if State.phase == "GameOver" then return false end

	for model in pairs(hunters) do
		if model.Parent then dissolve(model) end
	end
	ctx.VFX.Lockdown(false)
	Remotes.HuntState:FireAllClients(false, 0)
	ctx.notify(nil, "DAWN — YOU SURVIVED THE NIGHT", "good")
	ctx.Controls.log("Hunt survived on night " .. State.night)
	return true
end

return HuntManager
