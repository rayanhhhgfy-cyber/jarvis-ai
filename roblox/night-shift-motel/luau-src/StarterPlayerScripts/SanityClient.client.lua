-- SanityClient: hallucinations at 0 sanity. Visual and audio ONLY —
-- they never change real guest data.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local Lighting = game:GetService("Lighting")

local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local hallucinating = false
_G.NSM_Hallucinating = false

local cc = Instance.new("ColorCorrectionEffect")
cc.Name = "NSM_HallucinationCC"
cc.Parent = Lighting

local whisper = Instance.new("Sound")
whisper.SoundId = "rbxasset://sounds/swoosh.wav"
whisper.Looped = true
whisper.Volume = 0
whisper.Pitch = 0.4
whisper.Parent = workspace

local heartbeat = Instance.new("Sound")
heartbeat.SoundId = "rbxasset://sounds/bass.wav"
heartbeat.Looped = true
heartbeat.Volume = 0
heartbeat.Pitch = 1.6
heartbeat.Parent = workspace

remotes.Hallucinate.OnClientEvent:Connect(function(on)
	hallucinating = on
	_G.NSM_Hallucinating = on
	if not on then
		cc.TintColor = Color3.new(1, 1, 1)
		cc.Saturation = 0
		whisper.Volume = 0
	end
end)

remotes.Sanity.OnClientEvent:Connect(function(v)
	heartbeat.Volume = (v < 25 or _G.NSM_Hunting) and 0.35 or 0
end)
remotes.HuntState.OnClientEvent:Connect(function(active)
	_G.NSM_Hunting = active
end)

-- FAKE GUEST (client-side only, vanishes when inspected/questioned)
local function spawnFakeGuest()
	local map = workspace:FindFirstChild("Map")
	local desk = map and map:FindFirstChild("DeskFurniture1")
	if not desk then return end
	local model = Instance.new("Model")
	model.Name = "FakeGuest"
	local hrp = Instance.new("Part")
	hrp.Size = Vector3.new(2, 2, 1)
	hrp.Transparency = 1
	hrp.CFrame = CFrame.new(0, 3.5, -11)
	hrp.Anchored = true
	hrp.Parent = model
	for _, def in ipairs({
		{ size = Vector3.new(2, 2, 1), off = CFrame.new() },
		{ size = Vector3.new(1.4, 1.4, 1.4), off = CFrame.new(0, 1.7, 0) },
		{ size = Vector3.new(0.95, 2, 0.95), off = CFrame.new(-1.5, 0, 0) },
		{ size = Vector3.new(0.95, 2, 0.95), off = CFrame.new(1.5, 0, 0) },
		{ size = Vector3.new(0.9, 2, 0.9), off = CFrame.new(-0.55, -2, 0) },
		{ size = Vector3.new(0.9, 2, 0.9), off = CFrame.new(0.55, -2, 0) },
	}) do
		local p = Instance.new("Part")
		p.Size = def.size
		p.CFrame = hrp.CFrame * def.off
		p.Anchored = true
		p.CanCollide = false
		p.Color = Color3.fromRGB(30, 30, 34)
		p.Transparency = 0.35
		p.Parent = model
	end
	local head = model:GetChildren()[2]
	local cd = Instance.new("ClickDetector")
	cd.MaxActivationDistance = 20
	cd.Parent = head
	model.Parent = map
	local vanished = false
	local function vanish()
		if vanished then return end
		vanished = true
		for _, p in ipairs(model:GetDescendants()) do
			if p:IsA("BasePart") then p.Transparency = 1 end
		end
		local burst = Instance.new("Sound")
		burst.SoundId = "rbxasset://sounds/flashbulb.wav"
		burst.Volume = 1
		burst.Parent = head
		burst:Play()
		game:GetService("Debris"):AddItem(model, 1)
		remotes.Notify:FireServer("it was never there")
	end
	cd.MouseClick:Connect(vanish)
	task.delay(math.random(8, 16), vanish)
end

-- HALLUCINATION LOOP
task.spawn(function()
	local t0 = os.clock()
	while true do
		RunService.RenderStepped:Wait()
		if hallucinating then
			local t = os.clock() - t0
			cc.TintColor = Color3.fromRGB(255, 200 + math.sin(t * 2) * 40, 200 + math.cos(t * 3) * 40)
			cc.Saturation = math.sin(t * 1.5) * 0.4
			whisper.Volume = 0.25 + math.abs(math.sin(t)) * 0.2
			local cam = workspace.CurrentCamera
			if cam and cam.CameraType == Enum.CameraType.Custom then
				cam.FieldOfView = 70 + math.sin(t * 1.2) * 6
			end
			if math.random() < 0.002 then
				spawnFakeGuest()
			end
			if math.random() < 0.001 then
				local map = workspace:FindFirstChild("Map")
				local num = math.random(1, 6)
				if map then
					local ghost = Instance.new("Part")
					ghost.Size = Vector3.new(2, 5, 1)
					ghost.CFrame = CFrame.new((num - 101) * 10 - 25, 3, -40)
					ghost.Anchored = true
					ghost.CanCollide = false
					ghost.Color = Color3.fromRGB(10, 10, 12)
					ghost.Transparency = 0.4
					ghost.Name = "Hallucination"
					ghost.Parent = map
					task.delay(6, function() ghost:Destroy() end)
				end
			end
		else
			whisper.Volume = 0
			local cam = workspace.CurrentCamera
			if cam and cam.FieldOfView ~= 70 then
				cam.FieldOfView = 70
			end
		end
	end
end)
