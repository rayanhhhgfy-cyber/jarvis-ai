-- HUD v2: mobile-first scale-based layout. Money/rep/night/queue top bar,
-- sanity bar bottom-center, notifications, title cards, hunt overlay,
-- quick chat (right edge, clear of the touch controls), downed overlay, screen shake.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local old = pg:FindFirstChild("NSM_HUD")
if old then old:Destroy() end

local gui = Instance.new("ScreenGui")
gui.Name = "NSM_HUD"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = false
gui.Parent = pg

local function mk(class, props, parent)
	local o = Instance.new(class)
	for k, v in pairs(props) do o[k] = v end
	o.Parent = parent
	return o
end

local state = { money = 0, stars = 1, night = 1, phase = "Lobby", queueLeft = 0, sanity = 100, hints = false }

-- TOP BAR (full width, scales to any phone)
local top = mk("Frame", { Size = UDim2.new(1, -12, 0, 78), Position = UDim2.new(0, 6, 0, 6), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.25, BorderSizePixel = 0 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, top)
local moneyLabel = mk("TextLabel", { Size = UDim2.new(0.5, -8, 0, 24), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(120, 255, 140), TextScaled = true, Font = Enum.Font.Arcade, Text = "$0", TextXAlignment = Enum.TextXAlignment.Left }, top)
local repLabel = mk("TextLabel", { Size = UDim2.new(0.5, -8, 0, 24), Position = UDim2.new(0.5, 0, 0, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 220, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "REP: *", TextXAlignment = Enum.TextXAlignment.Right }, top)
local nightLabel = mk("TextLabel", { Size = UDim2.new(0.5, -8, 0, 24), Position = UDim2.new(0, 0, 0, 26), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 90, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "NIGHT 1", TextXAlignment = Enum.TextXAlignment.Left }, top)
local queueLabel = mk("TextLabel", { Size = UDim2.new(0.5, -8, 0, 24), Position = UDim2.new(0.5, 0, 0, 26), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(200, 200, 210), TextScaled = true, Font = Enum.Font.Arcade, Text = "Guests left: 0", TextXAlignment = Enum.TextXAlignment.Right }, top)
local objectiveLabel = mk("TextLabel", { Size = UDim2.new(1, -8, 0, 24), Position = UDim2.new(0, 4, 0, 52), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(180, 180, 190), TextScaled = true, Font = Enum.Font.Gotham, Text = "", TextWrapped = true }, top)

-- SANITY BAR (bottom center, scale width)
local sanityBack = mk("Frame", { Size = UDim2.new(0.55, 0, 0, 28), Position = UDim2.new(0.225, 0, 1, -36), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.25, BorderSizePixel = 0 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, sanityBack)
local sanityFill = mk("Frame", { Size = UDim2.new(1, -6, 1, -6), Position = UDim2.new(0, 3, 0, 3), BackgroundColor3 = Color3.fromRGB(120, 200, 255), BorderSizePixel = 0 }, sanityBack)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, sanityFill)
local sanityNum = mk("TextLabel", { Size = UDim2.new(1, 0, 1, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 255, 255), TextScaled = true, Font = Enum.Font.Arcade, Text = "SANITY 100", ZIndex = 2 }, sanityBack)
local lowWarn = mk("TextLabel", { Size = UDim2.new(0.4, 0, 0, 26), Position = UDim2.new(0.3, 0, 1, -94), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 60, 60), TextScaled = true, Font = Enum.Font.Arcade, Text = "LOW SANITY", Visible = false, ZIndex = 3 }, gui)

-- COFFEE / WARMER STATUS (above the sanity bar)
local warmerLabel = mk("TextLabel", { Size = UDim2.new(0.55, 0, 0, 22), Position = UDim2.new(0.225, 0, 1, -62), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.4, TextColor3 = Color3.fromRGB(255, 200, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "Coffee warmer: brewing...", Visible = false }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, warmerLabel)

-- NOTIFICATIONS (top center, below the top bar)
local notifyArea = mk("Frame", { Size = UDim2.new(0.72, 0, 0, 280), Position = UDim2.new(0.14, 0, 0, 90), BackgroundTransparency = 1 }, gui)
mk("UIListLayout", { Padding = UDim.new(0, 6), HorizontalAlignment = Enum.HorizontalAlignment.Center }, notifyArea)

local function notify(text, kind)
	local colors = { good = Color3.fromRGB(120, 255, 140), bad = Color3.fromRGB(255, 90, 90), guest = Color3.fromRGB(255, 220, 90), info = Color3.fromRGB(190, 190, 200) }
	local label = mk("TextLabel", { Size = UDim2.new(1, 0, 0, 36), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.25, TextColor3 = colors[kind] or colors.info, TextScaled = true, Font = Enum.Font.Arcade, Text = text }, notifyArea)
	mk("UICorner", { CornerRadius = UDim.new(0, 8) }, label)
	task.delay(4, function()
		if label.Parent then label:Destroy() end
	end)
end
remotes.Notify.OnClientEvent:Connect(notify)

-- TITLE CARD
local titleCard = mk("Frame", { Size = UDim2.new(1, 0, 1, 0), BackgroundColor3 = Color3.fromRGB(0, 0, 0), BackgroundTransparency = 0.35, Visible = false, ZIndex = 5 }, gui)
local titleNight = mk("TextLabel", { Size = UDim2.new(1, 0, 0.12, 0), Position = UDim2.new(0, 0, 0.18, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 60, 60), TextScaled = true, Font = Enum.Font.Arcade, Text = "NIGHT 1", ZIndex = 6 }, titleCard)
local titleObj = mk("TextLabel", { Size = UDim2.new(0.84, 0, 0.05, 0), Position = UDim2.new(0.08, 0, 0.32, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(230, 230, 240), TextScaled = true, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, ZIndex = 6 }, titleCard)
local titleRules = mk("TextLabel", { Size = UDim2.new(0.8, 0, 0.3, 0), Position = UDim2.new(0.1, 0, 0.39, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 220, 90), TextScaled = true, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, ZIndex = 6 }, titleCard)
local hintLabel = mk("TextLabel", { Size = UDim2.new(0.86, 0, 0.08, 0), Position = UDim2.new(0.07, 0, 0.78, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(160, 220, 255), TextScaled = true, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, ZIndex = 6 }, titleCard)

remotes.TitleCard.OnClientEvent:Connect(function(night, objective, newRules, hints)
	titleNight.Text = "NIGHT " .. night
	titleObj.Text = objective
	local txt = ""
	for _, r in ipairs(newRules or {}) do
		txt = txt .. "NEW RULE: " .. r .. "\n\n"
	end
	titleRules.Text = txt
	hintLabel.Text = hints and ("TUTORIAL: Walk to the desk and press Sit. Then use INSPECT, QUESTIONS, CAMERAS and the HANDBOOK before you ADMIT or TURN AWAY.") or ""
	titleCard.Visible = true
	task.delay(7, function() titleCard.Visible = false end)
end)

-- HUNT OVERLAY (below the top bar so it never overlaps it)
local huntOverlay = mk("TextLabel", { Size = UDim2.new(1, 0, 0, 46), Position = UDim2.new(0, 0, 0, 90), BackgroundColor3 = Color3.fromRGB(80, 0, 0), BackgroundTransparency = 0.2, TextColor3 = Color3.fromRGB(255, 60, 60), TextScaled = true, Font = Enum.Font.Arcade, Text = "LOCKDOWN — SOMETHING IS IN THE ROOMS", Visible = false, ZIndex = 4 }, gui)
local huntTimerLabel = mk("TextLabel", { Size = UDim2.new(0.4, 0, 0, 38), Position = UDim2.new(0.3, 0, 0, 140), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.3, TextColor3 = Color3.fromRGB(255, 120, 120), TextScaled = true, Font = Enum.Font.Arcade, Text = "", Visible = false, ZIndex = 4 }, gui)

remotes.HuntState.OnClientEvent:Connect(function(active, timeLeft)
	huntOverlay.Visible = active
	huntTimerLabel.Visible = active
	if active then
		huntTimerLabel.Text = "DAWN IN " .. tostring(timeLeft) .. "s"
	end
end)

-- DOWNED OVERLAY
local downedOverlay = mk("Frame", { Size = UDim2.new(1, 0, 1, 0), BackgroundColor3 = Color3.fromRGB(40, 0, 0), BackgroundTransparency = 0.45, Visible = false, ZIndex = 7 }, gui)
mk("TextLabel", { Size = UDim2.new(1, 0, 0.1, 0), Position = UDim2.new(0, 0, 0.38, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 80, 80), TextScaled = true, Font = Enum.Font.Arcade, Text = "YOU WERE CAUGHT", ZIndex = 8 }, downedOverlay)
remotes.Downed.OnClientEvent:Connect(function(isDowned)
	downedOverlay.Visible = isDowned and true or false
end)

-- QUICK CHAT (right edge, middle height: clear of thumbstick and jump button)
local quickTexts = { "I think this one is fake", "Check the cameras", "Hide!", "It's safe" }
local qcFrame = mk("Frame", { Size = UDim2.new(0, 170, 0, 168), Position = UDim2.new(1, -178, 0.32, 0), BackgroundTransparency = 1 }, gui)
mk("UIListLayout", { Padding = UDim.new(0, 6) }, qcFrame)
for _, txt in ipairs(quickTexts) do
	local b = mk("TextButton", { Size = UDim2.new(1, 0, 0, 36), BackgroundColor3 = Color3.fromRGB(30, 30, 42), BackgroundTransparency = 0.2, TextColor3 = Color3.fromRGB(255, 240, 170), TextScaled = true, Font = Enum.Font.GothamBold, Text = txt }, qcFrame)
	mk("UICorner", { CornerRadius = UDim.new(0, 8) }, b)
	b.MouseButton1Click:Connect(function()
		remotes.QuickChat:FireServer(txt)
	end)
end

-- SCREEN SHAKE
remotes.Shake.OnClientEvent:Connect(function(intensity)
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	if not hum then return end
	local t0 = os.clock()
	while os.clock() - t0 < 0.6 do
		hum.CameraOffset = Vector3.new(math.random(-10, 10) / 10 * intensity, math.random(-10, 10) / 10 * intensity, 0)
		RunService.RenderStepped:Wait()
	end
	hum.CameraOffset = Vector3.new()
end)

-- STATE + SANITY
local function starsText(n)
	local s = ""
	for i = 1, 5 do
		s = s .. (i <= n and "*" or "-")
	end
	return s
end

remotes.StateUpdate.OnClientEvent:Connect(function(s)
	state.money = s.money
	state.stars = s.stars
	state.night = s.night
	state.phase = s.phase
	state.queueLeft = s.queueLeft
	state.hints = s.hints
	moneyLabel.Text = "$" .. tostring(s.money)
	repLabel.Text = "REP: " .. starsText(s.stars)
	nightLabel.Text = "NIGHT " .. tostring(s.night)
	queueLabel.Text = "Guests left: " .. tostring(s.queueLeft)
	objectiveLabel.Text = s.objective or ""
end)

remotes.Sanity.OnClientEvent:Connect(function(v)
	state.sanity = v
	sanityFill.Size = UDim2.new(math.clamp(v / 100, 0, 1), -6, 1, -6)
	sanityFill.BackgroundColor3 = v > 50 and Color3.fromRGB(120, 200, 255) or (v > 25 and Color3.fromRGB(255, 200, 90) or Color3.fromRGB(255, 60, 60))
	sanityNum.Text = "SANITY " .. tostring(math.floor(v))
end)

-- LOW SANITY FLASH + WARMER DISPLAY
task.spawn(function()
	local warmerReadyAt, warmerMinutes = nil, 20
	remotes.StateUpdate.OnClientEvent:Connect(function(s)
		warmerReadyAt = s.warmerReadyAt
		warmerMinutes = s.warmerMinutes
	end)
	while true do
		task.wait(0.5)
		lowWarn.Visible = state.sanity < 25 and (os.clock() % 1 < 0.5)
		if warmerReadyAt then
			warmerLabel.Visible = true
			local left = warmerReadyAt - workspace:GetServerTimeNow()
			if left <= 0 then
				warmerLabel.Text = "COFFEE READY at the warmer! (+50 sanity)"
			else
				warmerLabel.Text = string.format("Warmer pot: %d:%02d", math.floor(left / 60), math.floor(left % 60))
			end
		end
	end
end)
