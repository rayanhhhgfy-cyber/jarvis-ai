# Night Shift Motel (working title)

A complete co-op Roblox horror game (1–3 players): night shift at a roadside motel, some guests are monsters pretending to be human. Inspired by the mechanics shown in the "Shift at Midnight"-style trailer reel — **original game, original name, original characters, original art. Nothing is copied from Motel 9.**

**Deliverable:** `NightShiftMotel.rbxlx` — open it in Roblox Studio (File → Open from File) and press Play. The entire map is built at runtime from Parts by `MapBuilder`, so nothing is missing.

---

## 1. Design doc — the full loop

- **Core loop:** guest walks in → "GUEST ARRIVED" + bell → no timer → investigate with 4 tools (INSPECT / QUESTIONS / CAMERAS / HANDBOOK) → GIVE ROOM KEY or TURN AWAY → consequences applied instantly → next guest 5 s later → night ends when the queue is empty → hunt phase if any monster was admitted → dawn → morning chores → shop → next night.
- **Tells (11, all enforced in code):** 6 fingers (Hands), hands too long (Hands), black eyes (Face), no reflection (Face), too many teeth (Face), skin too pale (Face), shadow the wrong shape (Face), wrong-year answer (Papers), name does not match ID (Papers), absent on camera (Camera), distorted on camera (Camera).
- **2-CATEGORY RULE** is Handbook rule 7 and is enforced by generation: monsters spawn with 2–4 tells across **at least 2 different categories**; humans have zero tells.
- **Camera-only monster** (Night 2+): zero visible tells, absent on camera — only the cameras can catch it.
- **Consequences:** admit human +$20 / +10 rep · turn away human −$10 / −15 rep (+35% chance it returns angry) · admit monster +$0, takes a room, light flickers, knocking, counts toward the hunt · turn away monster +$10 / +10 rep.
- **Reputation:** raw number, shown as 1–5 stars (`clamp(ceil(rep/20),1,5)`, never below 1 star), gives `rep × $1` starting bonus each night and the final rating.
- **Nights:** N1 5 guests/1 monster/3 rules/tutorial · N2 6/2/+1 rule/camera-only monster · N3 7/2/+2 rules/monsters lie better · N4 8/3/+1 rule/power flickers (lights out 10 s, cameras static) · N5 10/4/+2 rules/everything.
- **Hunt:** red lights, alarm, "LOCKDOWN — SOMETHING IS IN THE ROOMS", monsters chase at player walk speed (never faster), doors take 10 s to break (barricade chair +5 s), touch = downed, all downed = game over with Retry (money/rep restored to night start). Survive 60 s → dawn, monsters dissolve.
- **Morning chores:** each admitted monster eats 1 random admitted human → room turns **messy** (luggage, tipped bed, dark stain; hold Clean 5 s). Each surviving admitted human has a 25% chance to be an **overstayer** (argues; only the firm answer works). Dirty/occupied rooms can't take guests; zero clean rooms disables GIVE ROOM KEY. All chores done: +$10, +5 rep.
- **Sanity (per player, 0–100):** −5 spotted tell, −15 admit monster, −5 turn away human, −5 power flicker, −1/s during hunt. Recover only via coffee ($5, +30, coffee corner) or the free warmer pot (+50, brews every 20 real minutes, timer persists across nights, progress shown in the HUD). At 0: screen warp, color shift, whispers, fake guests that vanish on inspection, fake tells on real guests, scrambled handbook, fake monsters on cameras — visual/audio only, never changes real data.
- **Co-op:** shared money/rep/handbook, up to 3 desks (one per player), quick-chat buttons, Roblox's built-in proximity voice (nothing custom).
- **Desks:** Desk 1 free; Desk 2 $150, Desk 3 $300, bought at the dawn shop with in-game money only. Greyed out in solo play ("needs a friend to sit here").
- **Win / lose:** survive Night 5 → "YOU SURVIVED ALL 5 NIGHTS" + money + stars + play again. All players caught → retry the same night.

