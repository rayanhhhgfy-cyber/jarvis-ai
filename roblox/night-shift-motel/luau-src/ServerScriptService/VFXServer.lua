-- VFXServer: every visual effect and sound in one place.
local VFXServer = {}

local builtins = {
	bell = "rbxasset://sounds/electronicpingshort.wav",
	click = "rbxasset://sounds/button.wav",
	lock = "rbxasset://sounds/snap.mp3",
	static = "rbxasset://sounds/flashbulb.wav",
	breakDoor = "rbxasset://sounds/glassbreak.wav",
	caught = "rbxasset://sounds/uuhhh.mp3",
	whoosh = "rbxasset://sounds/swoosh.wav",
	dawn = "rbxasset://sounds/victory.wav",
	rumble = "rbxasset://sounds/collide.wav",
	drone = "rbxasset://sounds/bass.wav",
	water = "rbxasset://sounds/impact_water.mp3",
}

local Lighting = game:GetService("Lighting")
local rainEmitter, dustEmitter, droneLoop
local signBaseColor = Color3.fromRGB(255, 40, 40)
local flickerRunning = false

function VFXServer.Init(ctx)
	VFXServer.ctx = ctx
	local Map = ctx.Map

	local rain = Instance.new("ParticleEmitter")
	rain.Texture = "rbxassetid://241876428"
	rain.Rate = 260
	rain.Lifetime = NumberRange.new(1.6, 2.2)
	rain.Speed = NumberRange.new(38, 46)
	rain.Acceleration = Vector3.new(2, -12, 4)
	rain.Size = NumberSequence.new(0.35)
	rain.Transparency = NumberSequence.new(0.35)
	rain.Rotation = NumberRange.new(0, 360)
	rain.RotSpeed = NumberRange.new(-40, 40)
	rain.EmissionDirection = Enum.NormalId.Bottom
	rain.Color = ColorSequence.new(Color3.fromRGB(190, 205, 220))
	rain.Parent = Map.RainPart
	rainEmitter = rain

	local dust = Instance.new("ParticleEmitter")
	dust.Texture = "rbxasset://textures/particles/sparkles_main.dds"
	dust.Rate = 6
	dust.Lifetime = NumberRange.new(4, 8)
	dust.Speed = NumberRange.new(0.2, 0.6)
	dust.Size = NumberSequence.new(0.12)
	dust.Transparency = NumberSequence.new(0.75)
	dust.EmissionDirection = Enum.NormalId.Bottom
	dust.Color = ColorSequence.new(Color3.fromRGB(255, 240, 210))
	dust.Parent = Map.DustPart
	dustEmitter = dust

	droneLoop = Instance.new("Sound")
	droneLoop.SoundId = builtins.drone
	droneLoop.Looped = true
	droneLoop.Volume = 0.15
	droneLoop.Pitch = 0.45
	droneLoop.Parent = workspace
	droneLoop:Play()

	task.spawn(function()
		while true do
			task.wait(math.random(25, 70))
			VFXServer.Thunder()
		end
	end)

	task.spawn(function()
		while true do
			task.wait(math.random(7, 18))
			if not flickerRunning and ctx.State.phase == "Night" then
				VFXServer.FlickerRandom()
			end
		end
	end)
end

function VFXServer.Play(name, parent, volume, pitch, looped)
	local s = Instance.new("Sound")
	s.SoundId = builtins[name] or builtins.click
	s.Volume = volume or 0.8
	s.Pitch = pitch or 1
	s.Looped = looped or false
	s.Parent = parent or workspace
	s:Play()
	if not looped then
		game:GetService("Debris"):AddItem(s, 6)
	end
	return s
end

function VFXServer.Thunder()
	VFXServer.Play("rumble", workspace, 0.5, 0.3)
end

function VFXServer.SetRain(on, intensity)
	if not rainEmitter then return end
	rainEmitter.Enabled = on
	if intensity then rainEmitter.Rate = 260 * intensity end
