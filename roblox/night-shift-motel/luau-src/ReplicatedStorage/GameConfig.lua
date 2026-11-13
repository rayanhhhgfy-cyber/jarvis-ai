local Config = {}

Config.AdminUserId = 6157267885

Config.StartMoney = 50
Config.CurrentYear = 2025
Config.MaxDesks = 3
Config.DeskPrices = { [2] = 150, [3] = 300 }
Config.CoffeePrice = 5
Config.CoffeeSanity = 30
Config.WarmerSanity = 50
Config.WarmerMinutes = 20
Config.HuntSeconds = 60
Config.MonsterSpeed = 16
Config.DoorBreakSeconds = 10
Config.BarricadeBonus = 5
Config.RoomNumbers = { 101, 102, 103, 104, 105, 106 }
Config.CleanBonusMoney = 10
Config.CleanBonusRep = 5
Config.OverstayChance = 0.25
Config.AngryReturnChance = 0.35
Config.NextGuestDelay = 5

Config.AdmitHumanMoney = 20
Config.AdmitHumanRep = 10
Config.DenyHumanMoney = -10
Config.DenyHumanRep = -15
Config.DenyMonsterMoney = 10
Config.DenyMonsterRep = 10

Config.Nights = {
	{ guests = 5, monsters = 1, newRules = 0, lieSkill = 1, flicker = false, hints = true },
	{ guests = 6, monsters = 2, newRules = 1, lieSkill = 1, flicker = false, hints = false, cameraOnly = true },
	{ guests = 7, monsters = 2, newRules = 2, lieSkill = 2, flicker = false, hints = false },
	{ guests = 8, monsters = 3, newRules = 1, lieSkill = 2, flicker = true, hints = false },
	{ guests = 10, monsters = 4, newRules = 2, lieSkill = 3, flicker = true, hints = false },
}

Config.Tells = {
	{ id = "ExtraFinger", cat = "Hands", label = "Six fingers on one hand" },
	{ id = "LongHands", cat = "Hands", label = "Hands are too long" },
	{ id = "BlackEyes", cat = "Face", label = "Solid black eyes" },
	{ id = "NoReflection", cat = "Face", label = "No reflection in the mirror" },
	{ id = "TooManyTeeth", cat = "Face", label = "Too many teeth" },
	{ id = "PaleSkin", cat = "Face", label = "Skin too pale" },
	{ id = "ShadowWrong", cat = "Face", label = "Shadow the wrong shape" },
	{ id = "WrongYear", cat = "Papers", label = "Said the wrong year" },
	{ id = "NameMismatch", cat = "Papers", label = "Name does not match the ID" },
	{ id = "NoCamera", cat = "Camera", label = "Does not appear on camera" },
	{ id = "DistortedCam", cat = "Camera", label = "Looks wrong on camera" },
}

Config.Rules = {
	"Count the fingers. A guest with six fingers on one hand is not human. (Hands)",
	"Look at the eyes. Solid black eyes are not human. (Face)",
	"Answers must match the ID. A guest who says the wrong year, or whose name does not match the ID card, is not human. (Papers)",
	"Watch the cameras. Some things do not appear on camera at all. (Camera)",
	"Look closely at the face. Too many teeth, skin too pale, or a shadow with the wrong shape is not human. (Face)",
	"Look at the hands. Hands that are too long are not hands. (Hands)",
	"THE 2-CATEGORY RULE: a guest is a confirmed monster only when you find tells in TWO different categories. One tell alone is only suspicion. Keep investigating.",
	"Some guests show nothing at all. If the cameras show nobody standing at the desk, turn that guest away. (Camera)",
	"When you are tired you cannot trust your eyes. Drink coffee, and trust the handbook instead. (Sanity)",
}

Config.Questions = {
	{ id = "from", text = "Where are you traveling from?" },
	{ id = "id", text = "Can I see your ID?" },
	{ id = "year", text = "What year is it?" },
}

Config.ExtraQuestions = {
	{ id = "job", text = "What is your job?" },
	{ id = "stay", text = "How long are you staying?" },
}

Config.FirstNames = {
	"Harold", "Vera", "Dale", "Ruth", "Clyde", "Mabel", "Otis", "June",
	"Roy", "Edna", "Walt", "Ida", "Gus", "Pearl", "Hank", "Elsie",
	"Cecil", "Opal", "Vern", "Hazel", "Amos", "Lois", "Dewey", "Fay",
}

Config.LastNames = {
	"Carter", "Whitlock", "Mason", "Dell", "Hargrove", "Pike", "Slade", "Fenwick",
	"Boone", "Crane", "Vance", "Holt", "Marsh", "Keller", "Doyle", "Reyes",
}

Config.Cities = {
	"Ridgeville", "Cedar Falls", "Milton", "Ashgrove", "Fairview", "Kettle Creek",
	"Dry Gulch", "Larkspur", "Halloway", "Stonebridge",
}

Config.Jobs = {
	"Electrician", "Trucker", "Nurse", "Salesman", "Mechanic", "Teacher",
	"Line cook", "Mail carrier", "Welder", "Store clerk",
}

Config.Stays = { "1 night", "2 nights", "3 nights", "the weekend", "just tonight" }

Config.CreepyLines = {
	"From where the road ends.",
	"You would not know it.",
	"From a long way back.",
	"Down past the tree line.",
	"I have always been close by.",
	"Does it matter?",
}

Config.CreepyJobs = {
	"I fix things.",
	"I visit people.",
	"Night work.",
	"It is hard to explain.",
	"I was asked not to say.",
}

Config.CreepyStays = {
	"Until it is over.",
	"Just tonight. Maybe forever.",
	"As long as you will have me.",
	"I will know when to leave.",
}

Config.Objectives = {
	"Check every guest. Survive until morning.",
	"The cameras are your only chance against the ones with no tells.",
	"Monsters lie better now. Trust two categories, not one.",
	"Power flickers tonight. Do not panic when the lights die.",
	"The last night. Everything at once. Survive until dawn.",
}

return Config
