-- MapBuilder v2: builds the entire motel from Parts at runtime. Detailed horror-motel look.
local MapBuilder = {}

local map

local function P(t)
	local p = Instance.new(t.Class or "Part")
	p.Anchored = true
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	p.Size = t.Size or Vector3.new(4, 1, 2)
	p.CFrame = t.CF or CFrame.new(t.Pos or Vector3.new()) * CFrame.Angles((t.Rot and t.Rot[1]) or 0, (t.Rot and t.Rot[2]) or 0, (t.Rot and t.Rot[3]) or 0)
	p.Color = t.Color or Color3.fromRGB(120, 120, 120)
	p.Material = t.Material or Enum.Material.SmoothPlastic
	if t.Transparency then p.Transparency = t.Transparency end
	if t.Reflectance then p.Reflectance = t.Reflectance end
	if t.CanCollide ~= nil then p.CanCollide = t.CanCollide end
	if t.Shape then p.Shape = t.Shape end
	if t.Name then p.Name = t.Name end
	p.Parent = t.Parent or map
	return p
end

local function label(part, text, textColor, face, font, bg)
	local sg = Instance.new("SurfaceGui")
	sg.Face = face or Enum.NormalId.Front
	sg.CanvasSize = Vector2.new(600, 300)
	sg.Parent = part
	local tl = Instance.new("TextLabel")
	tl.Size = UDim2.new(1, 0, 1, 0)
	tl.BackgroundColor3 = bg or Color3.fromRGB(12, 10, 10)
	tl.BackgroundTransparency = bg and 0 or 1
	tl.Text = text
	tl.TextColor3 = textColor or Color3.fromRGB(255, 60, 60)
	tl.TextScaled = true
	tl.Font = font or Enum.Font.Arcade
	tl.Parent = sg
	return tl
end

local function light(part, brightness, range, color)
	local pl = Instance.new("PointLight")
	pl.Brightness = brightness or 1.2
	pl.Range = range or 18
	pl.Color = color or Color3.fromRGB(255, 225, 180)
	pl.Parent = part
	return pl
end

local function makePrompt(parent, text, hold, maxDist)
	local pr = Instance.new("ProximityPrompt")
	pr.ActionText = text
	pr.ObjectText = ""
	pr.HoldDuration = hold or 0
	pr.MaxActivationDistance = maxDist or 10
	pr.RequiresLineOfSight = false
	pr.Parent = parent
	return pr
end

local function tree(x, z, s)
	s = s or 1
	P({ Pos = Vector3.new(x, 3 * s, z), Size = Vector3.new(1.6 * s, 6 * s, 1.6 * s), Color = Color3.fromRGB(66, 48, 36), Material = Enum.Material.Wood })
	P({ Pos = Vector3.new(x, 7 * s, z), Size = Vector3.new(6.5 * s, 3.6 * s, 6.5 * s), Color = Color3.fromRGB(28, 58, 38), Material = Enum.Material.Grass })
	P({ Pos = Vector3.new(x, 10.2 * s, z), Size = Vector3.new(4.8 * s, 3.2 * s, 4.8 * s), Color = Color3.fromRGB(24, 52, 34), Material = Enum.Material.Grass })
	P({ Pos = Vector3.new(x, 13 * s, z), Size = Vector3.new(3 * s, 2.8 * s, 3 * s), Color = Color3.fromRGB(20, 46, 30), Material = Enum.Material.Grass })
end

local function bush(x, z)
	P({ Pos = Vector3.new(x, 0.9, z), Size = Vector3.new(2.6, 1.8, 2.6), Shape = Enum.PartType.Ball, Color = Color3.fromRGB(30, 56, 36), Material = Enum.Material.Grass })
end

local function plantPot(x, z, parent)
	local pot = P({ Parent = parent, Pos = Vector3.new(x, 0.7, z), Size = Vector3.new(1.2, 1.4, 1.2), Shape = Enum.PartType.Cylinder, Rot = { 0, 0, 90 }, Color = Color3.fromRGB(140, 70, 50), Material = Enum.Material.Concrete })
	P({ Parent = parent, Pos = Vector3.new(x, 2.2, z), Size = Vector3.new(1.7, 1.9, 1.7), Shape = Enum.PartType.Ball, Color = Color3.fromRGB(40, 78, 48), Material = Enum.Material.Grass, CanCollide = false })
	return pot
end

local function car(x, z, rot, color)
	local folder = Instance.new("Folder")
	folder.Name = "Car"
	folder.Parent = map
	local cf = CFrame.new(x, 1.2, z) * CFrame.Angles(0, rot, 0)
	P({ Parent = folder, CF = cf, Size = Vector3.new(6.4, 1.3, 13), Color = color, Material = Enum.Material.Metal, Reflectance = 0.25 })
	P({ Parent = folder, CF = cf * CFrame.new(0, 1.15, -0.6), Size = Vector3.new(5.6, 1.3, 6.4), Color = Color3.fromRGB(24, 26, 30), Material = Enum.Material.Glass, Transparency = 0.35 })
	for _, wx in ipairs({ -2.6, 2.6 }) do
		for _, wz in ipairs({ -4.2, 4.2 }) do
			P({ Parent = folder, CF = cf * CFrame.new(wx, -0.55, wz) * CFrame.Angles(0, 0, math.rad(90)), Size = Vector3.new(1.1, 2.4, 1.1), Shape = Enum.PartType.Cylinder, Color = Color3.fromRGB(20, 20, 22), Material = Enum.Material.Rubber or Enum.Material.SmoothPlastic })
		end
	end
	P({ Parent = folder, CF = cf * CFrame.new(0, 0.1, 6.55), Size = Vector3.new(5.2, 0.5, 0.3), Color = Color3.fromRGB(255, 240, 190), Material = Enum.Material.Neon })
	P({ Parent = folder, CF = cf * CFrame.new(0, 0.1, -6.55), Size = Vector3.new(5.2, 0.5, 0.3), Color = Color3.fromRGB(255, 60, 50), Material = Enum.Material.Neon })
end

local Map = {}
Map.Desks = {}
Map.Doors = {}
Map.RoomLights = {}
Map.Rooms = {}
Map.Cameras = {}
Map.LobbyLights = {}
Map.SignNeons = {}

