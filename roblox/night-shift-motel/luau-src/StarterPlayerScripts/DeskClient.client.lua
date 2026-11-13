-- DeskClient: guest panel at your desk — questions, ID card, ADMIT / TURN AWAY,
-- and the overstayer morning dialog.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local old = pg:FindFirstChild("NSM_Desk")
if old then old:Destroy() end

local gui = Instance.new("ScreenGui")
gui.Name = "NSM_Desk"
gui.ResetOnSpawn = false
gui.Parent = pg

local function mk(class, props, parent)
	local o = Instance.new(class)
	for k, v in pairs(props) do o[k] = v end
	o.Parent = parent
	return o
end

local myDesk = nil
local guests = {}
local cleanRooms = true
local currentId = nil

local panel = mk("Frame", { Size = UDim2.new(0, 420, 0, 330), Position = UDim2.new(1, -430, 1, -340), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.15, BorderSizePixel = 0, Visible = false }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 10) }, panel)
local nameLabel = mk("TextLabel", { Size = UDim2.new(1, -12, 0, 30), Position = UDim2.new(0, 6, 0, 4), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 220, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "GUEST", TextXAlignment = Enum.TextXAlignment.Left }, panel)
local speech = mk("TextLabel", { Size = UDim2.new(1, -12, 0, 54), Position = UDim2.new(0, 6, 0, 34), BackgroundColor3 = Color3.fromRGB(28, 28, 36), TextColor3 = Color3.fromRGB(240, 240, 240), TextScaled = true, Font = Enum.Font.Gotham, Text = "...", TextWrapped = true }, panel)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, speech)

local idCard = mk("Frame", { Size = UDim2.new(1, -12, 0, 64), Position = UDim2.new(0, 6, 0, 92), BackgroundColor3 = Color3.fromRGB(210, 200, 170), Visible = false }, panel)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, idCard)
local idText = mk("TextLabel", { Size = UDim2.new(1, -10, 1, -6), Position = UDim2.new(0, 5, 0, 3), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(35, 30, 25), TextScaled = true, Font = Enum.Font.Code, Text = "ID CARD", TextWrapped = true }, idCard)

local qFrame = mk("Frame", { Size = UDim2.new(1, -12, 0, 110), Position = UDim2.new(0, 6, 0, 160), BackgroundTransparency = 1 }, panel)
mk("UIGridLayout", { CellSize = UDim2.new(0.5, -4, 0, 34), CellPadding = UDim2.new(0, 4, 0, 4), SortOrder = Enum.SortOrder.LayoutOrder }, qFrame)

local questions = {
	{ id = "from", text = "Where are you traveling from?" },
	{ id = "id", text = "Can I see your ID?" },
	{ id = "year", text = "What year is it?" },
	{ id = "job", text = "What is your job?" },
	{ id = "stay", text = "How long are you staying?" },
}

local function makeQButton(q, order)
	local b = mk("TextButton", { LayoutOrder = order, BackgroundColor3 = Color3.fromRGB(40, 40, 56), BackgroundTransparency = 0.2, TextColor3 = Color3.fromRGB(200, 220, 255), TextScaled = true, Font = Enum.Font.Gotham, Text = q.text }, qFrame)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, b)
	b.MouseButton1Click:Connect(function()
		if currentId then
			remotes.Ask:FireServer(currentId, q.id)
		end
	end)
end
for i, q in ipairs(questions) do
	makeQButton(q, i)
end

local decisionRow = mk("Frame", { Size = UDim2.new(1, -12, 0, 48), Position = UDim2.new(0, 6, 1, -54), BackgroundTransparency = 1 }, panel)
local admitBtn = mk("TextButton", { Size = UDim2.new(0.5, -6, 1, 0), BackgroundColor3 = Color3.fromRGB(30, 120, 50), TextColor3 = Color3.fromRGB(230, 255, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "GIVE ROOM KEY" }, decisionRow)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, admitBtn)
local denyBtn = mk("TextButton", { Size = UDim2.new(0.5, -6, 1, 0), Position = UDim2.new(0.5, 6, 0, 0), BackgroundColor3 = Color3.fromRGB(150, 40, 40), TextColor3 = Color3.fromRGB(255, 230, 230), TextScaled = true, Font = Enum.Font.Arcade, Text = "TURN AWAY" }, decisionRow)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, denyBtn)

admitBtn.MouseButton1Click:Connect(function()
	if currentId then remotes.Decide:FireServer(currentId, true) end
end)
denyBtn.MouseButton1Click:Connect(function()
	if currentId then remotes.Decide:FireServer(currentId, false) end
end)

