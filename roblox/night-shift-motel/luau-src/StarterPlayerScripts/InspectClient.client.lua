-- InspectClient: click a guest (or press INSPECT) to zoom to their face,
-- then Inspect hands / Inspect face. Shows found tells.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local old = pg:FindFirstChild("NSM_Inspect")
if old then old:Destroy() end

local gui = Instance.new("ScreenGui")
gui.Name = "NSM_Inspect"
gui.ResetOnSpawn = false
gui.Parent = pg

local function mk(class, props, parent)
	local o = Instance.new(class)
	for k, v in pairs(props) do o[k] = v end
	o.Parent = parent
	return o
end

local inspecting = nil
local zooming = false

local frame = mk("Frame", { Size = UDim2.new(0.9, 0, 0.42, 0), Position = UDim2.new(0.05, 0, 0.29, 0), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.1, Visible = false, ZIndex = 9 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 10) }, frame)
mk("UISizeConstraint", { MaxSize = Vector2.new(460, 340) }, frame)
local title = mk("TextLabel", { Size = UDim2.new(1, -12, 0, 30), Position = UDim2.new(0, 6, 0, 4), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 220, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "INSPECTION", ZIndex = 10 }, frame)
local result = mk("TextLabel", { Size = UDim2.new(1, -12, 0.38, 0), Position = UDim2.new(0, 6, 0, 38), BackgroundColor3 = Color3.fromRGB(28, 28, 36), TextColor3 = Color3.fromRGB(240, 240, 240), TextScaled = true, Font = Enum.Font.Gotham, Text = "Look closely...", TextWrapped = true, ZIndex = 10 }, frame)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, result)

local handsBtn = mk("TextButton", { Size = UDim2.new(1, -12, 0, 44), Position = UDim2.new(0, 6, 1, -98), BackgroundColor3 = Color3.fromRGB(40, 40, 56), TextColor3 = Color3.fromRGB(200, 220, 255), TextScaled = true, Font = Enum.Font.GothamBold, Text = "INSPECT HANDS", ZIndex = 10 }, frame)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, handsBtn)
local faceBtn = mk("TextButton", { Size = UDim2.new(1, -12, 0, 44), Position = UDim2.new(0, 6, 1, -50), BackgroundColor3 = Color3.fromRGB(40, 40, 56), TextColor3 = Color3.fromRGB(200, 220, 255), TextScaled = true, Font = Enum.Font.GothamBold, Text = "INSPECT FACE", ZIndex = 10 }, frame)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, faceBtn)
local closeBtn = mk("TextButton", { Size = UDim2.new(0, 100, 0, 32), Position = UDim2.new(1, -106, 0, 4), BackgroundColor3 = Color3.fromRGB(120, 40, 40), TextColor3 = Color3.fromRGB(255, 230, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "CLOSE", ZIndex = 10 }, frame)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, closeBtn)

local function closeInspect()
	frame.Visible = false
	inspecting = nil
	if zooming then
		zooming = false
		local cam = workspace.CurrentCamera
		cam.CameraType = Enum.CameraType.Custom
		local char = player.Character
		local hum = char and char:FindFirstChildOfClass("Humanoid")
		if hum then cam.CameraSubject = hum end
	end
end
closeBtn.MouseButton1Click:Connect(closeInspect)

handsBtn.MouseButton1Click:Connect(function()
	if inspecting then remotes.Inspect:FireServer(inspecting, "Hands") end
end)
faceBtn.MouseButton1Click:Connect(function()
	if inspecting then remotes.Inspect:FireServer(inspecting, "Face") end
end)

local function startInspect(guestId)
	inspecting = guestId
	remotes.Inspect:FireServer(guestId, "open")
end

remotes.InspectResult.OnClientEvent:Connect(function(guestId, kind, labels, headCF)
	if guestId ~= inspecting then return end
	if kind == "open" then
		frame.Visible = true
		result.Text = "Look closely..."
		if headCF then
			zooming = true
			local cam = workspace.CurrentCamera
			cam.CameraType = Enum.CameraType.Scriptable
			local target = headCF * CFrame.new(0, 0.1, 4.2)
			TweenService:Create(cam, TweenInfo.new(0.5), { CFrame = target }):Play()
		end
	else
		local txt
		if #labels == 0 then
			txt = "Looks normal."
		else
			txt = ""
			for _, l in ipairs(labels) do
				txt = txt .. "!! " .. l .. "\n"
			end
		end
		if _G.NSM_Hallucinating and #labels == 0 and math.random() < 0.3 then
			txt = "!! Six fingers on one hand"
			task.delay(3, function()
				if result.Text == txt then
					result.Text = "Looks normal."
				end
			end)
		end
		result.Text = txt
	end
end)

-- Click any guest to inspect (works with touch)
local map = workspace:FindFirstChild("Map")
if map then
	map.DescendantAdded:Connect(function(d)
		if d:IsA("ClickDetector") and d.Parent and d.Parent:FindFirstChild("HumanoidRootPart") then
			d.MouseClick:Connect(function()
				local guestId = d.Parent:GetAttribute("GuestId")
				if guestId then startInspect(guestId) end
			end)
		end
	end)
end
