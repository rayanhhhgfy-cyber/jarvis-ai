-- CamerasClient v2: 4 security feeds by moving the camera to camera parts.
-- Clean, watchable feeds: subtle scanlines + rare static bursts (full static
-- only during power flickers), big touch-friendly cam buttons and EXIT.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local old = pg:FindFirstChild("NSM_Cams")
if old then old:Destroy() end

local gui = Instance.new("ScreenGui")
gui.Name = "NSM_Cams"
gui.ResetOnSpawn = false
gui.Parent = pg

local function mk(class, props, parent)
	local o = Instance.new(class)
	for k, v in pairs(props) do o[k] = v end
	o.Parent = parent
	return o
end

local camApps = {}
local guestModels = {}
local viewing = nil
local baseFOV = 70
local camFolder = workspace:WaitForChild("Map", 30)

local openBtn = mk("TextButton", { Size = UDim2.new(0, 140, 0, 44), Position = UDim2.new(0, 8, 0.5, 4), BackgroundColor3 = Color3.fromRGB(20, 50, 30), TextColor3 = Color3.fromRGB(120, 255, 140), TextScaled = true, Font = Enum.Font.Arcade, Text = "CAMERAS" }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, openBtn)

local overlay = mk("Frame", { Size = UDim2.new(1, 0, 1, 0), BackgroundColor3 = Color3.fromRGB(0, 0, 0), BackgroundTransparency = 0.55, Visible = false, ZIndex = 5 }, gui)
local static = mk("Frame", { Size = UDim2.new(1, 0, 1, 0), BackgroundColor3 = Color3.fromRGB(210, 210, 210), BackgroundTransparency = 1, Visible = true, ZIndex = 6, BorderSizePixel = 0 }, overlay)
local scanline = mk("Frame", { Size = UDim2.new(1, 0, 0.05, 0), Position = UDim2.new(0, 0, 0, 0), BackgroundColor3 = Color3.fromRGB(0, 0, 0), BackgroundTransparency = 0.82, Visible = true, ZIndex = 6, BorderSizePixel = 0 }, overlay)
local camLabel = mk("TextLabel", { Size = UDim2.new(0, 220, 0, 40), Position = UDim2.new(0, 12, 0, 64), BackgroundColor3 = Color3.fromRGB(10, 10, 12), TextColor3 = Color3.fromRGB(120, 255, 140), TextScaled = true, Font = Enum.Font.Code, Text = "CAM 01", ZIndex = 7 }, overlay)
local recDot = mk("TextLabel", { Size = UDim2.new(0, 70, 0, 34), Position = UDim2.new(1, -80, 0, 64), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 60, 60), TextScaled = true, Font = Enum.Font.Arcade, Text = "REC", ZIndex = 7 }, overlay)

-- CAM BUTTONS: big row across the top (easy to hit with a thumb)
local btnRow = mk("Frame", { Size = UDim2.new(1, -24, 0, 48), Position = UDim2.new(0, 12, 0, 8), BackgroundTransparency = 1, ZIndex = 7 }, overlay)
mk("UIGridLayout", { CellSize = UDim2.new(0.24, -8, 1, 0), CellPadding = UDim2.new(0, 8, 0, 0) }, btnRow)

local camNames = { "CAM 01", "CAM 02", "CAM 03", "CAM 04" }
local camButtons = {}
local function exitCams()
	viewing = nil
	overlay.Visible = false
	local cam = workspace.CurrentCamera
	cam.CameraType = Enum.CameraType.Custom
	cam.FieldOfView = baseFOV
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	if hum then cam.CameraSubject = hum end
end

for i, name in ipairs(camNames) do
	local b = mk("TextButton", { BackgroundColor3 = Color3.fromRGB(20, 40, 26), TextColor3 = Color3.fromRGB(120, 255, 140), TextScaled = true, Font = Enum.Font.Code, Text = name, ZIndex = 8 }, btnRow)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, b)
	b.MouseButton1Click:Connect(function()
		viewing = i
		camLabel.Text = name
		for n, other in pairs(camButtons) do
			other.BackgroundColor3 = n == i and Color3.fromRGB(40, 90, 50) or Color3.fromRGB(20, 40, 26)
		end
	end)
	camButtons[i] = b