end

function VFXServer.SetFog(on)
	local atmo = Lighting:FindFirstChild("Atmosphere")
	if atmo then atmo.Density = on and 0.42 or 0.15 end
end

function VFXServer.SetSign(on, color)
	local ctx = VFXServer.ctx
	for _, p in ipairs(ctx.Map.SignNeons) do
		p.Transparency = on and 0 or 1
		if color then p.Color = color end
	end
	if color then
		ctx.Map.SignTexts.motel.TextColor3 = color
	else
		ctx.Map.SignTexts.motel.TextColor3 = signBaseColor
	end
	ctx.Map.SignTexts.number.Visible = on
	ctx.Map.SignBoard.Transparency = on and 0 or 0.4
end

local function setAllLights(on, color)
	local Map = VFXServer.ctx.Map
	for _, l in ipairs(Map.LobbyLights) do
		l.Transparency = on and 0 or 1
		local pl = l:FindFirstChildOfClass("PointLight")
		if pl then pl.Enabled = on if color then pl.Color = color end end
		if color then l.Color = color end
	end
	if Map.CorridorLight then
		Map.CorridorLight.Transparency = on and 0 or 1
		local pl = Map.CorridorLight:FindFirstChildOfClass("PointLight")
		if pl then pl.Enabled = on if color then pl.Color = color end end
		if color then Map.CorridorLight.Color = color end
	end
	for _, door in pairs(Map.Doors) do
		door.light.Transparency = on and 0 or 1
		local pl = door.lightObj
		if pl then pl.Enabled = on if color then pl.Color = color end end
		if color then door.light.Color = color end
	end
end

function VFXServer.SetLights(on)
	setAllLights(on, nil)
end

function VFXServer.FlickerRandom()
	flickerRunning = true
	local Map = VFXServer.ctx.Map
	local pool = {}
	for _, l in ipairs(Map.LobbyLights) do table.insert(pool, l) end
	table.insert(pool, Map.CorridorLight)
	local target = pool[math.random(#pool)]
	for i = 1, 3 do
		target.Transparency = 1
		local pl = target:FindFirstChildOfClass("PointLight")
		if pl then pl.Enabled = false end
		task.wait(0.08)
		target.Transparency = 0
		if pl then pl.Enabled = true end
		task.wait(0.12)
	end
	flickerRunning = false
end

function VFXServer.PowerFlicker(duration)
	flickerRunning = true
	setAllLights(false, nil)
	VFXServer.ctx.Remotes.PowerFlicker:FireAllClients(duration)
	for _, pl in ipairs(game:GetService("Players"):GetPlayers()) do
		VFXServer.ctx.Sanity.Drain(pl, 5, "power flicker")
	end
	task.wait(duration or 10)
	setAllLights(true, nil)
	flickerRunning = false
end

function VFXServer.Lockdown(on)
	setAllLights(on, Color3.fromRGB(255, 30, 30))
	local atmo = Lighting:FindFirstChild("Atmosphere")
	if atmo then
		if on then
			atmo.Color = Color3.fromRGB(120, 10, 10)
			atmo.Haze = 3
		else
			atmo.Color = Color3.fromRGB(120, 124, 134)
			atmo.Haze = 2
		end
	end
end

function VFXServer.DawnLight()
	Lighting.OutdoorAmbient = Color3.fromRGB(190, 150, 110)
	Lighting.Ambient = Color3.fromRGB(120, 100, 90)
	Lighting.Brightness = 2.4
	VFXServer.Play("dawn", workspace, 0.7)
end

function VFXServer.NightLight()
	Lighting.OutdoorAmbient = Color3.fromRGB(18, 22, 34)
	Lighting.Ambient = Color3.fromRGB(8, 8, 12)
	Lighting.Brightness = 0.6
end

function VFXServer.Shake(intensity)
	VFXServer.ctx.Remotes.Shake:FireAllClients(intensity or 1)
end

return VFXServer
