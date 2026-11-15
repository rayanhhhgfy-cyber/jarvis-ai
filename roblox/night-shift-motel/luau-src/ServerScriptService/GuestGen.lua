-- GuestGen v2: guest NPCs built as Motor6D rigs with a procedural walk cycle,
-- detailed faces and clothing, and the physical monster tells.
local RunService = game:GetService("RunService")

local GuestGen = {}

local rigs = {}

RunService.Heartbeat:Connect(function(dt)
	for model, rig in pairs(rigs) do
		if not model.Parent then
			rigs[model] = nil
		else
			local moving = rig.humanoid.Parent ~= nil and rig.humanoid.MoveDirection.Magnitude > 0.05
			if moving then
				rig.phase = (rig.phase or 0) + dt * 9
				local s = math.sin(rig.phase)
				rig.lShoulder.C0 = rig.baseLS * CFrame.Angles(s * 0.5, 0, 0.06)
				rig.rShoulder.C0 = rig.baseRS * CFrame.Angles(-s * 0.5, 0, -0.06)
				rig.lHip.C0 = rig.baseLH * CFrame.Angles(-s * 0.45, 0, 0)
				rig.rHip.C0 = rig.baseRH * CFrame.Angles(s * 0.45, 0, 0)
			else
				rig.lShoulder.C0 = rig.lShoulder.C0:Lerp(rig.baseLS, 0.15)
				rig.rShoulder.C0 = rig.rShoulder.C0:Lerp(rig.baseRS, 0.15)
				rig.lHip.C0 = rig.lHip.C0:Lerp(rig.baseLH, 0.15)
				rig.rHip.C0 = rig.rHip.C0:Lerp(rig.baseRH, 0.15)
			end
		end
	end
end)

local function part(model, size, cf, color, material)
	local p = Instance.new("Part")
	p.Size = size
	p.CFrame = cf
	p.Color = color
	p.Material = material or Enum.Material.SmoothPlastic
	p.Anchored = false
	p.CanCollide = false
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	p.Parent = model
	return p
end

local function weldTo(base, p)
	local w = Instance.new("WeldConstraint")
	w.Part0 = base
	w.Part1 = p
	w.Parent = p
end

local function motor(model, part0, part1, c0, c1, name)
	local m = Instance.new("Motor6D")
	m.Part0 = part0
	m.Part1 = part1
	m.C0 = c0
	m.C1 = c1
	m.Name = name
	m.Parent = part0
	return m
end

local function buildFace(model, head, skin, isMonster, has)
	if isMonster and has("BlackEyes") then
		for _, ex in ipairs({ -0.3, 0.3 }) do
			local e = part(model, Vector3.new(0.42, 0.44, 0.08), head.CFrame * CFrame.new(ex, 0.12, -0.62), Color3.fromRGB(8, 8, 8))
			e.Name = "Eye"
			weldTo(head, e)
		end
	else
		for _, ex in ipairs({ -0.3, 0.3 }) do
			local e = part(model, Vector3.new(0.3, 0.26, 0.06), head.CFrame * CFrame.new(ex, 0.14, -0.62), Color3.fromRGB(245, 245, 245))
			e.Name = "Eye"
			weldTo(head, e)
			local pu = part(model, Vector3.new(0.12, 0.12, 0.05), head.CFrame * CFrame.new(ex, 0.14, -0.66), Color3.fromRGB(20, 20, 24))
			pu.Name = "Pupil"
			weldTo(head, pu)
		end
	end
	local nose = part(model, Vector3.new(0.18, 0.26, 0.16), head.CFrame * CFrame.new(0, -0.06, -0.66), skin)
	weldTo(head, nose)
	if isMonster and has("TooManyTeeth") then
		for i = 1, 9 do
			local t = part(model, Vector3.new(0.12, 0.24, 0.06), head.CFrame * CFrame.new(-0.48 + (i - 1) * 0.12, -0.42, -0.62), Color3.fromRGB(250, 250, 240))
			t.Name = "Tooth"
			weldTo(head, t)
		end
	else
		local mouth = part(model, Vector3.new(0.5, 0.1, 0.06), head.CFrame * CFrame.new(0, -0.42, -0.62), Color3.fromRGB(96, 58, 58))
		weldTo(head, mouth)
	end
end

