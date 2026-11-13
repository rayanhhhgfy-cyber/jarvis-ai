-- GuestGen: builds guest NPCs and their hidden human/monster data.
local GuestGen = {}

local function weldTo(model, part, base)
	local wc = Instance.new("WeldConstraint")
	wc.Part0 = base
	wc.Part1 = part
	wc.Parent = model
end

local function limb(model, base, size, cf, color, material)
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
	weldTo(model, p, base)
	return p
end

local function eyes(model, base, headCF, skin, blackEyes)
	local eyeColor = blackEyes and Color3.fromRGB(8, 8, 8) or Color3.fromRGB(245, 245, 245)
	local eyeSize = blackEyes and Vector3.new(0.38, 0.34, 0.08) or Vector3.new(0.24, 0.22, 0.06)
	for _, ex in ipairs({ -0.3, 0.3 }) do
		local e = limb(model, base, eyeSize, headCF * CFrame.new(ex, 0.12, -0.68), eyeColor)
		e.Name = "Eye"
	end
end

local function fingers(model, base, handCF, six, skin)
	local count = six and 6 or 5
	for i = 1, count do
		local off = -0.45 + (i - 1) * 0.18
		limb(model, base, Vector3.new(0.14, 0.45, 0.14), handCF * CFrame.new(off, -0.2, 0), skin, Enum.Material.SmoothPlastic)
	end
end

local function teeth(model, base, headCF)
	for i = 1, 9 do
		local t = limb(model, base, Vector3.new(0.13, 0.26, 0.05), headCF * CFrame.new(-0.5 + (i - 1) * 0.125, -0.42, -0.68), Color3.fromRGB(250, 250, 240))
		t.Name = "Tooth"
	end
end

-- spec = { isMonster, tells (array of tell ids), angry, cameraApp, walkSpeed }
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

	local torso = limb(model, hrp, Vector3.new(2, 2, 1), hrp.CFrame, suit)
	torso.Name = "Torso"
	local headCF = hrp.CFrame * CFrame.new(0, 1.7, 0)
	local head = limb(model, hrp, Vector3.new(1.4, 1.4, 1.4), headCF, skin)
	head.Name = "Head"

	eyes(model, hrp, headCF, skin, isMonster and has("BlackEyes"))
	if isMonster and has("TooManyTeeth") then
		teeth(model, hrp, headCF)
	end

	local armLen = (isMonster and has("LongHands")) and 3.2 or 2
	for _, side in ipairs({ -1.5, 1.5 }) do
		local armCF = hrp.CFrame * CFrame.new(side, 1 - armLen / 2, 0)
		local arm = limb(model, hrp, Vector3.new(0.95, armLen, 0.95), armCF, suit)
		arm.Name = "Arm"
		fingers(model, hrp, armCF * CFrame.new(0, -armLen / 2, 0), isMonster and has("ExtraFinger") and side > 0, skin)
	end
	for _, side in ipairs({ -0.55, 0.55 }) do
		local leg = limb(model, hrp, Vector3.new(0.9, 2, 0.9), hrp.CFrame * CFrame.new(side, -2, 0), Color3.fromRGB(35, 35, 40))
		leg.Name = "Leg"
	end

	if isMonster and has("ShadowWrong") then
		local sh = limb(model, hrp, Vector3.new(4.5, 0.06, 1.2), hrp.CFrame * CFrame.new(0.8, -2.97, 0.5) * CFrame.Angles(0, math.rad(35), 0), Color3.fromRGB(10, 10, 12))
		sh.Name = "Shadow"
	end

	local humanoid = Instance.new("Humanoid")
	humanoid.WalkSpeed = spec.walkSpeed or 16
	humanoid.HipHeight = 2
	humanoid.MaxHealth = 100
	humanoid.Health = 100
	humanoid.Parent = model

	local cd = Instance.new("ClickDetector")
	cd.MaxActivationDistance = 22
	cd.Parent = head

	model.PrimaryPart = hrp

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
