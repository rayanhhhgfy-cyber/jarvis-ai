#!/usr/bin/env python3
"""Assemble NightShiftMotel.rbxlx from the build/ folder of Luau sources."""
import os
from xml.sax.saxutils import escape

BUILD = "/workspace/build"
OUT = "/workspace/NightShiftMotel.rbxlx"

_ref = [0]
def ref():
    _ref[0] += 1
    return f"RBX{_ref[0]}"

def script_item(class_name, name, source):
    return (
        f'<Item class="{class_name}" referent="{ref()}">'
        f'<Properties><string name="Name">{escape(name)}</string>'
        f'<ProtectedString name="Source">{escape(source)}</ProtectedString>'
        f"</Properties></Item>"
    )

def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def color3(r, g, b):
    return f'<Color3 name="X"><R>{r}</R><G>{g}</G><B>{b}</B></Color3>'

def prop_color3(name, r, g, b):
    return f'<Color3 name="{name}"><R>{r}</R><G>{g}</G><B>{b}</B></Color3>'

parts = []
parts.append(
    '<roblox xmlns:xmime="http://schemas.microsoft.com/2003/10/Serialization/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4">'
)

# ---------------- ReplicatedStorage ----------------
rs_items = []
rsd = os.path.join(BUILD, "ReplicatedStorage")
for fn in sorted(os.listdir(rsd)):
    if fn.endswith(".lua"):
        rs_items.append(script_item("ModuleScript", fn[:-4], read(os.path.join(rsd, fn))))
parts.append(f'<Item class="ReplicatedStorage" referent="{ref()}"><Properties><string name="Name">ReplicatedStorage</string></Properties>' + "".join(rs_items) + "</Item>")

# ---------------- ServerScriptService ----------------
sss_items = []
sssd = os.path.join(BUILD, "ServerScriptService")
for fn in sorted(os.listdir(sssd)):
    if not fn.endswith(".lua"):
        continue
    src = read(os.path.join(sssd, fn))
    if fn.endswith(".server.lua"):
        sss_items.append(script_item("Script", fn[: -len(".server.lua")], src))
    else:
        sss_items.append(script_item("ModuleScript", fn[:-4], src))
parts.append(f'<Item class="ServerScriptService" referent="{ref()}"><Properties><string name="Name">ServerScriptService</string></Properties>' + "".join(sss_items) + "</Item>")

# ---------------- StarterPlayer / StarterPlayerScripts ----------------
sp_items = []
spd = os.path.join(BUILD, "StarterPlayerScripts")
for fn in sorted(os.listdir(spd)):
    if fn.endswith(".client.lua"):
        sp_items.append(script_item("LocalScript", fn[:-11], read(os.path.join(spd, fn))))
sps = f'<Item class="StarterPlayerScripts" referent="{ref()}"><Properties><string name="Name">StarterPlayerScripts</string></Properties>' + "".join(sp_items) + "</Item>"
parts.append(f'<Item class="StarterPlayer" referent="{ref()}"><Properties><string name="Name">StarterPlayer</string></Properties>{sps}</Item>')

# ---------------- StarterGui (empty; GUIs are built by code) ----------------
parts.append(f'<Item class="StarterGui" referent="{ref()}"><Properties><string name="Name">StarterGui</string><bool name="ResetPlayerGuiOnSpawn">false</bool></Properties></Item>')

# ---------------- SoundService ----------------
parts.append(f'<Item class="SoundService" referent="{ref()}"><Properties><string name="Name">SoundService</string><bool name="AmbientReverb">false</bool></Properties></Item>'.replace('<bool name="AmbientReverb">false</bool>', '<token name="AmbientReverb">0</token>'))

# ---------------- Lighting ----------------
lighting = (
    f'<Item class="Lighting" referent="{ref()}"><Properties>'
    '<string name="Name">Lighting</string>'
    + prop_color3("Ambient", 0.03, 0.03, 0.05)
    + prop_color3("OutdoorAmbient", 0.07, 0.09, 0.13)
    + '<float name="Brightness">0.6</float>'
    + '<float name="ClockTime">0</float>'
    + '<bool name="GlobalShadows">true</bool>'
    + '<float name="ExposureCompensation">0.1</float>'
    + '<Color3 name="FogColor"><R>0.05</R><G>0.06</G><B>0.09</B></Color3>'
    + '<float name="FogStart">40</float><float name="FogEnd">320</float>'
    + "</Properties>"
    + f'<Item class="Atmosphere" referent="{ref()}"><Properties>'
    + '<string name="Name">Atmosphere</string>'
    + '<float name="Density">0.42</float><float name="Offset">0.25</float>'
    + '<float name="Haze">2</float><float name="Glare">0</float>'
    + '<Color3 name="Color"><R>0.47</R><G>0.49</G><B>0.53</B></Color3>'
    + '<Color3 name="Decay"><R>0.2</R><G>0.2</G><B>0.25</B></Color3>'
    + "</Properties></Item>"
    + "</Item>"
)
parts.append(lighting)

# ---------------- Workspace ----------------
parts.append(f'<Item class="Workspace" referent="{ref()}"><Properties><string name="Name">Workspace</string></Properties></Item>')

parts.append("</roblox>")

xml = "".join(parts)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(xml)
print(f"Wrote {OUT} ({os.path.getsize(OUT)} bytes)")