local function buildHat(model, head, isMonster)
	if isMonster then return end
	local roll = math.random()
	if roll < 0.22 then
		local dark = Color3.fromRGB(32, 30, 32)
		local brim = part(model, Vector3.new(1.9, 0.1, 1.9), head.CFrame * CFrame.new(0, 0.58, 0), dark, Enum.Material.Fabric)
		weldTo(head, brim)
		local crown = part(model, Vector3.new(1.1, 0.5, 1.1), head.CFrame * CFrame.new(0, 0.86, 0), dark, Enum.Material.Fabric)
		weldTo(head, crown)
	elseif roll < 0.65 then
		local hairColors = { Color3.fromRGB(42, 32, 24), Color3.fromRGB(22, 22, 22), Color3.fromRGB(92, 72, 46), Color3.fromRGB(122, 112, 102) }
		local hair = part(model, Vector3.new(1.36, 0.38, 1.36), head.CFrame * CFrame.new(0, 0.52, 0), hairColors[math.random(#hairColors)], Enum.Material.Fabric)
		weldTo(head, hair)
	end
end

local function buildClothes(model, torso)
	local shirt = part(model, Vector3.new(1.2, 1.7, 0.12), torso.CFrame * CFrame.new(0, 0.05, -0.47), Color3.fromRGB(224, 221, 208))
	weldTo(torso, shirt)
	local tie = part(model, Vector3.new(0.3, 0.85, 0.08), torso.CFrame * CFrame.new(0, 0.38, -0.55), Color3.fromRGB(118, 30, 36))
	weldTo(torso, tie)
	local belt = part(model, Vector3.new(2.06, 0.28, 1.06), torso.CFrame * CFrame.new(0, -0.88, 0), Color3.fromRGB(26, 22, 20))
	weldTo(torso, belt)
end

local function buildArm(model, torso, side, armLen, suit, skin, sixFingers)
	local c0 = CFrame.new(side * 1.425, 0.75, 0)
	local c1 = CFrame.new(0, -armLen / 2 + 0.3, 0)
	local armCF = torso.CFrame * c0 * c1
	local arm = part(model, Vector3.new(0.85, armLen, 0.85), armCF, suit)
	arm.Name = "Arm"
	local m = motor(model, torso, arm, c0, c1, "Shoulder")
	local hand = part(model, Vector3.new(0.8, 0.55, 0.8), armCF * CFrame.new(0, -armLen / 2 - 0.2, 0), skin)
	weldTo(arm, hand)
	local count = sixFingers and 6 or 5
	for i = 1, count do
		local off = -0.3 + (i - 1) * (0.6 / (count - 1))
		local f = part(model, Vector3.new(0.13, 0.42, 0.13), hand.CFrame * CFrame.new(off, -0.42, 0), skin)
		f.Name = "Finger"
		weldTo(hand, f)
	end
	return m
end

local function buildLeg(model, torso, side)
	local c0 = CFrame.new(side * 0.55, -1, 0)
	local c1 = CFrame.new(0, -1, 0)
	local legCF = torso.CFrame * c0 * c1
	local leg = part(model, Vector3.new(0.85, 2, 0.85), legCF, Color3.fromRGB(36, 36, 42))
	leg.Name = "Leg"
	local m = motor(model, torso, leg, c0, c1, "Hip")
	local shoe = part(model, Vector3.new(0.9, 0.3, 1.15), legCF * CFrame.new(0, -1.05, -0.12), Color3.fromRGB(20, 20, 22))
	weldTo(leg, shoe)
	return m
end

-- spec = { isMonster, tells (array of tell ids), angry, cameraApp, walkSpeed, desk, spawnPos, idFrom }
function GuestGen.Create(ctx, spec)
	local Config = ctx.Config
	local isMonster = spec.isMonster
	local tells = spec.tells or {}
	local has = function(id)
		for _, t in ipairs(tells) do
			if t == id then return true end
		end
		return false
	end

	local first = Config.FirstNames[math.random(#Config.FirstNames)]
	local last = Config.LastNames[math.random(#Config.LastNames)]
	local idName = first .. " " .. last
	local spokenName = idName
	if isMonster and has("NameMismatch") then
		local other = Config.FirstNames[math.random(#Config.FirstNames)] .. " " .. Config.LastNames[math.random(#Config.LastNames)]
		if other == idName then other = other .. "s" end
		spokenName = other
	end

	local pale = isMonster and has("PaleSkin")
	local skin = pale and Color3.fromRGB(216, 214, 208) or Color3.fromRGB(math.random(150, 210), math.random(120, 165), math.random(100, 140))
	local suit = Color3.fromRGB(math.random(28, 60), math.random(28, 60), math.random(34, 70))

	local model = Instance.new("Model")
	model.Name = "Guest"

	local hrp = Instance.new("Part")
	hrp.Name = "HumanoidRootPart"
	hrp.Size = Vector3.new(2, 2, 1)
	hrp.Transparency = 1
	hrp.CanCollide = true
	hrp.CFrame = CFrame.new(spec.spawnPos or Vector3.new(0, 3.5, 55))
	hrp.Parent = model

	local torso = part(model, Vector3.new(2, 2, 1), hrp.CFrame, suit)
	torso.Name = "Torso"
	motor(model, hrp, torso, CFrame.new(), CFrame.new(), "RootJoint")

	local head = part(model, Vector3.new(1.3, 1.3, 1.3), hrp.CFrame * CFrame.new(0, 1.8, 0), skin)
	head.Name = "Head"
	motor(model, torso, head, CFrame.new(0, 1.15, 0), CFrame.new(0, -0.65, 0), "Neck")

	buildFace(model, head, skin, isMonster, has)
	buildHat(model, head, isMonster)
	buildClothes(model, torso)

	local armLen = (isMonster and has("LongHands")) and 3.2 or 2
	local sixFingers = isMonster and has("ExtraFinger")
	local lShoulder = buildArm(model, torso, -1, armLen, suit, skin, sixFingers)
	local rShoulder = buildArm(model, torso, 1, armLen, suit, skin, sixFingers)
	local lHip = buildLeg(model, torso, -1)
	local rHip = buildLeg(model, torso, 1)

	if isMonster and has("ShadowWrong") then
		local sh = part(model, Vector3.new(4.5, 0.06, 1.2), hrp.CFrame * CFrame.new(0.8, -2.97, 0.5) * CFrame.Angles(0, math.rad(35), 0), Color3.fromRGB(10, 10, 12))
		sh.Name = "Shadow"
		weldTo(hrp, sh)
	end

	local humanoid = Instance.new("Humanoid")
	humanoid.WalkSpeed = spec.walkSpeed or 16
	humanoid.HipHeight = 2.2
	humanoid.MaxHealth = 100
	humanoid.Health = 100
	humanoid.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
	humanoid.Parent = model

	local cd = Instance.new("ClickDetector")
	cd.MaxActivationDistance = 22
	cd.Parent = head

	model.PrimaryPart = hrp

	rigs[model] = {
		humanoid = humanoid,
		lShoulder = lShoulder,
		rShoulder = rShoulder,
		lHip = lHip,
		rHip = rHip,
		baseLS = lShoulder.C0,
		baseRS = rShoulder.C0,
		baseLH = lHip.C0,
		baseRH = rHip.C0,
		phase = math.random() * 6,
	}

	local answers = {}
	local wrongYear = isMonster and has("WrongYear")
	local year = Config.CurrentYear
	if wrongYear then
		year = ({ 1974, 1953, 1888, 2024 - math.random(20, 60) })[math.random(4)]
		if year >= Config.CurrentYear then year = 1966 end
	end
	local fromAnswer = spec.idFrom or Config.Cities[math.random(#Config.Cities)]
	if isMonster and math.random() < 0.5 then
		fromAnswer = Config.CreepyLines[math.random(#Config.CreepyLines)]
	end
	answers.from = fromAnswer
	answers.year = tostring(year) .. "."
	if isMonster and math.random() < 0.4 then
		answers.year = answers.year .. " Is that right?"
	end
	answers.job = Config.Jobs[math.random(#Config.Jobs)]
	if isMonster and math.random() < 0.5 then
		answers.job = Config.CreepyJobs[math.random(#Config.CreepyJobs)]
	end
	answers.stay = Config.Stays[math.random(#Config.Stays)]
	if isMonster and math.random() < 0.4 then
		answers.stay = Config.CreepyStays[math.random(#Config.CreepyStays)]
	end

	local guest = {
		id = tostring(math.random(100000, 999999)) .. tostring(os.clock() * 1000),
		desk = spec.desk,
		isMonster = isMonster,
		tells = tells,
		angry = spec.angry or false,
		cameraApp = spec.cameraApp or "normal",
		idCard = { name = idName, from = spec.idFrom or answers.from, job = answers.job, stay = answers.stay },
		spokenName = spokenName,
		answers = answers,
		walkSpeed = spec.walkSpeed or 16,
		model = model,
		roomNumber = nil,
	}

	model:SetAttribute("GuestId", guest.id)
	return guest
end

function GuestGen.Say(guest, text)
	local head = guest.model:FindFirstChild("Head")
	if not head then return end
	local old = head:FindFirstChild("GuestBubble")
	if old then old:Destroy() end
	local bb = Instance.new("BillboardGui")
	bb.Name = "GuestBubble"
	bb.Size = UDim2.new(0, 260, 0, 90)
	bb.StudsOffset = Vector3.new(0, 2.4, 0)
	bb.AlwaysOnTop = true
	bb.MaxDistance = 60
	bb.Parent = head
	local tl = Instance.new("TextLabel")
	tl.Size = UDim2.new(1, 0, 1, 0)
	tl.BackgroundColor3 = Color3.fromRGB(20, 20, 24)
	tl.BackgroundTransparency = 0.25
	tl.TextColor3 = Color3.fromRGB(240, 240, 240)
	tl.TextScaled = true
	tl.Font = Enum.Font.Gotham
	tl.TextWrapped = true
	tl.Text = text
	tl.Parent = bb
	task.delay(6, function()
		if bb.Parent then bb:Destroy() end
	end)
end

return GuestGen
