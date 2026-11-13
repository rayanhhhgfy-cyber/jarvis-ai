-- CamerasClient: 4 security feeds by moving the camera to camera parts,
-- static overlay, CAM labels, monsters absent/distorted on camera.
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
local camFolder = workspace:WaitForChild("Map", 30)

local openBtn = mk("TextButton", { Size = UDim2.new(0, 130, 0, 40), Position = UDim2.new(0, 8, 0.5, 30), BackgroundColor3 = Color3.fromRGB(20, 50, 30), TextColor3 = Color3.fromRGB(120, 255, 140), TextScaled = true, Font = Enum.Font.Arcade, Text = "CAMERAS" }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, openBtn)

local overlay = mk("Frame", { Size = UDim2.new(1, 0, 1, 0), BackgroundColor3 = Color3.fromRGB(0, 0, 0), BackgroundTransparency = 0.55, Visible = false, ZIndex = 5 }, gui)
local static = mk("Frame", { Size = UDim2.new(1, 0, 1, 0), BackgroundColor3 = Color3.fromRGB(200, 200, 200), BackgroundTransparency = 0.85, Visible = true, ZIndex = 6 }, overlay)
local camLabel = mk("TextLabel", { Size = UDim2.new(0, 260, 0, 36), Position = UDim2.new(0, 12, 0, 12), BackgroundColor3 = Color3.fromRGB(10, 10, 12), TextColor3 = Color3.fromRGB(120, 255, 140), TextScaled = true, Font = Enum.Font.Code, Text = "CAM 01", ZIndex = 7 }, overlay)
local recDot = mk("TextLabel", { Size = UDim2.new(0, 60, 0, 30), Position = UDim2.new(1, -70, 0, 12), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 60, 60), TextScaled = true, Font = Enum.Font.Arcade, Text = "REC", ZIndex = 7 }, overlay)

local btnRow = mk("Frame", { Size = UDim2.new(0, 480, 0, 50), Position = UDim2.new(0.5, -240, 1, -70), BackgroundTransparency = 1, ZIndex = 7 }, overlay)
mk("UIGridLayout", { CellSize = UDim2.new(0, 110, 1, 0), CellPadding = UDim2.new(0, 10, 0, 0) }, btnRow)

local camNames = { "CAM 01", "CAM 02", "CAM 03", "CAM 04" }
local function exitCams()
	viewing = nil
	overlay.Visible = false
	local cam = workspace.CurrentCamera
	cam.CameraType = Enum.CameraType.Custom
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
	end)
end

local exitBtn = mk("TextButton", { Size = UDim2.new(0, 120, 0, 50), Position = UDim2.new(0.5, 250, 1, -70), BackgroundColor3 = Color3.fromRGB(120, 40, 40), TextColor3 = Color3.fromRGB(255, 230, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "EXIT", ZIndex = 8 }, overlay)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, exitBtn)
exitBtn.MouseButton1Click:Connect(exitCams)

openBtn.MouseButton1Click:Connect(function()
	overlay.Visible = not overlay.Visible
	if not overlay.Visible then
		exitCams()
	else
		viewing = viewing or 1
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

-- RENDER LOOP: camera position, static noise, hidden/distorted monsters
RunService.RenderStepped:Connect(function()
	local cam = workspace.CurrentCamera
	if overlay.Visible and viewing and camFolder then
		local camDef = camFolder:FindFirstChild("Cam" .. viewing)
		if camDef then
			cam.CameraType = Enum.CameraType.Scriptable
			cam.CFrame = camDef.CFrame
		end
		-- static noise flicker
		local powerOut = os.clock() < staticUntil
		if powerOut or math.random() < 0.35 then
			static.BackgroundColor3 = Color3.fromRGB(math.random(120, 255), math.random(120, 255), math.random(120, 255))
			static.BackgroundTransparency = powerOut and 0.25 or math.random(80, 95) / 100
		else
			static.BackgroundTransparency = 1
		end
		-- hide / distort guests on camera
		for id, app in pairs(camApps) do
			local model = guestModels[id]
			if model and model.Parent then
				local hide = app == "absent"
				for _, p in ipairs(model:GetDescendants()) do
					if p:IsA("BasePart") then
						p.LocalTransparencyModifier = hide and 1 or 0
					end
				end
				if app == "distorted" then
					for _, p in ipairs(model:GetDescendants()) do
						if p:IsA("BasePart") then
							p.LocalTransparencyModifier = 0.5 + 0.3 * math.abs(math.sin(os.clock() * 3))
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