## 2. Map build list (all built from Parts by `ServerScriptService/MapBuilder`)

| Zone | Size / position (studs) | Contents |
|---|---|---|
| Parking lot | asphalt 220×200 plate, y=0, wet look (Reflectance 0.12) | 5 marked spots, sidewalk, walkway |
| Road | 240×26 at z=84 | center stripes, streetlamp (neon head + PointLight) |
| Lobby | 64×42 interior, x −32..32, z −22..18 | black/white checkered floor (4×4 tiles), wood walls, glass windows, 4 flickering ceiling lights |
| Front counter | 30×4×3 at z=−14 | space for **3 desks** at x = −10, 0, +10: bell, guest register, green lamp, Seat + Sit prompt each; key board with 6 keys on the wall behind |
| Coffee corner | x 25..31, z −18..−13 | coffee machine (Buy prompt, $5), free-pot warmer (Drink prompt, HUD countdown), cups |
| Dressing | around lobby | vending machine, ice machine, wall TV, wall phone, table + chairs, suitcase, wall clock, portraits, house-rules frame, lantern, candelabra, radio, typewriter |
| Security room | 10×10 front-left corner of lobby | 4 CCTV monitors, open/close metal door |
| Corridor | 64×12 at z −22..−34 | neon strip light |
| Guest rooms | 6 rooms 10×12 (z −34..−46), doors at x = −25…+25 | bed + pillow, wall lamp, TV, bathroom door, chair (barricade prop), ceiling light, numbered door with Open/Close + Lock prompts |
| MOTEL sign | pole at (−45, z 62) | red neon MOTEL board, green number board, neon accent bars, VACANCY board (flips to NO VACANCY) — **built from Parts, not the paid kit** |
| Trees | 10 pines around the lot | trunk + 3 stacked canopy blocks |
| Cameras | 4 invisible parts | CAM 01 Entrance, CAM 02 Parking, CAM 03 Corridor, CAM 04 Lobby |
| Spawn | SpawnLocation at (0, 50) | players arrive in the lot |

Atmosphere fog, night lighting and rain are set by `VFXServer` (rain uses the verified free decal `rbxassetid://241876428`).

## 3. Where every script goes (already correct inside the rbxlx)

| Location | Script | Type |
|---|---|---|
| ReplicatedStorage | `GameConfig` | ModuleScript (all numbers, tells, rules, questions) |
| ServerScriptService | `Main` | Script (state machine, guest flow, decisions) |
| ServerScriptService | `MapBuilder`, `GuestGen`, `VFXServer`, `SanityServer`, `HuntManager`, `ChoresServer`, `ShopServer`, `AdminServer` | ModuleScripts |
| StarterPlayer → StarterPlayerScripts | `HUD`, `DeskClient`, `InspectClient`, `HandbookClient`, `CamerasClient`, `SanityClient`, `DawnShopClient`, `AdminClient` | LocalScripts |

## 4. Assets

**Used in the file (verified only):**
- Rain: `ParticleEmitter` with the free **raindrop v3** decal, asset ID **241876428** (as specified).
- All sounds are Roblox **built-in `rbxasset://` files** (bell ding, click, lock snap, static, glass break, rumble/drone, dawn sting, caught grunt) — no invented IDs, no copyrighted music. To upgrade sounds later, search the Toolbox audio for free: `thunder`, `rain loop`, `heartbeat`, `whisper`, `alarm loop`, `knocking` — and swap the IDs in `VFXServer` (`builtins` table).

