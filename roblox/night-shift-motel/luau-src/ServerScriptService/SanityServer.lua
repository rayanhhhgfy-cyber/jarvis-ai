-- SanityServer: per-player sanity, coffee, warmer (20 min real-time), hallucination flag.
local Players = game:GetService("Players")

local SanityServer = {}
local ctx, Config, Remotes, State, Map
local values = {}

function SanityServer.Init(c)
	ctx = c
	Config = c.Config
	Remotes = c.Remotes
	State = c.State
	Map = c.Map

	Map.CoffeeBuyPrompt.Triggered:Connect(function(player)
		local price = SanityServer.GetCoffeePrice()
		if State.money < price and not State.toggles.infiniteMoney then
			ctx.notify(player, "Not enough money for coffee ($" .. price .. ").", "bad")
			return
		end
		if not State.toggles.infiniteMoney then
			State.money = State.money - price
		end
		SanityServer.Recover(player, Config.CoffeeSanity)
		ctx.notify(player, "Coffee bought: +" .. Config.CoffeeSanity .. " sanity.", "good")
		ctx.Controls.log("Coffee purchased by " .. player.Name .. " (-$" .. price .. ")")
		ctx.sendState()
	end)

	Map.WarmerDrinkPrompt.Triggered:Connect(function(player)
		if not State.toggles.instantCoffee and workspace:GetServerTimeNow() < State.warmerReadyAt then return end
		SanityServer.Recover(player, Config.WarmerSanity)
		ctx.notify(player, "Fresh pot: +" .. Config.WarmerSanity .. " sanity. The warmer starts a new pot.", "good")
		State.warmerReadyAt = workspace:GetServerTimeNow() + Config.WarmerMinutes * 60
		Map.WarmerDrinkPrompt.Enabled = false
		ctx.sendState()
	end)

	task.spawn(function()
		while true do
			task.wait(1)
			local ready = State.toggles.instantCoffee or workspace:GetServerTimeNow() >= State.warmerReadyAt
			if ready and not Map.WarmerDrinkPrompt.Enabled then
				Map.WarmerDrinkPrompt.Enabled = true
				ctx.VFX.Play("bell", Map.Warmer, 1, 1.3)
				ctx.notify(nil, "COFFEE READY — free pot at the warmer!", "good")
				ctx.sendState()
			elseif not ready and Map.WarmerDrinkPrompt.Enabled and not State.toggles.instantCoffee then
				Map.WarmerDrinkPrompt.Enabled = false
			end
		end
	end)
end

function SanityServer.GetCoffeePrice()
	return State.coffeePrice or Config.CoffeePrice
end

function SanityServer.AddPlayer(player)
	values[player] = 100
	Remotes.Sanity:FireClient(player, 100)
end

function SanityServer.RemovePlayer(player)
	values[player] = nil
end

local function push(player)
	local v = values[player] or 100
	Remotes.Sanity:FireClient(player, v)
	Remotes.Hallucinate:FireClient(player, v <= 0)
end

function SanityServer.Get(player)
	return values[player] or 100
end

function SanityServer.Drain(player, amount, reason)
	if State.toggles.noSanityDrain and amount > 0 then return end
	if not values[player] then values[player] = 100 end
	values[player] = math.clamp(values[player] - amount, 0, 100)
	push(player)
end

function SanityServer.Recover(player, amount)
	if not values[player] then values[player] = 100 end
	values[player] = math.clamp(values[player] + amount, 0, 100)
	push(player)
end

function SanityServer.Set(player, v)
	values[player] = math.clamp(v, 0, 100)
	push(player)
end

function SanityServer.RefillAll()
	for _, pl in ipairs(Players:GetPlayers()) do
		SanityServer.Set(pl, 100)
	end
end

function SanityServer.GetValues()
	return values
end

return SanityServer
