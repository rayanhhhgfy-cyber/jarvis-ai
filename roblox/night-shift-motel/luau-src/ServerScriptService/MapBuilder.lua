-- MapBuilder: builds the entire motel from Parts at runtime.
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

local function label(part, text, textColor, size, face)
	local sg = Instance.new("SurfaceGui")
	sg.Face = face or Enum.NormalId.Front
	sg.CanvasSize = Vector2.new(400, 200)
	sg.Parent = part
	local tl = Instance.new("TextLabel")
	tl.Size = UDim2.new(1, 0, 1, 0)
	tl.BackgroundTransparency = 1
	tl.Text = text
	tl.TextColor3 = textColor or Color3.fromRGB(255, 60, 60)
	tl.TextScaled = true
	tl.Font = Enum.Font.Arcade
	tl.Parent = sg
	return tl
end

local function light(part, brightness, range, color)
	local pl = Instance.new("PointLight")
	pl.Brightness = brightness or 1.2
	pl.Range = range or 18
	pl.Color = color or Color3.fromRGB(255, 230, 190)
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

local function tree(x, z)
	P({ Pos = Vector3.new(x, 3, z), Size = Vector3.new(1.6, 6, 1.6), Color = Color3.fromRGB(74, 54, 40), Material = Enum.Material.Wood })
	P({ Pos = Vector3.new(x, 7, z), Size = Vector3.new(6, 3.4, 6), Color = Color3.fromRGB(34, 70, 44), Material = Enum.Material.Grass })
	P({ Pos = Vector3.new(x, 10, z), Size = Vector3.new(4.4, 3, 4.4), Color = Color3.fromRGB(30, 62, 40), Material = Enum.Material.Grass })
	P({ Pos = Vector3.new(x, 12.6, z), Size = Vector3.new(2.8, 2.6, 2.8), Color = Color3.fromRGB(26, 55, 36), Material = Enum.Material.Grass })
end

local Map = {}
Map.Desks = {}
Map.Doors = {}
Map.RoomLights = {}
Map.Rooms = {}
Map.Cameras = {}