**The 3 packs (import in Studio — FBX/OBJ cannot be embedded in an rbxlx):**
1. Download `night-shift-motel-assets.zip` (the link you have) and unzip.
2. In Studio: **Avatar/Home tab → Import 3D** (3D Importer), select the FBX files from `PSX Hotel Kit Free` (guest rooms: bed, door, key, portrait, house rules, dead bellboy prop), `PSX Roadside Horror Kit sample` (motel shell, vending machine, street lamp), and `Ashgrove Horror Prop Sampler` (service bell, guest register, room key, lantern, candelabra, radio, suitcase, typewriter, wall clock, ice machine — see its `manifest.json`).
3. Place them over the Parts props (same positions as the table above), then delete the Part stand-ins.
4. **Delete any scripts inside imported/free models** (check for Script children in the Explorer).

**Required credit (Settings → Game Settings → About, or in-game credits):**
> PSX Hotel Kit Free by heyheythere - https://heyheythere.itch.io/psx-hotel-kit-free - CC BY 4.0

**Doors Hardcore Remaster** (Creator Store, asset 12263106166, already in your Toolbox inventory) is a reference/entities pack — insert it from Toolbox if you want its entities; it is not required for this game to run.

**No other assets are used. No invented IDs. No paid models. No AI-generated images.**

## 5. Admin panel (erdl18 only)

- Top-right **ADMIN** button + chat command `:admin` — both only exist for **UserId 6157267885**. The server re-checks `UserId == 6157267885` on **every** admin RemoteEvent and ignores/logs anything else; username is never used.
- Tabs: GAME (start/pause/end/set night/skip/restart/skip dawn/win/lose/reset), GUESTS (spawn, force human/monster, remove, clear queue, quotas), ECONOMY (money/rep/sanity per player, refill, coffee price), DESKS (give/remove/unlock, prices), HUNT (start/stop, spawn monster, timer, speed), MAP (rain, fog, sign + color, lights, flicker, doors, teleports), PLAYERS (live list, teleport, heal, kick), TOGGLES (god, infinite money, no sanity drain, instant warmer, freeze guests), LOG (full history of admits, hunts, purchases).

## 6. Save policy

Money/reputation/nights persist **for the whole server session only**. No DataStore is used, so nothing breaks if API access is disabled — restart the server to reset.

## 7. Test checklist

- [ ] **Night 1 solo:** sit at Desk 1, serve 5 guests, admit humans (+$20 each), dawn summary, no hunt.
- [ ] **Monster admitted on purpose** (admin → GUESTS → FORCE NEXT: MONSTER → ADMIT): room light flickers, knocking, hunt triggers at queue end.
- [ ] **Human turned away:** −$10/−15 rep, may return angry (louder bell, faster walk).
- [ ] **Camera check:** CAM 01–04 views with static + labels; camera-only monster shows an empty desk.
- [ ] **Hunt phase:** red lights, alarm, chase, hide in room + lock + barricade (10 s + 5 s), survive 60 s → dawn.
- [ ] **Phone test:** every button is a big touch button; prompts (Sit/Buy/Drink/Clean/Tell to leave) work with tap-and-hold.
- [ ] **Desk 2 with 2 players:** dawn shop → BUY DESK 2 ($150), desk appears, second player sits and serves their own guest. Solo → greyed out "needs a friend".
- [ ] **Sanity → 0** (admin → ECONOMY → SET MY SANITY 0): screen warps, whispers, fake guests vanish on inspection, handbook scrambles, fake tells appear.
- [ ] **Coffee:** Buy at the corner → +30 sanity. **Warmer:** pot ready after 20 min (or admin → INSTANT COFFEE WARMER to test) → Drink → +50.
- [ ] **Admin panel:** opens only for erdl18 (button + `:admin`); a second account has no button and `:admin` does nothing; test SET NIGHT, SPAWN MONSTER, SET MONEY, START HUNT — all take effect.
- [ ] **Morning chores:** admit a monster + a human the same night → at dawn the human's room is messy (Clean holds 5 s) and/or an overstayer argues and leaves only with the firm answer; all chores → +$10/+5 rep; with all rooms dirty, GIVE ROOM KEY shows "NO CLEAN ROOMS".
- [ ] **Win:** survive Night 5 → final screen with money + stars → PLAY AGAIN resets to Night 1.