function MapBuilder.Build(ctx)
	map = Instance.new("Folder")
	map.Name = "Map"
	map.Parent = workspace

	local asphalt = Color3.fromRGB(40, 40, 44)
	local grass = Color3.fromRGB(34, 48, 32)
	local brick = Color3.fromRGB(94, 62, 54)
	local trim = Color3.fromRGB(196, 176, 138)
	local wood = Color3.fromRGB(104, 74, 50)
	local woodDark = Color3.fromRGB(72, 50, 34)
	local wallWood = Color3.fromRGB(116, 86, 58)
	local carpet = Color3.fromRGB(88, 32, 32)
	local roomFloor = Color3.fromRGB(122, 88, 58)

	-- ============ GROUND / LOT / ROAD ============
	P({ Pos = Vector3.new(0, -0.5, 5), Size = Vector3.new(260, 1, 220), Color = grass, Material = Enum.Material.Grass, Name = "Ground" })
	P({ Pos = Vector3.new(0, -0.44, 20), Size = Vector3.new(180, 0.12, 120), Color = asphalt, Material = Enum.Material.Asphalt, Reflectance = 0.14, Name = "Lot" })
	P({ Pos = Vector3.new(0, -0.4, 92), Size = Vector3.new(260, 0.2, 26), Color = Color3.fromRGB(30, 30, 33), Material = Enum.Material.Asphalt, Name = "Road" })
	for i = -6, 6 do
		P({ Pos = Vector3.new(i * 18, -0.28, 92), Size = Vector3.new(7, 0.06, 0.9), Color = Color3.fromRGB(215, 195, 80), CanCollide = false })
	end
	for i = -2, 2 do
		P({ Pos = Vector3.new(i * 7 - 14, -0.28, 80.5), Size = Vector3.new(0.9, 0.06, 22), Color = Color3.fromRGB(230, 230, 225), CanCollide = false, Transparency = 0.3 })
	end
	-- curbs + parking lines
	for i = -3, 3 do
		P({ Pos = Vector3.new(i * 14, 0.15, 36), Size = Vector3.new(0.6, 0.3, 24), Color = Color3.fromRGB(180, 178, 170), Material = Enum.Material.Concrete })
		P({ Pos = Vector3.new(i * 14 - 7, 0.06, 42), Size = Vector3.new(0.5, 0.06, 20), Color = Color3.fromRGB(225, 225, 220), CanCollide = false })
		P({ Pos = Vector3.new(i * 14 + 7, 0.06, 42), Size = Vector3.new(0.5, 0.06, 20), Color = Color3.fromRGB(225, 225, 220), CanCollide = false })
	end
	P({ Pos = Vector3.new(0, 0.04, 24), Size = Vector3.new(120, 0.08, 8), Color = Color3.fromRGB(150, 148, 142), Material = Enum.Material.Concrete, Name = "Sidewalk" })
	P({ Pos = Vector3.new(0, 0.04, 30), Size = Vector3.new(10, 0.08, 16), Color = Color3.fromRGB(150, 148, 142), Material = Enum.Material.Concrete, Name = "Walkway" })

	car(-21, 44, math.rad(90), Color3.fromRGB(96, 34, 38))
	car(35, 46, math.rad(90), Color3.fromRGB(52, 66, 88))
	car(7, 46, math.rad(90), Color3.fromRGB(70, 70, 74))

	-- dumpster + crates + power box + bench
	P({ Pos = Vector3.new(-42, 1.6, 30), Size = Vector3.new(6, 3.2, 3.4), Color = Color3.fromRGB(40, 62, 44), Material = Enum.Material.DiamondPlate, Name = "Dumpster" })
	P({ Pos = Vector3.new(-42, 3.4, 30), Size = Vector3.new(6.4, 0.4, 3.8), Color = Color3.fromRGB(34, 52, 38), Material = Enum.Material.Metal, Rot = { math.rad(-8), 0, 0 } })
	P({ Pos = Vector3.new(44, 1, 28), Size = Vector3.new(3, 2, 3), Color = Color3.fromRGB(96, 72, 48), Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(44, 2.9, 28), Size = Vector3.new(2.6, 1.8, 2.6), Color = Color3.fromRGB(88, 66, 44), Material = Enum.Material.WoodPlanks, Rot = { 0, math.rad(20), 0 } })
	P({ Pos = Vector3.new(44, 1.5, 24), Size = Vector3.new(2.4, 3, 1.2), Color = Color3.fromRGB(70, 74, 78), Material = Enum.Material.Metal, Name = "PowerBox" })
	label(P({ Pos = Vector3.new(44, 1.5, 24.65), Size = Vector3.new(1.8, 1.2, 0.05), Color = Color3.fromRGB(200, 170, 60), CanCollide = false }), "!", Color3.fromRGB(40, 30, 10))
	P({ Pos = Vector3.new(14, 1.1, 26.5), Size = Vector3.new(6, 0.4, 2.2), Color = Color3.fromRGB(96, 66, 44), Material = Enum.Material.Wood })
	P({ Pos = Vector3.new(14, 0.55, 26.5), Size = Vector3.new(6, 0.9, 0.4), Color = Color3.fromRGB(96, 66, 44), Material = Enum.Material.Wood })

	-- ============ BUILDING SHELL (x -34..34, z -48..20) ============
	-- slab
	P({ Pos = Vector3.new(0, 0.06, -14), Size = Vector3.new(70, 0.12, 70), Color = Color3.fromRGB(60, 60, 62), Material = Enum.Material.Concrete })
	-- lobby floor: checkered
	for ix = 0, 15 do
		for iz = 0, 9 do
			local dark = (ix + iz) % 2 == 0
			P({
				Pos = Vector3.new(-30 + ix * 4, 0.14, -18 + iz * 4),
				Size = Vector3.new(4, 0.08, 4),
				Color = dark and Color3.fromRGB(22, 22, 25) or Color3.fromRGB(214, 210, 200),
				Material = Enum.Material.Marble,
				CanCollide = false,
			})
		end
	end
	-- corridor carpet
	P({ Pos = Vector3.new(0, 0.16, -26), Size = Vector3.new(64, 0.08, 12), Color = carpet, Material = Enum.Material.Fabric, CanCollide = false, Name = "CorridorCarpet" })

	-- FRONT WALL z=20 (door gap x -5..5, windows)
	P({ Pos = Vector3.new(-19.75, 7, 20.5), Size = Vector3.new(30.5, 14, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(19.75, 7, 20.5), Size = Vector3.new(30.5, 14, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(0, 11.5, 20.5), Size = Vector3.new(10, 5, 1), Color = brick, Material = Enum.Material.Brick })
	-- windows with frames
	for _, wx in ipairs({ -19.75, 19.75 }) do
		P({ Pos = Vector3.new(wx, 6, 20.35), Size = Vector3.new(24, 8, 0.3), Color = trim, Material = Enum.Material.Wood })
		P({ Pos = Vector3.new(wx, 6, 20.2), Size = Vector3.new(22.5, 6.5, 0.3), Color = Color3.fromRGB(120, 150, 170), Material = Enum.Material.Glass, Transparency = 0.55, CanCollide = false })
		P({ Pos = Vector3.new(wx, 6, 20.05), Size = Vector3.new(0.4, 6.5, 0.35), Color = trim, Material = Enum.Material.Wood, CanCollide = false })
		P({ Pos = Vector3.new(wx, 2.2, 20.35), Size = Vector3.new(24, 1, 0.5), Color = trim, Material = Enum.Material.Wood })
	end
	-- awning over entrance
	P({ Pos = Vector3.new(0, 9.6, 23.5), Size = Vector3.new(16, 0.5, 7), Color = Color3.fromRGB(110, 34, 34), Material = Enum.Material.Fabric, Rot = { math.rad(8), 0, 0 } })
	P({ Pos = Vector3.new(0, 10.2, 20.8), Size = Vector3.new(16, 1.2, 0.8), Color = trim, Material = Enum.Material.Wood })
	for _, px in ipairs({ -7, 7 }) do
		P({ Pos = Vector3.new(px, 4.8, 26.6), Size = Vector3.new(0.4, 9.6, 0.4), Color = Color3.fromRGB(40, 40, 44), Material = Enum.Material.Metal })
	end
	label(P({ Pos = Vector3.new(0, 10.2, 21.25), Size = Vector3.new(10, 1, 0.1), Color = Color3.fromRGB(24, 20, 18), CanCollide = false }), "OFFICE  ->", Color3.fromRGB(255, 200, 90))
	-- door mats
	P({ Pos = Vector3.new(0, 0.2, 22.5), Size = Vector3.new(8, 0.08, 4), Color = Color3.fromRGB(70, 40, 34), Material = Enum.Material.Fabric, CanCollide = false })

	-- SIDE WALLS
	P({ Pos = Vector3.new(-34.5, 7, -14), Size = Vector3.new(1, 14, 70), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(34.5, 7, -14), Size = Vector3.new(1, 14, 70), Color = brick, Material = Enum.Material.Brick })
	-- interior wall panels (lobby)
	P({ Pos = Vector3.new(-33.9, 6, -1), Size = Vector3.new(0.4, 12, 40), Color = wallWood, Material = Enum.Material.WoodPlanks, CanCollide = false })
	P({ Pos = Vector3.new(33.9, 6, -1), Size = Vector3.new(0.4, 12, 40), Color = wallWood, Material = Enum.Material.WoodPlanks, CanCollide = false })
	-- wainscot
	P({ Pos = Vector3.new(-33.7, 1.5, -1), Size = Vector3.new(0.3, 3, 40), Color = woodDark, Material = Enum.Material.Wood, CanCollide = false })
	P({ Pos = Vector3.new(33.7, 1.5, -1), Size = Vector3.new(0.3, 3, 40), Color = woodDark, Material = Enum.Material.Wood, CanCollide = false })

	-- BACK WALL z=-20 (corridor gap x -4..4)
	P({ Pos = Vector3.new(-19.75, 7, -20.5), Size = Vector3.new(30.5, 14, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(19.75, 7, -20.5), Size = Vector3.new(30.5, 14, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(0, 11.5, -20.5), Size = Vector3.new(10, 5, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(0, 2.5, -20.2), Size = Vector3.new(10, 5, 0.3), Color = woodDark, Material = Enum.Material.Wood, CanCollide = false })

	-- CORRIDOR WALLS (z=-32 with 6 door gaps, 5 wide)
	P({ Pos = Vector3.new(-29.75, 5, -32.5), Size = Vector3.new(1.5, 10, 1), Color = wallWood, Material = Enum.Material.WoodPlanks })
	for i = 0, 5 do
		local cx = -25 + i * 10
		P({ Pos = Vector3.new(cx, 5, -32.5), Size = Vector3.new(1, 10, 1), Color = wallWood, Material = Enum.Material.WoodPlanks })
		label(P({ Pos = Vector3.new(cx, 8, -32.2), Size = Vector3.new(2.4, 1, 0.1), Color = woodDark, CanCollide = false }), tostring(101 + i), Color3.fromRGB(240, 225, 180))
	end
	P({ Pos = Vector3.new(-32, 5, -26), Size = Vector3.new(1, 10, 14), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(32, 5, -26), Size = Vector3.new(1, 10, 14), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(0, 10.2, -26), Size = Vector3.new(64, 0.4, 12), Color = Color3.fromRGB(56, 40, 30) })
	local corridorLight = P({ Pos = Vector3.new(0, 9.9, -26), Size = Vector3.new(44, 0.25, 1.4), Color = Color3.fromRGB(255, 238, 205), Material = Enum.Material.Neon, Name = "CorridorLight" })
	light(corridorLight, 1.1, 32)
	Map.CorridorLight = corridorLight
	-- corridor dressing: framed pictures + wall lamps
	for _, px in ipairs({ -14, -6, 6, 14 }) do
		P({ Pos = Vector3.new(px, 5.5, -31.9), Size = Vector3.new(2.6, 3.4, 0.25), Color = Color3.fromRGB(70, 52, 36), Material = Enum.Material.Wood, CanCollide = false })
		label(P({ Pos = Vector3.new(px, 5.5, -31.75), Size = Vector3.new(2.1, 2.9, 0.1), Color = Color3.fromRGB(52, 44, 40), CanCollide = false }), "?:", Color3.fromRGB(150, 130, 110))
	end
	for _, px in ipairs({ -10, 10 }) do
		local wl = P({ Pos = Vector3.new(px, 6.5, -20.9), Size = Vector3.new(0.7, 1.1, 0.5), Color = Color3.fromRGB(255, 215, 150), Material = Enum.Material.Neon, CanCollide = false })
		light(wl, 0.6, 12)
	end

	-- ROOF (lobby y=14, rooms y=10) + parapet
	P({ Pos = Vector3.new(0, 14.2, -1), Size = Vector3.new(72, 0.6, 44), Color = Color3.fromRGB(52, 48, 46), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(0, 10.2, -40), Size = Vector3.new(72, 0.6, 30), Color = Color3.fromRGB(52, 48, 46), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(0, 14.8, 19.5), Size = Vector3.new(72, 1.2, 1), Color = trim, Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(-35.75, 14.8, -1), Size = Vector3.new(1, 1.2, 42), Color = trim, Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(35.75, 14.8, -1), Size = Vector3.new(1, 1.2, 42), Color = trim, Material = Enum.Material.Concrete })
	-- AC units on roof
	for _, acx in ipairs({ -18, 0, 18 }) do
		P({ Pos = Vector3.new(acx, 15.4, -8), Size = Vector3.new(5, 1.6, 4), Color = Color3.fromRGB(150, 152, 156), Material = Enum.Material.DiamondPlate })
	end

	-- CEILING LIGHTS (lobby)
	for _, pos in ipairs({ Vector3.new(-16, 13.6, -8), Vector3.new(16, 13.6, -8), Vector3.new(-16, 13.6, 8), Vector3.new(16, 13.6, 8) }) do
		P({ Pos = pos + Vector3.new(0, 0.35, 0), Size = Vector3.new(7, 0.3, 2.4), Color = woodDark, Material = Enum.Material.Wood })
		local lp = P({ Pos = pos, Size = Vector3.new(6, 0.3, 1.8), Color = Color3.fromRGB(255, 240, 210), Material = Enum.Material.Neon, Name = "LobbyLight" .. #Map.LobbyLights + 1 })
		light(lp, 1.4, 28)
		table.insert(Map.LobbyLights, lp)
	end

	-- ============ FRONT COUNTER + 3 DESKS ============
	P({ Pos = Vector3.new(0, 2, -12), Size = Vector3.new(32, 4, 2.6), Color = wood, Material = Enum.Material.WoodPlanks, Name = "Counter" })
	for i = -5, 5 do
		P({ Pos = Vector3.new(i * 3.1, 2, -10.62), Size = Vector3.new(2.7, 3.7, 0.15), Color = woodDark, Material = Enum.Material.Wood, CanCollide = false })
	end
	P({ Pos = Vector3.new(0, 4.2, -12), Size = Vector3.new(33, 0.4, 3.6), Color = Color3.fromRGB(58, 42, 30), Material = Enum.Material.Wood, Reflectance = 0.1 })
	P({ Pos = Vector3.new(0, 4.45, -10.4), Size = Vector3.new(33, 0.15, 0.4), Color = Color3.fromRGB(190, 160, 90), Material = Enum.Material.Metal, CanCollide = false })

	for slot = 1, 3 do
		local x = (slot - 2) * 10
		local furniture = Instance.new("Folder")
		furniture.Name = "DeskFurniture" .. slot
		furniture.Parent = map
		P({ Parent = furniture, Pos = Vector3.new(x + 1.6, 4.75, -12), Size = Vector3.new(1, 0.15, 1), Color = Color3.fromRGB(190, 160, 60), Material = Enum.Material.Metal })
		local bellDome = P({ Parent = furniture, Pos = Vector3.new(x + 1.6, 5, -12), Size = Vector3.new(0.6, 0.4, 0.6), Shape = Enum.PartType.Ball, Color = Color3.fromRGB(225, 195, 85), Material = Enum.Material.Metal, Name = "Bell" .. slot })
		P({ Parent = furniture, Pos = Vector3.new(x - 1.2, 4.6, -12.1), Size = Vector3.new(1.8, 0.3, 1.3), Color = Color3.fromRGB(205, 198, 180), Name = "Register" .. slot })
		P({ Parent = furniture, Pos = Vector3.new(x - 1.2, 4.78, -12.1), Size = Vector3.new(1.5, 0.1, 1), Color = Color3.fromRGB(90, 80, 70), CanCollide = false })
		P({ Parent = furniture, Pos = Vector3.new(x - 3, 5.1, -12.2), Size = Vector3.new(0.16, 1.6, 0.16), Color = Color3.fromRGB(50, 50, 54), Material = Enum.Material.Metal })
		local lampHead = P({ Parent = furniture, Pos = Vector3.new(x - 3, 6, -12.2), Size = Vector3.new(1, 0.4, 1), Color = Color3.fromRGB(110, 200, 120), Material = Enum.Material.Neon, Name = "DeskLamp" .. slot })
		light(lampHead, 0.8, 10)
		local seat = Instance.new("Seat")
		seat.Anchored = true
		seat.Size = Vector3.new(2.6, 0.4, 2.6)
		seat.CFrame = CFrame.new(x, 0.6, -15.5)
		seat.Color = Color3.fromRGB(110, 38, 38)
		seat.Material = Enum.Material.Fabric
		seat.Name = "DeskSeat" .. slot
		seat.Parent = furniture
		P({ Parent = furniture, Pos = Vector3.new(x, 0.3, -15.5), Size = Vector3.new(2.6, 0.6, 2.6), Color = woodDark, Material = Enum.Material.Wood, CanCollide = false })
		local sitPrompt = makePrompt(seat, "Sit", 0, 9)
		sitPrompt.ObjectText = "Desk " .. slot
		local ding = Instance.new("Sound")
		ding.SoundId = "rbxasset://sounds/electronicpingshort.wav"
		ding.Volume = 1
		ding.Parent = bellDome
		Map.Desks[slot] = { seat = seat, prompt = sitPrompt, bell = ding, pos = Vector3.new(x, 3, -9), bought = (slot == 1), furniture = furniture }
		if slot > 1 then
			for _, d in ipairs(furniture:GetDescendants()) do
				if d:IsA("BasePart") then d.Transparency = 1 end
				if d:IsA("Seat") then d.CanCollide = false end
				if d:IsA("ProximityPrompt") then d.Enabled = false end
			end
			seat.CanCollide = false
		end
	end

	-- KEY BOARD on back wall
	local keyBoard = P({ Pos = Vector3.new(0, 7.5, -19.8), Size = Vector3.new(12, 4.5, 0.4), Color = woodDark, Material = Enum.Material.Wood })
	for i = 1, 6 do
		P({ Parent = keyBoard, Pos = Vector3.new(-4.5 + (i - 1) * 1.8, 0.4, 0.4), Size = Vector3.new(0.5, 0.9, 0.15), Color = Color3.fromRGB(205, 185, 95), Material = Enum.Material.Metal })
		label(P({ Parent = keyBoard, Pos = Vector3.new(-4.5 + (i - 1) * 1.8, -1.2, 0.4), Size = Vector3.new(1.1, 1.4, 0.1), Color = Color3.fromRGB(40, 30, 22), CanCollide = false }), tostring(100 + i), Color3.fromRGB(240, 230, 180))
	end

	-- ============ COFFEE CORNER (right side of lobby) ============
	P({ Pos = Vector3.new(27.5, 1.9, -14), Size = Vector3.new(7, 3.8, 6), Color = wood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(27.5, 4, -14), Size = Vector3.new(7.6, 0.4, 6.6), Color = Color3.fromRGB(58, 42, 30), Material = Enum.Material.Wood })
	local coffeeMachine = P({ Pos = Vector3.new(25.6, 5.6, -14), Size = Vector3.new(2, 2.8, 1.8), Color = Color3.fromRGB(48, 48, 54), Material = Enum.Material.Metal, Name = "CoffeeMachine" })
	label(coffeeMachine, "COFFEE\n$5", Color3.fromRGB(255, 130, 60))
	P({ Pos = Vector3.new(25.6, 4.6, -13.05), Size = Vector3.new(1.2, 0.3, 0.3), Color = Color3.fromRGB(200, 200, 205), Material = Enum.Material.Metal, CanCollide = false })
	local buyPrompt = makePrompt(coffeeMachine, "Buy coffee (+" .. ctx.Config.CoffeeSanity .. " sanity)", 0, 10)
	buyPrompt.ObjectText = "Coffee corner"
	local brewSound = Instance.new("Sound")
	brewSound.SoundId = "rbxasset://sounds/swoosh.wav"
	brewSound.Volume = 0.4
	brewSound.Looped = true
	brewSound.Parent = coffeeMachine
	local warmer = P({ Pos = Vector3.new(28.6, 5.5, -14), Size = Vector3.new(2, 2.4, 1.8), Color = Color3.fromRGB(118, 68, 38), Material = Enum.Material.Metal, Name = "CoffeeWarmer" })
	label(warmer, "FREE\nPOT", Color3.fromRGB(255, 205, 95))
	local drinkPrompt = makePrompt(warmer, "Drink free pot (+" .. ctx.Config.WarmerSanity .. " sanity)", 0, 10)
	drinkPrompt.ObjectText = "Coffee warmer"
	drinkPrompt.Enabled = false
	for i = 1, 5 do
		P({ Pos = Vector3.new(30.2, 4.4 + i * 0.4, -12.2), Size = Vector3.new(1, 0.35, 1), Shape = Enum.PartType.Cylinder, Rot = { 0, 0, 90 }, Color = Color3.fromRGB(232, 230, 224) })
	end
	label(P({ Pos = Vector3.new(31.5, 6.5, -14), Size = Vector3.new(0.15, 2.6, 4), Color = Color3.fromRGB(26, 34, 28), Rot = { 0, math.rad(90), 0 } }), "MENU\nCoffee $5\nRefill FREE", Color3.fromRGB(240, 235, 215), Enum.NormalId.Left, Enum.Font.Gotham, true)
	Map.CoffeeMachine = coffeeMachine
	Map.CoffeeBuyPrompt = buyPrompt
	Map.Warmer = warmer
	Map.WarmerDrinkPrompt = drinkPrompt
	Map.BrewSound = brewSound

	-- ============ LOBBY DRESSING ============
	local vending = P({ Pos = Vector3.new(-30.5, 3.2, 12), Size = Vector3.new(4.4, 6.4, 2.6), Color = Color3.fromRGB(140, 28, 38), Material = Enum.Material.Metal, Name = "VendingMachine" })
	label(vending, "DRINKS", Color3.fromRGB(120, 255, 160))
	P({ Pos = Vector3.new(-30.5, 5.9, 10.65), Size = Vector3.new(3.6, 0.5, 0.3), Color = Color3.fromRGB(120, 255, 160), Material = Enum.Material.Neon, CanCollide = false })
	local ice = P({ Pos = Vector3.new(-30.5, 2.2, 6), Size = Vector3.new(3.4, 4.4, 2.4), Color = Color3.fromRGB(185, 190, 196), Material = Enum.Material.Metal, Name = "IceMachine" })
	label(ice, "ICE", Color3.fromRGB(60, 90, 200))
	local tv = P({ Pos = Vector3.new(0, 9, -19.9), Size = Vector3.new(5, 3, 0.5), Color = Color3.fromRGB(26, 26, 30), Name = "WallTV" })
	label(tv, "STATIC", Color3.fromRGB(140, 140, 145))
	P({ Pos = Vector3.new(0, 9, -19.6), Size = Vector3.new(5.6, 0.4, 0.6), Color = Color3.fromRGB(40, 40, 44), Material = Enum.Material.Metal, CanCollide = false })
	local phone = P({ Pos = Vector3.new(-27, 6.5, -19.8), Size = Vector3.new(1.4, 2, 0.5), Color = Color3.fromRGB(38, 38, 44), Material = Enum.Material.Metal, Name = "WallPhone" })
	P({ Pos = Vector3.new(-27, 6.5, -19.5), Size = Vector3.new(0.4, 1, 0.4), Color = Color3.fromRGB(38, 38, 44), CanCollide = false })
	-- seating area
	P({ Pos = Vector3.new(-14, 0.25, 6), Size = Vector3.new(16, 0.1, 12), Color = Color3.fromRGB(94, 30, 30), Material = Enum.Material.Fabric, CanCollide = false, Name = "LobbyRug" })
	P({ Pos = Vector3.new(-14, 1, 6), Size = Vector3.new(5, 1.2, 5), Color = woodDark, Material = Enum.Material.Wood, Name = "CoffeeTable" })
	for _, cx in ipairs({ -18.5, -9.5 }) do
		P({ Pos = Vector3.new(cx, 1.3, 6), Size = Vector3.new(2.2, 2.6, 2.2), Color = Color3.fromRGB(104, 36, 36), Material = Enum.Material.Fabric, Name = "Armchair" })
		P({ Pos = Vector3.new(cx, 2.9, 7.1), Size = Vector3.new(2.2, 2.4, 0.5), Color = Color3.fromRGB(104, 36, 36), Material = Enum.Material.Fabric, CanCollide = false })
	end
	P({ Pos = Vector3.new(-14, 1.3, 1), Size = Vector3.new(7, 2.6, 2.4), Color = Color3.fromRGB(96, 34, 34), Material = Enum.Material.Fabric, Name = "Sofa" })
	-- wall art + clock + house rules
	for _, def in ipairs({ { -24, 7.5, "MOTEL" }, { 24, 7.5, "9" }, { 12, 7.5, "zZ" } }) do
		P({ Pos = Vector3.new(def[1], def[2], -19.8), Size = Vector3.new(3, 4, 0.3), Color = Color3.fromRGB(70, 52, 36), Material = Enum.Material.Wood })
		label(P({ Pos = Vector3.new(def[1], def[2], -19.6), Size = Vector3.new(2.5, 3.5, 0.1), Color = Color3.fromRGB(46, 40, 36), CanCollide = false }), def[3], Color3.fromRGB(160, 140, 115))
	end
	local clockFace = P({ Pos = Vector3.new(-8, 9.5, -19.8), Size = Vector3.new(2.4, 2.4, 0.25), Shape = Enum.PartType.Cylinder, Rot = { 0, 0, 90 }, Color = Color3.fromRGB(232, 228, 218), Name = "WallClock" })
	label(clockFace, "12", Color3.fromRGB(30, 30, 30), Enum.NormalId.Front, Enum.Font.Arcade, true)
	P({ Pos = Vector3.new(-24.5, 7.5, -19.8), Size = Vector3.new(2.6, 3.6, 0.3), Color = Color3.fromRGB(222, 216, 196) })
	label(P({ Pos = Vector3.new(-24.5, 7.5, -19.6), Size = Vector3.new(2.2, 3.1, 0.1), Color = Color3.fromRGB(222, 216, 196), CanCollide = false }), "HOUSE\nRULES", Color3.fromRGB(40, 36, 30), Enum.NormalId.Front, Enum.Font.Arcade, true)
	-- plants
	plantPot(30, 14)
	plantPot(-30, -16)
	plantPot(20, 15)
	-- suitcases + typewriter + radio + candelabra + lantern
	P({ Pos = Vector3.new(10, 0.8, 4), Size = Vector3.new(2.2, 1.4, 3.2), Color = Color3.fromRGB(122, 96, 60), Material = Enum.Material.Fabric, Name = "Suitcase" })
	P({ Pos = Vector3.new(10.4, 2, 4), Size = Vector3.new(1.8, 0.9, 2.6), Color = Color3.fromRGB(108, 84, 52), Material = Enum.Material.Fabric, Rot = { 0, math.rad(12), 0 } })
	P({ Pos = Vector3.new(4.5, 4.7, -12), Size = Vector3.new(1.5, 0.7, 1.1), Color = Color3.fromRGB(38, 38, 44), Material = Enum.Material.Metal, Name = "Typewriter" })
	P({ Pos = Vector3.new(-18, 1.9, -18.5), Size = Vector3.new(2, 1.4, 1.1), Color = Color3.fromRGB(88, 58, 40), Material = Enum.Material.Wood, Name = "Radio" })
	label(P({ Pos = Vector3.new(-18, 1.9, -17.9), Size = Vector3.new(1.2, 0.7, 0.05), Color = Color3.fromRGB(200, 190, 160), CanCollide = false }), "AM", Color3.fromRGB(40, 36, 30))
	local candelabra = P({ Pos = Vector3.new(18, 4.9, -12), Size = Vector3.new(1, 1, 1), Color = Color3.fromRGB(195, 165, 70), Material = Enum.Material.Metal, Name = "Candelabra" })
	for _, cx in ipairs({ -0.3, 0.3 }) do
		P({ Pos = Vector3.new(18 + cx, 5.8, -12), Size = Vector3.new(0.16, 0.8, 0.16), Color = Color3.fromRGB(255, 220, 140), Material = Enum.Material.Neon, CanCollide = false })
	end
	local lantern = P({ Pos = Vector3.new(31, 8.5, 12), Size = Vector3.new(0.9, 1.4, 0.9), Color = Color3.fromRGB(255, 200, 120), Material = Enum.Material.Neon, Name = "Lantern" })
	light(lantern, 0.7, 14)

	-- ============ SECURITY ROOM (front-left of lobby) ============
	P({ Pos = Vector3.new(-27, 0.2, 12.5), Size = Vector3.new(12, 0.2, 11), Color = Color3.fromRGB(58, 58, 62), Material = Enum.Material.Concrete, CanCollide = false })
	P({ Pos = Vector3.new(-27, 5, 7.5), Size = Vector3.new(13, 10, 0.5), Color = Color3.fromRGB(72, 72, 78), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(-33.5, 5, 12.5), Size = Vector3.new(0.5, 10, 11), Color = Color3.fromRGB(72, 72, 78), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(-27, 10, 12.5), Size = Vector3.new(13, 0.5, 11), Color = Color3.fromRGB(50, 50, 54) })
	P({ Pos = Vector3.new(-20.5, 5, 9.25), Size = Vector3.new(0.5, 10, 6.5), Color = Color3.fromRGB(72, 72, 78), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(-20.5, 8.75, 14.25), Size = Vector3.new(0.5, 2.5, 1.5), Color = Color3.fromRGB(72, 72, 78), Material = Enum.Material.Concrete })
	local secDoor = P({ Pos = Vector3.new(-20.5, 3.75, 14.25), Size = Vector3.new(0.4, 7.5, 3), Color = Color3.fromRGB(78, 78, 86), Material = Enum.Material.Metal, Name = "SecurityDoor" })
	label(secDoor, "SECURITY", Color3.fromRGB(120, 255, 140), Enum.NormalId.Right)
	local secPrompt = makePrompt(secDoor, "Open / Close", 0, 9)
	local secLight = P({ Pos = Vector3.new(-27, 9.4, 12.5), Size = Vector3.new(3, 0.2, 1.4), Color = Color3.fromRGB(255, 240, 210), Material = Enum.Material.Neon, CanCollide = false })
	light(secLight, 1.2, 18)
	local camNames = { "CAM 01 ENTRANCE", "CAM 02 PARKING", "CAM 03 CORRIDOR", "CAM 04 LOBBY" }
	for i = 1, 4 do
		local mon = P({ Pos = Vector3.new(-31.5 + ((i - 1) % 2) * 4, 7 + math.floor((i - 1) / 2) * -3, 8), Size = Vector3.new(3.4, 2.5, 0.4), Color = Color3.fromRGB(18, 18, 22), Name = "Monitor" .. i })
		label(mon, camNames[i], Color3.fromRGB(120, 255, 140))
	end
	P({ Pos = Vector3.new(-27, 1.1, 9.6), Size = Vector3.new(7, 2.2, 2.6), Color = Color3.fromRGB(44, 44, 50), Material = Enum.Material.Metal, Name = "SecurityDesk" })
	P({ Pos = Vector3.new(-27, 2.9, 9.6), Size = Vector3.new(7, 0.3, 3), Color = Color3.fromRGB(60, 60, 66), Material = Enum.Material.Metal })
	Map.SecurityDoor = secDoor
	Map.SecurityDoorOpen = false
	Map.SecurityPrompt = secPrompt

	-- ============ GUEST ROOMS 101-106 (z -46..-32) ============
	for i, num in ipairs(ctx.Config.RoomNumbers) do
		local x = -25 + (i - 1) * 10
		P({ Pos = Vector3.new(x, 0.18, -39.5), Size = Vector3.new(10, 0.1, 14), Color = roomFloor, Material = Enum.Material.WoodPlanks, CanCollide = false, Name = "RoomFloor" .. num })
		P({ Pos = Vector3.new(x, 0.25, -36.5), Size = Vector3.new(8, 0.08, 5), Color = Color3.fromRGB(80, 44, 40), Material = Enum.Material.Fabric, CanCollide = false, Name = "RoomRug" .. num })
		P({ Pos = Vector3.new(x, 5, -46.5), Size = Vector3.new(10, 10, 0.5), Color = wallWood, Material = Enum.Material.WoodPlanks })
		P({ Pos = Vector3.new(x - 5, 5, -39.5), Size = Vector3.new(0.5, 10, 14), Color = wallWood, Material = Enum.Material.WoodPlanks })
		P({ Pos = Vector3.new(x + 5, 5, -39.5), Size = Vector3.new(0.5, 10, 14), Color = wallWood, Material = Enum.Material.WoodPlanks })
		P({ Pos = Vector3.new(x, 10, -39.5), Size = Vector3.new(10, 0.5, 14), Color = Color3.fromRGB(56, 40, 30) })
		-- bed + headboard + blanket + pillow
		P({ Pos = Vector3.new(x - 2.6, 1.1, -43.5), Size = Vector3.new(0.4, 2.6, 5.4), Color = woodDark, Material = Enum.Material.Wood, Name = "Headboard" .. num })
		P({ Pos = Vector3.new(x - 2.6, 0.9, -43.2), Size = Vector3.new(4.4, 1.2, 7.6), Color = Color3.fromRGB(128, 38, 38), Material = Enum.Material.Fabric, Name = "Bed" .. num })
		P({ Pos = Vector3.new(x - 2.6, 1.6, -42.4), Size = Vector3.new(4.2, 0.35, 4.6), Color = Color3.fromRGB(70, 52, 66), Material = Enum.Material.Fabric, CanCollide = false })
		P({ Pos = Vector3.new(x - 2.6, 1.75, -45.4), Size = Vector3.new(2.4, 0.55, 1.6), Color = Color3.fromRGB(232, 228, 218), Name = "Pillow" .. num })
		-- nightstand + lamp
		P({ Pos = Vector3.new(x + 0.6, 0.85, -45.4), Size = Vector3.new(1.6, 1.5, 1.6), Color = woodDark, Material = Enum.Material.Wood, Name = "Nightstand" .. num })
		P({ Pos = Vector3.new(x + 0.6, 1.9, -45.4), Size = Vector3.new(0.14, 0.7, 0.14), Color = Color3.fromRGB(50, 50, 54), Material = Enum.Material.Metal, CanCollide = false })
		local shade = P({ Pos = Vector3.new(x + 0.6, 2.5, -45.4), Size = Vector3.new(1, 0.8, 1), Color = Color3.fromRGB(255, 214, 150), Material = Enum.Material.Neon, Name = "RoomLamp" .. num })
		light(shade, 0.9, 14)
		-- dresser + TV
		P({ Pos = Vector3.new(x + 3.4, 1, -42), Size = Vector3.new(1.6, 2, 4), Color = woodDark, Material = Enum.Material.Wood, Name = "Dresser" .. num })
		P({ Pos = Vector3.new(x + 3.4, 2.9, -42), Size = Vector3.new(1.2, 1.7, 2.6), Color = Color3.fromRGB(24, 24, 28), Name = "RoomTV" .. num })
		-- bathroom door + frame
		P({ Pos = Vector3.new(x - 4.6, 3.5, -46.2), Size = Vector3.new(0.3, 7, 3), Color = Color3.fromRGB(96, 70, 48), Name = "BathroomDoor" .. num })
		P({ Pos = Vector3.new(x - 4.6, 7.2, -46.2), Size = Vector3.new(0.4, 0.6, 3.4), Color = woodDark, CanCollide = false })
		-- window + curtains
		P({ Pos = Vector3.new(x, 5.5, -46.3), Size = Vector3.new(3.4, 3, 0.2), Color = Color3.fromRGB(110, 135, 155), Material = Enum.Material.Glass, Transparency = 0.6, CanCollide = false })
		P({ Pos = Vector3.new(x - 2.1, 5.5, -46.2), Size = Vector3.new(0.8, 4.2, 0.25), Color = Color3.fromRGB(70, 30, 34), Material = Enum.Material.Fabric, CanCollide = false })
		P({ Pos = Vector3.new(x + 2.1, 5.5, -46.2), Size = Vector3.new(0.8, 4.2, 0.25), Color = Color3.fromRGB(70, 30, 34), Material = Enum.Material.Fabric, CanCollide = false })
		-- chair (barricade prop)
		local chair = P({ Pos = Vector3.new(x + 2, 0.9, -36), Size = Vector3.new(1.4, 1.8, 1.4), Color = Color3.fromRGB(110, 75, 50), Material = Enum.Material.Wood, Name = "Chair" .. num })
		local barPrompt = makePrompt(chair, "Barricade door (+5s)", 0, 9)
		-- ceiling fixture
		local cl = P({ Pos = Vector3.new(x, 9.6, -39.5), Size = Vector3.new(3.4, 0.25, 1.4), Color = Color3.fromRGB(255, 240, 210), Material = Enum.Material.Neon, Name = "RoomLight" .. num })
		local clLight = light(cl, 1.0, 16)
		-- wall art
		P({ Pos = Vector3.new(x, 6.5, -32.75), Size = Vector3.new(2, 2.6, 0.2), Color = Color3.fromRGB(70, 52, 36), CanCollide = false })
		-- door (5 wide gap)
		local door = P({ Pos = Vector3.new(x, 3.5, -32.5), Size = Vector3.new(5, 7, 0.4), Color = Color3.fromRGB(118, 84, 54), Material = Enum.Material.Wood, Name = "Door" .. num })
		label(door, tostring(num), Color3.fromRGB(238, 224, 180), Enum.NormalId.Front)
		P({ Parent = door, Pos = Vector3.new(2, 0, 0.3), Size = Vector3.new(0.22, 0.22, 0.8), Color = Color3.fromRGB(210, 180, 90), Material = Enum.Material.Metal, CanCollide = false })
		local dPrompt = makePrompt(door, "Close", 0, 9)
		Map.Doors[num] = {
			part = door, prompt = dPrompt, room = num,
			closed = door.CFrame, isOpen = true, locked = false, barricaded = false,
			openCF = door.CFrame * CFrame.new(-2.5, 0, 0) * CFrame.Angles(0, math.rad(-100), 0) * CFrame.new(2.5, 0, 0),
			light = cl, lightObj = clLight, lamp = shade,
			knock = nil, breaking = false, chair = chair, barPrompt = barPrompt,
		}
		Map.Rooms[num] = { num = num, state = "clean", occupant = nil }
		Map.RoomLights[num] = cl
		barPrompt.Enabled = false
		door.CFrame = Map.Doors[num].openCF
	end

	-- ============ NEON MOTEL SIGN ============
	P({ Pos = Vector3.new(-48, 8, 66), Size = Vector3.new(2, 16, 2), Color = Color3.fromRGB(56, 56, 60), Material = Enum.Material.Metal, Name = "SignPole" })
	P({ Pos = Vector3.new(-40, 5, 66), Size = Vector3.new(2, 10, 2), Color = Color3.fromRGB(56, 56, 60), Material = Enum.Material.Metal, Name = "SignPole2" })
	local signBoard = P({ Pos = Vector3.new(-44, 20, 66), Size = Vector3.new(26, 9, 1.2), Color = Color3.fromRGB(24, 20, 24), Name = "SignBoard" })
	local motelText = label(signBoard, "MOTEL", Color3.fromRGB(255, 42, 42))
	local numberBoard = P({ Pos = Vector3.new(-44, 12.5, 66), Size = Vector3.new(9, 6, 1.2), Color = Color3.fromRGB(24, 20, 24), Name = "NumberBoard" })
	local numberText = label(numberBoard, "9", Color3.fromRGB(60, 255, 95))
	-- neon tube border
	for _, def in ipairs({
		{ Vector3.new(-44, 24.8, 66), Vector3.new(27, 0.4, 1.5) },
		{ Vector3.new(-44, 15.2, 66), Vector3.new(27, 0.4, 1.5) },
		{ Vector3.new(-57.7, 20, 66), Vector3.new(0.4, 10, 1.5) },
		{ Vector3.new(-30.3, 20, 66), Vector3.new(0.4, 10, 1.5) },
	}) do
		local tube = P({ Pos = def[1], Size = def[2], Color = Color3.fromRGB(255, 42, 42), Material = Enum.Material.Neon, Name = "SignNeon" .. #Map.SignNeons + 1 })
		table.insert(Map.SignNeons, tube)
	end
	local vacancy = P({ Pos = Vector3.new(-44, 17, 64.6), Size = Vector3.new(11, 2.8, 0.4), Color = Color3.fromRGB(18, 18, 20), Name = "VacancyBoard" })
	local vacancyText = label(vacancy, "VACANCY", Color3.fromRGB(70, 255, 110))
	light(signBoard, 2.5, 55, Color3.fromRGB(255, 60, 60))
	Map.SignParts = { signBoard, numberBoard, vacancy }
	Map.SignTexts = { motel = motelText, number = numberText, vacancy = vacancyText }

	-- STREETLAMPS
	for _, lx in ipairs({ 18, -18 }) do
		P({ Pos = Vector3.new(lx, 7, 74), Size = Vector3.new(0.9, 14, 0.9), Color = Color3.fromRGB(48, 48, 52), Material = Enum.Material.Metal, Name = "LampPost" })
		local head = P({ Pos = Vector3.new(lx + 1.5, 14.2, 74), Size = Vector3.new(3.4, 0.5, 1.8), Color = Color3.fromRGB(255, 235, 180), Material = Enum.Material.Neon, Name = "StreetLamp" })
		light(head, 1.7, 38)
	end

	-- TREES + BUSHES
	for _, t in ipairs({ { -62, 30, 1.2 }, { -66, 54 }, { 60, 28, 1.1 }, { 64, 52, 1.3 }, { -72, 72, 1.4 }, { 72, 72 }, { -54, 8 }, { 54, 6, 1.2 }, { -70, 18 }, { 70, 14, 1.1 }, { -58, 88, 1.3 }, { 58, 88 } }) do
		tree(t[1], t[2], t[3])
	end
	for _, b in ipairs({ { -40, 22 }, { 40, 22 }, { -36, 70 }, { 36, 70 }, { -52, 40 }, { 52, 40 } }) do
		bush(b[1], b[2])
	end

	-- ============ SECURITY CAMERAS ============
	local camDefs = {
		{ pos = Vector3.new(0, 11.5, 15), look = Vector3.new(0, 2.5, 22) },
		{ pos = Vector3.new(0, 17, 52), look = Vector3.new(0, 1.5, 36) },
		{ pos = Vector3.new(29, 9, -26), look = Vector3.new(-30, 2, -26) },
		{ pos = Vector3.new(-29, 11.5, -14), look = Vector3.new(12, 2.5, -2) },
	}
	for i, def in ipairs(camDefs) do
		local cam = P({ Pos = def.pos, Size = Vector3.new(1, 1, 1), Transparency = 1, CanCollide = false, Name = "Cam" .. i })
		cam.CFrame = CFrame.lookAt(def.pos, def.look)
		P({ Pos = def.pos + Vector3.new(0, 0.9, 0), Size = Vector3.new(0.8, 0.8, 1.6), Color = Color3.fromRGB(38, 38, 42), Material = Enum.Material.Metal, Name = "CamBody" .. i })
		Map.Cameras[i] = { part = cam, name = "CAM 0" .. i }
	end

	-- RAIN + DUST EMITTER HOLDERS
	local rainPart = P({ Pos = Vector3.new(0, 60, 30), Size = Vector3.new(110, 1, 110), Transparency = 1, CanCollide = false, Name = "RainEmitter" })
	Map.RainPart = rainPart
	local dustPart = P({ Pos = Vector3.new(0, 10, -2), Size = Vector3.new(24, 1, 24), Transparency = 1, CanCollide = false, Name = "DustEmitter" })
	Map.DustPart = dustPart

	-- SPAWN
	local spawnLoc = Instance.new("SpawnLocation")
	spawnLoc.Anchored = true
	spawnLoc.Size = Vector3.new(10, 0.4, 10)
	spawnLoc.CFrame = CFrame.new(0, 0.25, 52)
	spawnLoc.Color = Color3.fromRGB(66, 66, 70)
	spawnLoc.Material = Enum.Material.Concrete
	spawnLoc.Neutral = true
	spawnLoc.Name = "SpawnLocation"
	spawnLoc.Parent = map

	return Map
end

return MapBuilder