function MapBuilder.Build(ctx)
	map = Instance.new("Folder")
	map.Name = "Map"
	map.Parent = workspace

	local asphalt = Color3.fromRGB(38, 38, 42)
	local wood = Color3.fromRGB(96, 68, 48)
	local wallWood = Color3.fromRGB(112, 84, 58)
	local brick = Color3.fromRGB(96, 62, 52)

	-- GROUND / LOT / ROAD
	P({ Pos = Vector3.new(0, -0.5, 10), Size = Vector3.new(220, 1, 200), Color = asphalt, Material = Enum.Material.Asphalt, Reflectance = 0.12, Name = "Lot" })
	P({ Pos = Vector3.new(0, 0.06, 84), Size = Vector3.new(240, 0.4, 26), Color = Color3.fromRGB(28, 28, 30), Material = Enum.Material.Asphalt, Name = "Road" })
	for i = -5, 5 do
		P({ Pos = Vector3.new(i * 20, 0.3, 84), Size = Vector3.new(6, 0.05, 0.8), Color = Color3.fromRGB(220, 200, 80), CanCollide = false })
	end
	P({ Pos = Vector3.new(0, 0.12, 26), Size = Vector3.new(70, 0.3, 10), Color = Color3.fromRGB(130, 128, 124), Material = Enum.Material.Concrete, Name = "Sidewalk" })
	P({ Pos = Vector3.new(0, 0.14, 36), Size = Vector3.new(8, 0.3, 14), Color = Color3.fromRGB(130, 128, 124), Material = Enum.Material.Concrete, Name = "Walkway" })
	for i = -2, 2 do
		P({ Pos = Vector3.new(i * 12, 0.2, 44), Size = Vector3.new(0.5, 0.1, 14), Color = Color3.fromRGB(230, 230, 230), CanCollide = false })
		P({ Pos = Vector3.new(i * 12, 0.2, 62), Size = Vector3.new(0.5, 0.1, 14), Color = Color3.fromRGB(230, 230, 230), CanCollide = false })
	end

	-- LOBBY FLOOR (checkered)
	for ix = 0, 15 do
		for iz = 0, 9 do
			local dark = (ix + iz) % 2 == 0
			P({
				Pos = Vector3.new(-30 + ix * 4, 0.1, -20 + iz * 4),
				Size = Vector3.new(4, 0.2, 4),
				Color = dark and Color3.fromRGB(24, 24, 26) or Color3.fromRGB(226, 224, 218),
				Material = Enum.Material.Marble,
			})
		end
	end

	-- LOBBY WALLS (interior x -32..32, z -22..18)
	P({ Pos = Vector3.new(-17, 6, -22.5), Size = Vector3.new(30, 12, 1), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(17, 6, -22.5), Size = Vector3.new(30, 12, 1), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(0, 10, -22.5), Size = Vector3.new(6, 4, 1), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(-13.75, 6, 18.5), Size = Vector3.new(19.5, 12, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(13.75, 6, 18.5), Size = Vector3.new(19.5, 12, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(0, 10, 18.5), Size = Vector3.new(8, 4, 1), Color = brick, Material = Enum.Material.Brick })
	P({ Pos = Vector3.new(-32.5, 6, -2), Size = Vector3.new(1, 12, 42), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(32.5, 6, -2), Size = Vector3.new(1, 12, 42), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(0, 12.5, -2), Size = Vector3.new(66, 0.5, 42), Color = Color3.fromRGB(70, 52, 38), Material = Enum.Material.WoodPlanks })
	-- windows (glass, see rain through)
	P({ Pos = Vector3.new(-13.75, 6, 18.1), Size = Vector3.new(17, 6, 0.2), Color = Color3.fromRGB(140, 170, 190), Material = Enum.Material.Glass, Transparency = 0.65, CanCollide = false })
	P({ Pos = Vector3.new(13.75, 6, 18.1), Size = Vector3.new(17, 6, 0.2), Color = Color3.fromRGB(140, 170, 190), Material = Enum.Material.Glass, Transparency = 0.65, CanCollide = false })

	-- CEILING LIGHTS
	local lightSpots = { Vector3.new(-16, 11.8, -10), Vector3.new(16, 11.8, -10), Vector3.new(-16, 11.8, 8), Vector3.new(16, 11.8, 8) }
	for i, pos in ipairs(lightSpots) do
		local lp = P({ Pos = pos, Size = Vector3.new(6, 0.3, 2), Color = Color3.fromRGB(255, 240, 210), Material = Enum.Material.Neon, Name = "LobbyLight" .. i })
		light(lp, 1.4, 26)
		table.insert(Map, lp)
	end
	Map.LobbyLights = {}
	for _, child in ipairs(map:GetChildren()) do
		if child.Name:sub(1, 10) == "LobbyLight" then table.insert(Map.LobbyLights, child) end
	end

	-- FRONT COUNTER (space for 3 desks)
	P({ Pos = Vector3.new(0, 2, -14), Size = Vector3.new(30, 4, 3), Color = wood, Material = Enum.Material.WoodPlanks, Name = "Counter" })
	P({ Pos = Vector3.new(0, 4.2, -14), Size = Vector3.new(31, 0.4, 4.4), Color = Color3.fromRGB(70, 50, 36), Material = Enum.Material.Wood, Name = "CounterTop" })

	-- DESKS 1-3 (2 and 3 hidden until bought)
	for slot = 1, 3 do
		local x = (slot - 2) * 10
		local furniture = Instance.new("Folder")
		furniture.Name = "DeskFurniture" .. slot
		furniture.Parent = map
		local bellBase = P({ Parent = furniture, Pos = Vector3.new(x + 1.2, 4.7, -13.2), Size = Vector3.new(0.8, 0.2, 0.8), Color = Color3.fromRGB(190, 160, 60), Material = Enum.Material.Metal })
		local bellDome = P({ Parent = furniture, Class = "Part", Pos = Vector3.new(x + 1.2, 4.95, -13.2), Size = Vector3.new(0.55, 0.35, 0.55), Shape = Enum.PartType.Ball, Color = Color3.fromRGB(220, 190, 80), Material = Enum.Material.Metal, Name = "Bell" .. slot })
		P({ Parent = furniture, Pos = Vector3.new(x - 1.4, 4.55, -13.4), Size = Vector3.new(1.6, 0.25, 1.1), Color = Color3.fromRGB(210, 205, 190), Name = "Register" .. slot })
		local lampPole = P({ Parent = furniture, Pos = Vector3.new(x - 2.6, 5, -13.4), Size = Vector3.new(0.15, 1.4, 0.15), Color = Color3.fromRGB(60, 60, 60), Material = Enum.Material.Metal })
		local lampHead = P({ Parent = furniture, Pos = Vector3.new(x - 2.6, 5.8, -13.4), Size = Vector3.new(0.9, 0.35, 0.9), Color = Color3.fromRGB(120, 200, 120), Material = Enum.Material.Neon, Name = "DeskLamp" .. slot })
		light(lampHead, 0.8, 10)
		local seat = Instance.new("Seat")
		seat.Anchored = true
		seat.Size = Vector3.new(2.4, 0.4, 2.4)
		seat.CFrame = CFrame.new(x, 0.5, -17.5)
		seat.Color = Color3.fromRGB(120, 40, 40)
		seat.Material = Enum.Material.Fabric
		seat.Name = "DeskSeat" .. slot
		seat.Parent = furniture
		local sitPrompt = makePrompt(seat, "Sit", 0, 8)
		sitPrompt.ObjectText = "Desk " .. slot
		local ding = Instance.new("Sound")
		ding.SoundId = "rbxasset://sounds/electronicpingshort.wav"
		ding.Volume = 1
		ding.Parent = bellDome
		Map.Desks[slot] = { seat = seat, prompt = sitPrompt, bell = ding, pos = Vector3.new(x, 3, -11), bought = (slot == 1), furniture = furniture }
		if slot > 1 then
			for _, d in ipairs(furniture:GetDescendants()) do
				if d:IsA("BasePart") then d.Transparency = 1 end
				if d:IsA("Seat") then d.CanCollide = false end
				if d:IsA("ProximityPrompt") then d.Enabled = false end
			end
			seat.CanCollide = false
		end
	end

	-- KEY BOARD behind counter
	local keyBoard = P({ Pos = Vector3.new(0, 7, -21.6), Size = Vector3.new(10, 4, 0.4), Color = Color3.fromRGB(80, 58, 40), Material = Enum.Material.Wood })
	for i = 1, 6 do
		P({ Parent = keyBoard, Pos = Vector3.new(-3.75 + (i - 1) * 1.5, 0, 0.4), Size = Vector3.new(0.6, 0.9, 0.15), Color = Color3.fromRGB(200, 180, 90), Material = Enum.Material.Metal })
		label(P({ Parent = keyBoard, Pos = Vector3.new(-3.75 + (i - 1) * 1.5, -0.9, 0.4), Size = Vector3.new(0.9, 0.5, 0.1), Color = Color3.fromRGB(40, 30, 20), CanCollide = false }), tostring(100 + i), Color3.fromRGB(240, 230, 180), nil, Enum.NormalId.Front)
	end

	-- COFFEE CORNER
	local coffeeCounter = P({ Pos = Vector3.new(28, 1.75, -16), Size = Vector3.new(6, 3.5, 5), Color = wood, Material = Enum.Material.WoodPlanks, Name = "CoffeeCounter" })
	P({ Pos = Vector3.new(28, 3.7, -16), Size = Vector3.new(6.5, 0.4, 5.5), Color = Color3.fromRGB(70, 50, 36), Material = Enum.Material.Wood })
	local coffeeMachine = P({ Pos = Vector3.new(26.6, 5, -16), Size = Vector3.new(1.8, 2.4, 1.6), Color = Color3.fromRGB(50, 50, 55), Material = Enum.Material.Metal, Name = "CoffeeMachine" })
	label(coffeeMachine, "COFFEE\n$5", Color3.fromRGB(255, 120, 60))
	local buyPrompt = makePrompt(coffeeMachine, "Buy coffee (+" .. ctx.Config.CoffeeSanity .. " sanity)", 0, 9)
	buyPrompt.ObjectText = "Coffee corner"
	local brewSound = Instance.new("Sound")
	brewSound.SoundId = "rbxasset://sounds/swoosh.wav"
	brewSound.Volume = 0.4
	brewSound.Looped = true
	brewSound.Parent = coffeeMachine
	local warmer = P({ Pos = Vector3.new(29.4, 5, -16), Size = Vector3.new(1.8, 2.2, 1.6), Color = Color3.fromRGB(120, 70, 40), Material = Enum.Material.Metal, Name = "CoffeeWarmer" })
	label(warmer, "FREE\nPOT", Color3.fromRGB(255, 200, 90))
	local drinkPrompt = makePrompt(warmer, "Drink free pot (+" .. ctx.Config.WarmerSanity .. " sanity)", 0, 9)
	drinkPrompt.ObjectText = "Coffee warmer"
	drinkPrompt.Enabled = false
	for i = 1, 4 do
		P({ Pos = Vector3.new(30.6, 4 + i * 0.35, -14.4), Size = Vector3.new(0.9, 0.3, 0.9), Shape = Enum.PartType.Cylinder, Color = Color3.fromRGB(235, 235, 230) })
	end
	Map.CoffeeMachine = coffeeMachine
	Map.CoffeeBuyPrompt = buyPrompt
	Map.Warmer = warmer
	Map.WarmerDrinkPrompt = drinkPrompt
	Map.BrewSound = brewSound

	-- LOBBY DRESSING
	local vending = P({ Pos = Vector3.new(-29, 3, 14), Size = Vector3.new(4, 6, 2.4), Color = Color3.fromRGB(150, 30, 40), Material = Enum.Material.Metal, Name = "VendingMachine" })
	label(vending, "DRINKS", Color3.fromRGB(120, 255, 160))
	local ice = P({ Pos = Vector3.new(-29, 2, 8), Size = Vector3.new(3, 4, 2.2), Color = Color3.fromRGB(190, 195, 200), Material = Enum.Material.Metal, Name = "IceMachine" })
	label(ice, "ICE", Color3.fromRGB(60, 90, 200))
	local tv = P({ Pos = Vector3.new(0, 8.5, -21.4), Size = Vector3.new(4, 2.6, 0.5), Color = Color3.fromRGB(30, 30, 32), Name = "WallTV" })
	label(tv, "STATIC", Color3.fromRGB(150, 150, 150))
	local phone = P({ Pos = Vector3.new(-26, 6, -21.6), Size = Vector3.new(1.2, 1.6, 0.5), Color = Color3.fromRGB(40, 40, 44), Material = Enum.Material.Metal, Name = "WallPhone" })
	P({ Pos = Vector3.new(-10, 1, 2), Size = Vector3.new(5, 1.2, 5), Color = Color3.fromRGB(90, 60, 44), Material = Enum.Material.Wood, Name = "LobbyTable" })
	for _, cx in ipairs({ -12.5, -7.5 }) do
		P({ Pos = Vector3.new(cx, 1.1, 2), Size = Vector3.new(1.6, 2.2, 1.6), Color = Color3.fromRGB(120, 40, 40), Material = Enum.Material.Fabric, Name = "LobbyChair" })
	end
	P({ Pos = Vector3.new(10, 0.6, 4), Size = Vector3.new(2, 1.2, 3), Color = Color3.fromRGB(120, 95, 60), Material = Enum.Material.Fabric, Name = "Suitcase" })
	P({ Pos = Vector3.new(24, 6.5, -21.4), Size = Vector3.new(1.6, 1.6, 0.4), Color = Color3.fromRGB(60, 50, 40), Name = "WallClock" })
	label(P({ Pos = Vector3.new(24, 6.5, -21.15), Size = Vector3.new(1.3, 1.3, 0.1), Color = Color3.fromRGB(235, 230, 220), CanCollide = false }), "12", Color3.fromRGB(30, 30, 30))
	for _, px in ipairs({ -20, 20 }) do
		local frame = P({ Pos = Vector3.new(px, 7, -21.6), Size = Vector3.new(2.4, 3, 0.3), Color = Color3.fromRGB(70, 52, 38), Material = Enum.Material.Wood, Name = "Portrait" })
		label(frame, ":)", Color3.fromRGB(200, 190, 170))
	end
	local houseRules = P({ Pos = Vector3.new(-24, 7, -21.6), Size = Vector3.new(2.2, 3, 0.3), Color = Color3.fromRGB(226, 220, 200), Name = "HouseRules" })
	label(houseRules, "HOUSE\nRULES", Color3.fromRGB(40, 40, 40))
	local lantern = P({ Pos = Vector3.new(30.5, 8, 12), Size = Vector3.new(0.8, 1.2, 0.8), Color = Color3.fromRGB(255, 200, 120), Material = Enum.Material.Neon, Name = "Lantern" })
	light(lantern, 0.7, 12)
	local candelabra = P({ Pos = Vector3.new(18, 4.9, -13.4), Size = Vector3.new(0.9, 0.9, 0.9), Color = Color3.fromRGB(190, 160, 60), Material = Enum.Material.Metal, Name = "Candelabra" })
	local radio = P({ Pos = Vector3.new(-18, 1.6, -20.5), Size = Vector3.new(1.8, 1.2, 1), Color = Color3.fromRGB(90, 60, 40), Material = Enum.Material.Wood, Name = "Radio" })
	local typewriter = P({ Pos = Vector3.new(4.5, 4.6, -14), Size = Vector3.new(1.4, 0.6, 1), Color = Color3.fromRGB(40, 40, 44), Material = Enum.Material.Metal, Name = "Typewriter" })

	-- SECURITY ROOM (front-left corner of lobby)
	P({ Pos = Vector3.new(-26.5, 0.1, 12.5), Size = Vector3.new(10, 0.3, 10), Color = Color3.fromRGB(60, 60, 64), Material = Enum.Material.Concrete, Name = "SecurityFloor" })
	P({ Pos = Vector3.new(-24.5, 5, 7.5), Size = Vector3.new(13, 10, 0.5), Color = Color3.fromRGB(70, 70, 76), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(-31.75, 5, 12.5), Size = Vector3.new(0.5, 10, 10), Color = Color3.fromRGB(70, 70, 76), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(-26.5, 10, 12.5), Size = Vector3.new(10, 0.5, 10), Color = Color3.fromRGB(50, 50, 54) })
	P({ Pos = Vector3.new(-21.75, 5, 10), Size = Vector3.new(0.5, 10, 4), Color = Color3.fromRGB(70, 70, 76), Material = Enum.Material.Concrete })
	P({ Pos = Vector3.new(-21.75, 8.5, 14.25), Size = Vector3.new(0.5, 3, 1.5), Color = Color3.fromRGB(70, 70, 76), Material = Enum.Material.Concrete })
	local secDoor = P({ Pos = Vector3.new(-21.75, 3.5, 14.25), Size = Vector3.new(0.4, 7, 3), Color = Color3.fromRGB(80, 80, 88), Material = Enum.Material.Metal, Name = "SecurityDoor" })
	local secPrompt = makePrompt(secDoor, "Open / Close", 0, 8)
	local camNames = { "CAM 01 ENTRANCE", "CAM 02 PARKING", "CAM 03 CORRIDOR", "CAM 04 LOBBY" }
	for i = 1, 4 do
		local mon = P({ Parent = secDoor.Parent, Pos = Vector3.new(-29.5 + ((i - 1) % 2) * 3.4, 6.5 + math.floor((i - 1) / 2) * -3.2, 8), Size = Vector3.new(3, 2.4, 0.4), Color = Color3.fromRGB(20, 20, 24), Name = "Monitor" .. i })
		label(mon, camNames[i], Color3.fromRGB(120, 255, 140))
	end
	Map.SecurityDoor = secDoor
	Map.SecurityDoorOpen = false
	Map.SecurityPrompt = secPrompt

	-- CORRIDOR
	P({ Pos = Vector3.new(0, 0.1, -28), Size = Vector3.new(64, 0.2, 12), Color = Color3.fromRGB(88, 62, 44), Material = Enum.Material.WoodPlanks, Name = "CorridorFloor" })
	P({ Pos = Vector3.new(0, 5, -33.75), Size = Vector3.new(64, 10, 0.5), Color = wallWood, Material = Enum.Material.WoodPlanks })
	for _, wx in ipairs({ -27, -17, -7, 3, 13, 23 }) do
		P({ Pos = Vector3.new(wx, 5, -33.75), Size = Vector3.new(4, 10, 0.5), Color = wallWood, Material = Enum.Material.WoodPlanks })
	end
	P({ Pos = Vector3.new(-32.5, 5, -28), Size = Vector3.new(1, 10, 12), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(32.5, 5, -28), Size = Vector3.new(1, 10, 12), Color = wallWood, Material = Enum.Material.WoodPlanks })
	P({ Pos = Vector3.new(0, 10.2, -28), Size = Vector3.new(64, 0.4, 12), Color = Color3.fromRGB(60, 44, 32) })
	local corridorLight = P({ Pos = Vector3.new(0, 9.8, -28), Size = Vector3.new(40, 0.3, 1.6), Color = Color3.fromRGB(255, 240, 210), Material = Enum.Material.Neon, Name = "CorridorLight" })
	light(corridorLight, 1.1, 30)
	Map.CorridorLight = corridorLight

	-- GUEST ROOMS 101-106
	for i, num in ipairs(ctx.Config.RoomNumbers) do
		local x = -25 + (i - 1) * 10
		P({ Pos = Vector3.new(x, 0.1, -40.5), Size = Vector3.new(10, 0.2, 12), Color = Color3.fromRGB(96, 70, 50), Material = Enum.Material.WoodPlanks, Name = "RoomFloor" .. num })
		P({ Pos = Vector3.new(x, 5, -46.75), Size = Vector3.new(10, 10, 0.5), Color = wallWood, Material = Enum.Material.WoodPlanks })
		P({ Pos = Vector3.new(x - 5, 5, -40.5), Size = Vector3.new(0.5, 10, 12), Color = wallWood, Material = Enum.Material.WoodPlanks })
		P({ Pos = Vector3.new(x + 5, 5, -40.5), Size = Vector3.new(0.5, 10, 12), Color = wallWood, Material = Enum.Material.WoodPlanks })
		P({ Pos = Vector3.new(x, 10, -40.5), Size = Vector3.new(10, 0.5, 12), Color = Color3.fromRGB(60, 44, 32) })
		-- bed
		P({ Pos = Vector3.new(x - 2.5, 0.8, -43.5), Size = Vector3.new(4, 1, 7), Color = Color3.fromRGB(140, 40, 40), Material = Enum.Material.Fabric, Name = "Bed" .. num })
		P({ Pos = Vector3.new(x - 2.5, 1.6, -45.5), Size = Vector3.new(2.4, 0.6, 1.6), Color = Color3.fromRGB(235, 235, 225), Name = "Pillow" .. num })
		-- wall lamp + TV + bathroom door
		local lamp = P({ Pos = Vector3.new(x + 3.5, 5.5, -46.2), Size = Vector3.new(0.8, 0.8, 0.5), Color = Color3.fromRGB(255, 220, 150), Material = Enum.Material.Neon, Name = "RoomLamp" .. num })
		local rl = light(lamp, 0.9, 14)
		P({ Pos = Vector3.new(x, 6, -46.2), Size = Vector3.new(2.4, 1.6, 0.4), Color = Color3.fromRGB(25, 25, 28), Name = "RoomTV" .. num })
		P({ Pos = Vector3.new(x + 4.4, 3.5, -44), Size = Vector3.new(0.3, 7, 3), Color = Color3.fromRGB(90, 66, 46), Name = "BathroomDoor" .. num })
		-- chair (barricade prop)
		local chair = P({ Pos = Vector3.new(x + 2, 0.9, -38), Size = Vector3.new(1.4, 1.8, 1.4), Color = Color3.fromRGB(110, 75, 50), Material = Enum.Material.Wood, Name = "Chair" .. num })
		local barPrompt = makePrompt(chair, "Barricade door (+5s)", 0, 8)
		-- ceiling light
		local cl = P({ Pos = Vector3.new(x, 9.7, -40.5), Size = Vector3.new(3, 0.25, 1.4), Color = Color3.fromRGB(255, 240, 210), Material = Enum.Material.Neon, Name = "RoomLight" .. num })
		local clLight = light(cl, 1.0, 16)
		-- door
		local door = P({ Pos = Vector3.new(x, 3.5, -33.75), Size = Vector3.new(4, 7, 0.4), Color = Color3.fromRGB(122, 88, 58), Material = Enum.Material.Wood, Name = "Door" .. num })
		label(door, tostring(num), Color3.fromRGB(240, 230, 190), nil, Enum.NormalId.Front)
		P({ Parent = door, Pos = Vector3.new(1.6, 0, 0.3), Size = Vector3.new(0.2, 0.2, 0.7), Color = Color3.fromRGB(210, 180, 90), Material = Enum.Material.Metal, CanCollide = false })
		local dPrompt = makePrompt(door, "Close", 0, 8)
		Map.Doors[num] = {
			part = door, prompt = dPrompt, room = num,
			closed = door.CFrame, isOpen = true, locked = false, barricaded = false,
			openCF = door.CFrame * CFrame.new(-2, 0, 0) * CFrame.Angles(0, math.rad(-100), 0) * CFrame.new(2, 0, 0),
			light = cl, lightObj = clLight, lamp = lamp,
			knock = nil, breaking = false, chair = chair, barPrompt = barPrompt,
		}
		door.CFrame = Map.Doors[num].openCF
		Map.Rooms[num] = { num = num, state = "clean", occupant = nil }
		Map.RoomLights[num] = cl
		barPrompt.Enabled = false
	end

	-- EXTERIOR: neon MOTEL sign (built from Parts + SurfaceGui, as specified)
	local signPole = P({ Pos = Vector3.new(-45, 9, 62), Size = Vector3.new(2.4, 18, 2.4), Color = Color3.fromRGB(60, 60, 64), Material = Enum.Material.Metal, Name = "SignPole" })
	local signBoard = P({ Pos = Vector3.new(-45, 19, 62), Size = Vector3.new(20, 7, 1), Color = Color3.fromRGB(30, 26, 30), Name = "SignBoard" })
	local motelText = label(signBoard, "MOTEL", Color3.fromRGB(255, 40, 40))
	local numberBoard = P({ Pos = Vector3.new(-45, 12.5, 62), Size = Vector3.new(8, 5, 1), Color = Color3.fromRGB(30, 26, 30), Name = "NumberBoard" })
	local numberText = label(numberBoard, "9", Color3.fromRGB(60, 255, 90))
	P({ Pos = Vector3.new(-45, 22.8, 62), Size = Vector3.new(21, 0.5, 1.4), Color = Color3.fromRGB(255, 40, 40), Material = Enum.Material.Neon, Name = "SignNeonTop" })
	P({ Pos = Vector3.new(-45, 15.2, 62), Size = Vector3.new(21, 0.5, 1.4), Color = Color3.fromRGB(255, 40, 40), Material = Enum.Material.Neon, Name = "SignNeonMid" })
	local vacancy = P({ Pos = Vector3.new(-45, 16.5, 60.2), Size = Vector3.new(10, 2.6, 0.4), Color = Color3.fromRGB(20, 20, 22), Name = "VacancyBoard" })
	local vacancyText = label(vacancy, "VACANCY", Color3.fromRGB(60, 255, 90))
	light(signBoard, 2, 40, Color3.fromRGB(255, 60, 60))
	Map.SignParts = { signBoard, numberBoard, vacancy }
	Map.SignTexts = { motel = motelText, number = numberText, vacancy = vacancyText }
	Map.SignNeons = {}
	for _, child in ipairs(map:GetChildren()) do
		if child.Name:sub(1, 9) == "SignNeon" then table.insert(Map.SignNeons, child) end
	end

	-- STREETLAMP
	P({ Pos = Vector3.new(18, 7, 74), Size = Vector3.new(0.8, 14, 0.8), Color = Color3.fromRGB(50, 50, 54), Material = Enum.Material.Metal, Name = "LampPost" })
	local lampHead2 = P({ Pos = Vector3.new(18, 14.2, 74), Size = Vector3.new(2.4, 0.6, 1.6), Color = Color3.fromRGB(255, 235, 180), Material = Enum.Material.Neon, Name = "StreetLamp" })
	light(lampHead2, 1.6, 34)
	Map.StreetLamp = lampHead2

	-- TREES
	local treeSpots = { { -60, 30 }, { -64, 52 }, { 58, 28 }, { 62, 50 }, { -70, 70 }, { 70, 70 }, { -52, 8 }, { 52, 6 }, { -68, 20 }, { 68, 16 } }
	for _, t in ipairs(treeSpots) do
		tree(t[1], t[2])
	end

	-- SECURITY CAMERAS
	local camDefs = {
		{ name = "CAM 01 - ENTRANCE", pos = Vector3.new(0, 11, 12), look = Vector3.new(0, 3, 18) },
		{ name = "CAM 02 - PARKING", pos = Vector3.new(0, 14, 48), look = Vector3.new(0, 2, 38) },
		{ name = "CAM 03 - CORRIDOR", pos = Vector3.new(0, 9.5, -24), look = Vector3.new(0, 2, -30) },
		{ name = "CAM 04 - LOBBY", pos = Vector3.new(0, 11, -4), look = Vector3.new(0, 3, 8) },
	}
	for i, def in ipairs(camDefs) do
		local cam = P({ Pos = def.pos, Size = Vector3.new(1, 1, 1), Transparency = 1, CanCollide = false, Name = "Cam" .. i })
		cam.CFrame = CFrame.lookAt(def.pos, def.look)
		local holder = P({ Pos = def.pos + Vector3.new(0, 0.8, 0), Size = Vector3.new(0.8, 0.8, 1.4), Color = Color3.fromRGB(40, 40, 44), Material = Enum.Material.Metal, Name = "CamBody" .. i })
		Map.Cameras[i] = { part = cam, name = def.name }
	end

	-- RAIN + DUST EMITTER HOLDERS (emitters added by VFXServer)
	local rainPart = P({ Pos = Vector3.new(0, 55, 30), Size = Vector3.new(90, 1, 90), Transparency = 1, CanCollide = false, Name = "RainEmitter" })
	Map.RainPart = rainPart
	local dustPart = P({ Pos = Vector3.new(0, 9, -2), Size = Vector3.new(20, 1, 20), Transparency = 1, CanCollide = false, Name = "DustEmitter" })
	Map.DustPart = dustPart

	-- SPAWN
	local spawnLoc = Instance.new("SpawnLocation")
	spawnLoc.Anchored = true
	spawnLoc.Size = Vector3.new(10, 1, 10)
	spawnLoc.CFrame = CFrame.new(0, 0.6, 50)
	spawnLoc.Color = Color3.fromRGB(70, 70, 74)
	spawnLoc.Material = Enum.Material.Concrete
	spawnLoc.Neutral = true
	spawnLoc.Name = "SpawnLocation"
	spawnLoc.Parent = map

	return Map
end

return MapBuilder