end

local exitBtn = mk("TextButton", { Size = UDim2.new(0, 150, 0, 54), Position = UDim2.new(1, -160, 1, -64), BackgroundColor3 = Color3.fromRGB(120, 40, 40), TextColor3 = Color3.fromRGB(255, 230, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "EXIT", ZIndex = 8 }, overlay)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, exitBtn)
exitBtn.MouseButton1Click:Connect(exitCams)

openBtn.MouseButton1Click:Connect(function()
	overlay.Visible = not overlay.Visible
	if not overlay.Visible then
		exitCams()
	else
		baseFOV = workspace.CurrentCamera.FieldOfView
		viewing = viewing or 1
		camLabel.Text = camNames[viewing]
		for n, other in pairs(camButtons) do
			other.BackgroundColor3 = n == viewing and Color3.fromRGB(40, 90, 50) or Color3.fromRGB(20, 40, 26)
		end
	end
end)

remotes.GuestUpdate.OnClientEvent:Connect(function(data)
	if data.present then
		camApps[data.id] = data.cameraApp or "normal"
	else
		camApps[data.id] = nil
	end
end)

if camFolder then
	camFolder.DescendantAdded:Connect(function(d)
		if d:IsA("Model") and d:GetAttribute("GuestId") then
			guestModels[d:GetAttribute("GuestId")] = d
		end
	end)
	for _, d in ipairs(camFolder:GetDescendants()) do
		if d:IsA("Model") and d:GetAttribute("GuestId") then
			guestModels[d:GetAttribute("GuestId")] = d
		end
	end
end

local staticUntil = 0
remotes.PowerFlicker.OnClientEvent:Connect(function(duration)
	staticUntil = os.clock() + (duration or 10)
end)

-- RENDER LOOP: camera position, subtle static, hidden/distorted monsters
local staticLevel = 1
RunService.RenderStepped:Connect(function()
	local cam = workspace.CurrentCamera
	if overlay.Visible and viewing and camFolder then
		local camDef = camFolder:FindFirstChild("Cam" .. viewing)
		if camDef then
			cam.CameraType = Enum.CameraType.Scriptable
			cam.CFrame = camDef.CFrame
			cam.FieldOfView = 75
		end
		-- static: rare short burst + quick fade so the feed stays watchable
		local powerOut = os.clock() < staticUntil
		if powerOut then
			static.BackgroundColor3 = Color3.fromRGB(180, 180, 180)
			static.BackgroundTransparency = 0.3
		else
			if math.random() < 0.015 then
				staticLevel = 0.12
			end
			staticLevel = staticLevel + (1 - staticLevel) * 0.25
			static.BackgroundColor3 = Color3.fromRGB(210, 210, 210)
			static.BackgroundTransparency = staticLevel
		end
		-- moving scanline for the CRT feel
		scanline.Position = UDim2.new(0, 0, (os.clock() * 0.18) % 1, 0)
		-- hide / distort guests on camera
		for id, app in pairs(camApps) do
			local model = guestModels[id]
			if model and model.Parent then
				local hide = app == "absent"
				for _, p in ipairs(model:GetDescendants()) do
					if p:IsA("BasePart") then
						if hide then
							p.LocalTransparencyModifier = 1
						elseif app == "distorted" then
							p.LocalTransparencyModifier = 0.5 + 0.3 * math.abs(math.sin(os.clock() * 3))
						else
							p.LocalTransparencyModifier = 0
						end
					end
				end
			end
		end
	else
		static.BackgroundTransparency = 1
		-- restore guests when not viewing
		for id in pairs(camApps) do
			local model = guestModels[id]
			if model and model.Parent then
				for _, p in ipairs(model:GetDescendants()) do
					if p:IsA("BasePart") then
						p.LocalTransparencyModifier = 0
					end
				end
			end
		end
	end
end)