-- SEAT TRACKING
local function trackSeat()
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	if hum then
		local seat = hum.SeatPart
		if seat and seat.Name:sub(1, 8) == "DeskSeat" then
			myDesk = tonumber(seat.Name:sub(9))
		else
			myDesk = nil
		end
	end
end

task.spawn(function()
	while true do
		task.wait(0.4)
		trackSeat()
		local guest = myDesk and guests[myDesk]
		panel.Visible = guest ~= nil
		if guest then
			currentId = guest.id
			nameLabel.Text = (guest.angry and "[ANGRY] " or "") .. guest.name
		else
			currentId = nil
		end
		admitBtn.Text = cleanRooms and "GIVE ROOM KEY" or "NO CLEAN ROOMS"
	end
end)

remotes.GuestUpdate.OnClientEvent:Connect(function(data)
	if data.present then
		guests[data.desk] = data
		speech.Text = "..."
		idCard.Visible = false
	else
		if guests[data.desk] and guests[data.desk].id == data.id then
			guests[data.desk] = nil
		end
	end
end)

remotes.Answer.OnClientEvent:Connect(function(guestId, qid, text, idCardData)
	if currentId ~= guestId then return end
	speech.Text = text
	if qid == "id" and idCardData then
		idCard.Visible = true
		idText.Text = "GUEST ID\nName: " .. idCardData.name .. "\nFrom: " .. idCardData.from .. "   Stay: " .. idCardData.stay
	end
end)

remotes.StateUpdate.OnClientEvent:Connect(function(s)
	cleanRooms = false
	for _, r in ipairs(s.rooms) do
		if r.state == "clean" then cleanRooms = true end
	end
end)

-- MORNING CHORE DIALOG (overstayer)
local choreFrame = mk("Frame", { Size = UDim2.new(0, 400, 0, 240), Position = UDim2.new(0.5, -200, 0.5, -120), BackgroundColor3 = Color3.fromRGB(16, 16, 22), BackgroundTransparency = 0.1, Visible = false, ZIndex = 9 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 10) }, choreFrame)
local choreTitle = mk("TextLabel", { Size = UDim2.new(1, -12, 0, 30), Position = UDim2.new(0, 6, 0, 4), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(255, 220, 90), TextScaled = true, Font = Enum.Font.Arcade, Text = "ROOM — GUEST WON'T LEAVE", ZIndex = 10 }, choreFrame)
local choreArg = mk("TextLabel", { Size = UDim2.new(1, -12, 0, 60), Position = UDim2.new(0, 6, 0, 38), BackgroundColor3 = Color3.fromRGB(28, 28, 36), TextColor3 = Color3.fromRGB(240, 240, 240), TextScaled = true, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, ZIndex = 10 }, choreFrame)
mk("UICorner", { CornerRadius = UDim.new(0, 6) }, choreArg)
local choreChoices = mk("Frame", { Size = UDim2.new(1, -12, 0, 120), Position = UDim2.new(0, 6, 0, 108), BackgroundTransparency = 1, ZIndex = 10 }, choreFrame)
mk("UIListLayout", { Padding = UDim.new(0, 6) }, choreChoices)
local choreRoom = nil

local choiceTexts = {
	"Okay, sleep in then.",
	"Checkout was at dawn, you have to leave now.",
	"Take your time, sir.",
}
for i, txt in ipairs(choiceTexts) do
	local b = mk("TextButton", { Size = UDim2.new(1, 0, 0, 36), BackgroundColor3 = i == 2 and Color3.fromRGB(30, 90, 140) or Color3.fromRGB(50, 50, 60), TextColor3 = Color3.fromRGB(240, 240, 240), TextScaled = true, Font = Enum.Font.Gotham, Text = txt, ZIndex = 11 }, choreChoices)
	mk("UICorner", { CornerRadius = UDim.new(0, 6) }, b)
	b.MouseButton1Click:Connect(function()
		if choreRoom then
			remotes.ChoreReply:FireServer(choreRoom, i)
		end
		choreFrame.Visible = false
	end)
end

remotes.ChoreDialog.OnClientEvent:Connect(function(room, argument)
	choreRoom = room
	choreTitle.Text = "ROOM " .. tostring(room) .. " — GUEST WON'T LEAVE"
	choreArg.Text = '"' .. argument .. '"'
	choreFrame.Visible = true
end)
