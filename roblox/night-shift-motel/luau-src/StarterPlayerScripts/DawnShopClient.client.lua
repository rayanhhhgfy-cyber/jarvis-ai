-- DawnShopClient: dawn summary, chore list, the dawn shop (Desk 2/3), win/lose screens.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local old = pg:FindFirstChild("NSM_Dawn")
if old then old:Destroy() end

local gui = Instance.new("ScreenGui")
gui.Name = "NSM_Dawn"
gui.ResetOnSpawn = false
gui.Parent = pg

local function mk(class, props, parent)
	local o = Instance.new(class)
	for k, v in pairs(props) do o[k] = v end
	o.Parent = parent
	return o
end

local desksBought = 1
local deskPrices = {}

-- DAWN SCREEN
local dawn = mk("Frame", { Size = UDim2.new(0, 520, 0, 420), Position = UDim2.new(0.5, -260, 0.5, -210), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.05, Visible = false, ZIndex = 9 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 12) }, dawn)
mk("TextLabel", { Size = UDim2.new(1, 0, 0, 50), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 200, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "DAWN — YOU SURVIVED THE NIGHT", ZIndex = 10 }, dawn)
local summary = mk("TextLabel", { Size = UDim2.new(1, -20, 0, 110), Position = UDim2.new(0, 10, 0, 56), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(220, 220, 230), TextSize = 20, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, ZIndex = 10 }, dawn)
local choresTitle = mk("TextLabel", { Size = UDim2.new(1, -20, 0, 30), Position = UDim2.new(0, 10, 0, 170), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 120, 120), TextScaled = true, Font = Enum.Font.Arcade, Text = "MORNING CHORES", TextXAlignment = Enum.TextXAlignment.Left, ZIndex = 10 }, dawn)
local choresText = mk("TextLabel", { Size = UDim2.new(1, -20, 0, 110), Position = UDim2.new(0, 10, 0, 202), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(220, 220, 230), TextSize = 18, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, ZIndex = 10 }, dawn)

-- SHOP
local shopTitle = mk("TextLabel", { Size = UDim2.new(1, -20, 0, 30), Position = UDim2.new(0, 10, 0, 312), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(120, 255, 140), TextScaled = true, Font = Enum.Font.Arcade, Text = "MOTEL UPGRADES", TextXAlignment = Enum.TextXAlignment.Left, ZIndex = 10 }, dawn)
local deskRow = mk("Frame", { Size = UDim2.new(1, -20, 0, 44), Position = UDim2.new(0, 10, 0, 344), BackgroundTransparency = 1, ZIndex = 10 }, dawn)
mk("UIGridLayout", { CellSize = UDim2.new(0.5, -6, 1, 0), CellPadding = UDim2.new(0, 6, 0, 0) }, deskRow)
local deskButtons = {}
for slot = 2, 3 do
	local b = mk("TextButton", { BackgroundColor3 = Color3.fromRGB(30, 90, 140), TextColor3 = Color3.fromRGB(230, 245, 255), TextScaled = true, Font = Enum.Font.GothamBold, Text = "DESK " .. slot, ZIndex = 11 }, deskRow)
	mk("UICorner", { CornerRadius = UDim.new(0, 8) }, b)
	b.MouseButton1Click:Connect(function()
		remotes.Shop:FireServer("buyDesk", slot)
	end)
	deskButtons[slot] = b
end
local bottomRow = mk("Frame", { Size = UDim2.new(1, -20, 0, 44), Position = UDim2.new(0, 10, 1, -52), BackgroundTransparency = 1, ZIndex = 10 }, dawn)
local shopBtn = mk("TextButton", { Size = UDim2.new(0.5, -6, 1, 0), BackgroundColor3 = Color3.fromRGB(60, 60, 80), TextColor3 = Color3.fromRGB(230, 230, 240), TextScaled = true, Font = Enum.Font.Arcade, Text = "DESK HELP", ZIndex = 11 }, bottomRow)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, shopBtn)
local startBtn = mk("TextButton", { Size = UDim2.new(0.5, -6, 1, 0), Position = UDim2.new(0.5, 6, 0, 0), BackgroundColor3 = Color3.fromRGB(30, 120, 50), TextColor3 = Color3.fromRGB(230, 255, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "START NEXT NIGHT", ZIndex = 11 }, bottomRow)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, startBtn)
startBtn.MouseButton1Click:Connect(function()
	dawn.Visible = false
	remotes.NextNight:FireServer()
end)
shopBtn.MouseButton1Click:Connect(function()
	shopTitle.Text = "Desks: one per player. Solo players cannot use extra desks."
end)

