-- HandbookClient: the rule book. Night 1: 3 rules, each night adds more.
-- Rules always match real tells in the code. Scrambles during hallucinations.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local pg = player:WaitForChild("PlayerGui")

local old = pg:FindFirstChild("NSM_Handbook")
if old then old:Destroy() end

local gui = Instance.new("ScreenGui")
gui.Name = "NSM_Handbook"
gui.ResetOnSpawn = false
gui.Parent = pg

local function mk(class, props, parent)
	local o = Instance.new(class)
	for k, v in pairs(props) do o[k] = v end
	o.Parent = parent
	return o
end

local rules = {}
local revealed = 3

local openBtn = mk("TextButton", { Size = UDim2.new(0, 130, 0, 40), Position = UDim2.new(0, 8, 0.5, -20), BackgroundColor3 = Color3.fromRGB(90, 60, 30), TextColor3 = Color3.fromRGB(255, 230, 170), TextScaled = true, Font = Enum.Font.Arcade, Text = "HANDBOOK" }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, openBtn)

local book = mk("Frame", { Size = UDim2.new(0, 560, 0, 460), Position = UDim2.new(0.5, -280, 0.5, -230), BackgroundColor3 = Color3.fromRGB(214, 202, 168), Visible = false, ZIndex = 9 }, gui)
mk("UICorner", { CornerRadius = UDim.new(0, 12) }, book)
mk("TextLabel", { Size = UDim2.new(1, 0, 0, 44), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(70, 50, 30), TextScaled = true, Font = Enum.Font.Arcade, Text = "MOTEL HANDBOOK — NIGHT SHIFT RULES", ZIndex = 10 }, book)
local rulesText = mk("TextLabel", { Size = UDim2.new(1, -30, 1, -90), Position = UDim2.new(0, 15, 0, 50), BackgroundTransparency = 1, TextColor3 = Color3.fromRGB(45, 35, 25), TextSize = 18, Font = Enum.Font.Gotham, Text = "", TextWrapped = true, TextYAlignment = Enum.TextYAlignment.Top, ZIndex = 10 }, book)
local closeBtn = mk("TextButton", { Size = UDim2.new(0, 110, 0, 34), Position = UDim2.new(0.5, -55, 1, -42), BackgroundColor3 = Color3.fromRGB(70, 50, 30), TextColor3 = Color3.fromRGB(255, 230, 170), TextScaled = true, Font = Enum.Font.Arcade, Text = "CLOSE BOOK", ZIndex = 10 }, book)
mk("UICorner", { CornerRadius = UDim.new(0, 8) }, closeBtn)

local function refresh()
	local txt = ""
	for i = 1, math.min(revealed, #rules) do
		txt = txt .. i .. ". " .. rules[i] .. "\n\n"
	end
	rulesText.Text = txt
end

openBtn.MouseButton1Click:Connect(function()
	book.Visible = not book.Visible
	refresh()
end)
closeBtn.MouseButton1Click:Connect(function()
	book.Visible = false
end)

remotes.StateUpdate.OnClientEvent:Connect(function(s)
	rules = s.ruleTexts or {}
	revealed = s.rules or 3
	if book.Visible then refresh() end
end)

-- HALLUCINATION: handbook text scrambles for 5 seconds at a time
local glyphs = { "#", "%", "&", "@", "?", "/", "\\", "~", "=", "+" }
local function scramble(s)
	local out = {}
	for i = 1, #s do
		local c = s:sub(i, i)
		if c == "\n" or c == " " then
			table.insert(out, c)
		elseif math.random() < 0.55 then
			table.insert(out, glyphs[math.random(#glyphs)])
		else
			table.insert(out, c)
		end
	end
	return table.concat(out)
end

task.spawn(function()
	while true do
		task.wait(math.random(20, 40))
		if _G.NSM_Hallucinating and book.Visible then
			local original = rulesText.Text
			rulesText.Text = scramble(original)
			task.wait(5)
			refresh()
		end
	end
end)
