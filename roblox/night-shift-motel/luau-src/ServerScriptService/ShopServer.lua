-- ShopServer: dawn shop — buy Desk 2 and Desk 3 with in-game money only.
local Players = game:GetService("Players")

local ShopServer = {}
local ctx, Config, Remotes, State, Map

function ShopServer.Init(c)
	ctx = c
	Config = c.Config
	Remotes = c.Remotes
	State = c.State
	Map = c.Map
end

function ShopServer.Handle(player, action, data)
	if action ~= "buyDesk" then return end
	local slot = tonumber(data)
	if slot ~= 2 and slot ~= 3 then return end
	if State.phase ~= "Dawn" and State.phase ~= "Shop" then
		ctx.notify(player, "The shop is only open at dawn.", "bad")
		return
	end
	if slot <= State.desksBought then
		ctx.notify(player, "That desk is already yours.", "info")
		return
	end
	if slot ~= State.desksBought + 1 then
		ctx.notify(player, "Buy the desks in order.", "bad")
		return
	end
	if #Players:GetPlayers() < slot then
		ctx.notify(player, "Needs a friend to sit here.", "bad")
		return
	end
	local price = Config.DeskPrices[slot]
	if State.money < price and not State.toggles.infiniteMoney then
		ctx.notify(player, "Not enough money ($" .. price .. " needed).", "bad")
		return
	end
	if not State.toggles.infiniteMoney then
		State.money = State.money - price
	end
	State.desksBought = slot
	ctx.Controls.setDeskBought(slot, true)
	ctx.notify(nil, "Desk " .. slot .. " installed! Sit there to serve your own guests.", "good")
	ctx.Controls.log("Desk " .. slot .. " purchased for $" .. price)
	ctx.sendState()
end

return ShopServer