remotes.Dawn.OnClientEvent:Connect(function(payload)
	summary.Text = "Night " .. payload.night .. " summary:\nMoney earned: $" .. payload.earned .. "\nCorrect calls: " .. payload.correct .. "\nWrong calls: " .. payload.wrong .. "\nMonsters caught: " .. payload.caught
	local txt = ""
	if #payload.chores == 0 then
		txt = "All rooms are clean. Nothing to do."
	else
		for _, ch in ipairs(payload.chores) do
			local what = ch.kind == "messy" and "needs cleaning" or "guest won't leave"
			txt = txt .. "Room " .. ch.room .. " — " .. what .. "\n"
		end
		txt = txt .. "\nWalk to each room to fix it. All chores done: +$10 and +5 reputation."
	end
	choresText.Text = txt
	dawn.Visible = true
end)

remotes.StateUpdate.OnClientEvent:Connect(function(s)
	desksBought = s.desksBought
	deskPrices = s.deskPrices or {}
	for slot, b in pairs(deskButtons) do
		if slot <= desksBought then
			b.Text = "DESK " .. slot .. " — OWNED"
			b.BackgroundColor3 = Color3.fromRGB(40, 60, 40)
		elseif #Players:GetPlayers() < slot then
			b.Text = "DESK " .. slot .. " — $" .. (deskPrices[slot] or 0) .. " (needs a friend)"
			b.BackgroundColor3 = Color3.fromRGB(60, 60, 66)
		else
			b.Text = "DESK " .. slot .. " — $" .. (deskPrices[slot] or 0)
			b.BackgroundColor3 = Color3.fromRGB(30, 90, 140)
		end
	end
end)

-- WIN / LOSE SCREENS
local endFrame = mk("Frame", { Size = UDim2.new(1, 0, 1, 0), BackgroundColor3 = Color3.fromRGB(0, 0, 0), BackgroundTransparency = 0.25, Visible = false, ZIndex = 12 }, gui)
local endTitle = mk("TextLabel", { Size = UDim2.new(1, 0, 0, 90), Position = UDim2.new(0, 0, 0.3, 0), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 220, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "", ZIndex = 13 }, endFrame)
local endSub = mk("TextLabel", { Size = UDim2.new(0.8, 0, 0, 60), Position = UDim2.new(0.1, 0, 0.3, 100), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(230, 230, 240), TextScaled = true, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, ZIndex = 13 }, endFrame)
local againBtn = mk("TextButton", { Size = UDim2.new(0, 260, 0, 60), Position = UDim2.new(0.5, -130, 0.3, 190), BackgroundColor3 = Color3.fromRGB(30, 120, 50), TextColor3 = Color3.fromRGB(230, 255, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "PLAY AGAIN", ZIndex = 13 }, endFrame)
mk("UICorner", { CornerRadius = UDim.new(0, 10) }, againBtn)
againBtn.MouseButton1Click:Connect(function()
	endFrame.Visible = false
	remotes.NextNight:FireServer()
end)

remotes.EndScreen.OnClientEvent:Connect(function(win, data)
	if win then
		endTitle.Text = "YOU SURVIVED ALL 5 NIGHTS"
		endSub.Text = "Final money: $" .. tostring(data.money) .. "   Reputation: " .. tostring(data.stars) .. " stars"
		againBtn.Text = "PLAY AGAIN"
	else
		endTitle.Text = "GAME OVER"
		endSub.Text = "The motel is lost on night " .. tostring(data.night) .. "."
		againBtn.Text = "RETRY NIGHT"
	end
	endFrame.Visible = true
end)
