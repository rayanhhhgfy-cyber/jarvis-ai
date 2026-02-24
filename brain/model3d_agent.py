import requests, json, re
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL

# ── Ultra-intelligent 3D generation system prompt ─────────────────────────────
_SYS_GENERATE = """You are JARVIS, Tony Stark's AI, the world's most advanced 3D modeling assistant.
You generate photorealistic, architecturally accurate, highly detailed 3D scenes.

RULES:
1. Output ONLY a valid JSON array. No markdown, no explanation, no extra text.
2. For complex objects (suits, vehicles, buildings, creatures) use 15-50 objects minimum.
3. Make objects VISUALLY STUNNING — vary colors, add metallic/emissive materials.
4. Position objects precisely so they look like the real thing.
5. All rotations are in radians. Ground is at y=0.
6. Keep JSON compact — avoid unnecessary whitespace.
7. NEVER truncate — output must be valid complete JSON.

Object schema (ALL fields required):
{"name":"string","type":"box|sphere|cylinder|cone|torus|plane","geometry":{...},"position":[x,y,z],"rotation":[x,y,z],"scale":[x,y,z],"material":{"color":"#hex","metalness":0.0-1.0,"roughness":0.0-1.0,"emissive":"#hex","emissiveIntensity":0.0-2.0,"opacity":1.0,"transparent":false}}

Geometry by type:
- box: {"width":n,"height":n,"depth":n}
- sphere: {"radius":n,"widthSegments":32,"heightSegments":32}
- cylinder: {"radiusTop":n,"radiusBottom":n,"height":n,"radialSegments":32}
- cone: {"radius":n,"height":n,"radialSegments":32}
- torus: {"radius":n,"tube":n,"radialSegments":16,"tubularSegments":48}
- plane: {"width":n,"height":n}

DESIGN GUIDELINES:
- Iron Man suits: use metallic gold/red, high metalness(0.9), low roughness(0.1), emissive glow on chest/eyes
- Cars/vehicles: chassis box, wheel cylinders, windows (blue transparent), detailed parts
- Buildings: floors, walls, windows, roof, doors, details
- Characters: torso, limbs, head, clothing details with correct proportions
- Nature: ground plane, tree trunks, canopies, rocks, grass patches, water
- Weapons: barrel, grip, stock, scope, details with correct military colors
- Furniture: separate pieces for each component

ABSOLUTELY use different colors from this palette when asked:
"#ff4444","#ff8800","#ffcc00","#00ff88","#00ccff","#0044ff","#aa00ff","#ff00aa",
"#ff6b6b","#ffd93d","#6bcb77","#4d96ff","#c77dff","#ff9f1c","#2ec4b6","#e71d36"

Output the JSON array now:"""

_SYS_MODIFY = """You are JARVIS, Tony Stark's AI. You modify existing 3D scenes intelligently.

RULES:
1. Output ONLY a valid JSON array containing ALL objects in the final scene.
2. Include unchanged objects exactly as they were.
3. Apply the modification request precisely.
4. NEVER truncate — output must be valid complete JSON.
5. No markdown, no explanation — raw JSON only.

Modification types you handle:
- "add [thing]" → append new objects
- "remove/delete [thing]" → exclude matching objects
- "change color of [thing] to [color]" → update material.color
- "move [thing] [direction]" → update position
- "make [thing] bigger/smaller" → update scale
- "rotate [thing]" → update rotation
- "make it more detailed" → add more objects to existing parts

Output the complete modified JSON array now:"""


def _call(messages, max_tokens=8000):
    if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_YOUR_NEW_KEY_HERE":
        return None, "No API key configured in config.py"
    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({
                "model": GROQ_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.25
            }),
            timeout=60
        )
        r.raise_for_status()
        resp = r.json()
        content = resp["choices"][0]["message"]["content"].strip()
        finish_reason = resp["choices"][0].get("finish_reason", "")
        return content, None, finish_reason
    except Exception as e:
        return None, str(e), ""


def _repair_json(raw):
    """Aggressively repair truncated/malformed JSON arrays from the LLM."""
    # Strip markdown fences
    raw = re.sub(r'^```(?:json)?\s*\n?', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\n?```\s*$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    # Try direct parse first
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data, None
        if isinstance(data, dict):
            if "objects" in data:
                return data["objects"], None
            return [data], None
    except json.JSONDecodeError:
        pass

    # Find the start of the array
    start = raw.find('[')
    if start == -1:
        # Try to find any JSON object and wrap it
        start = raw.find('{')
        if start != -1:
            raw = '[' + raw[start:]
        else:
            return None, "No JSON data found in AI response."
    else:
        raw = raw[start:]

    # Try to extract complete objects from the truncated array
    # Strategy: find all well-formed objects by looking for balanced braces
    objects = []
    depth = 0
    in_string = False
    escape_next = False
    obj_start = -1

    i = 0
    while i < len(raw):
        ch = raw[i]
        if escape_next:
            escape_next = False
        elif ch == '\\' and in_string:
            escape_next = True
        elif ch == '"' and not escape_next:
            in_string = not in_string
        elif not in_string:
            if ch == '{':
                depth += 1
                if depth == 1:
                    obj_start = i
            elif ch == '}':
                depth -= 1
                if depth == 0 and obj_start != -1:
                    obj_str = raw[obj_start:i+1]
                    try:
                        obj = json.loads(obj_str)
                        # Validate it looks like a 3D object
                        if "type" in obj and "position" in obj:
                            objects.append(obj)
                    except json.JSONDecodeError:
                        pass
                    obj_start = -1
        i += 1

    if objects:
        return objects, None

    # Last resort: try to close the array and parse
    repaired = raw.rstrip().rstrip(',').rstrip()
    # Count open/close braces outside strings
    open_b = repaired.count('{') - repaired.count('}')
    open_sq = repaired.count('[') - repaired.count(']')
    repaired += '}' * max(0, open_b) + ']' * max(0, open_sq)
    try:
        data = json.loads(repaired)
        if isinstance(data, list):
            return data, None
    except json.JSONDecodeError:
        pass

    return None, "Could not parse 3D model data — try a simpler request or fewer objects."


def generate(prompt):
    """Generate 3D model objects from a text prompt with smart chunking for large requests."""
    msg = f"Request: {prompt}\n\nOutput the JSON array now:"
    raw, err, finish_reason = _call([
        {"role": "system", "content": _SYS_GENERATE},
        {"role": "user", "content": msg}
    ], max_tokens=8000)

    if err:
        return {"objects": [], "error": err, "success": False}

    objects, parse_err = _repair_json(raw)
    if parse_err:
        return {"objects": [], "error": parse_err, "raw": raw[:300], "success": False}

    # Post-process: ensure all required fields exist
    objects = [_sanitize_object(obj, i) for i, obj in enumerate(objects) if isinstance(obj, dict)]
    objects = [o for o in objects if o is not None]

    if not objects:
        return {"objects": [], "error": "AI returned no valid 3D objects. Try rephrasing your request.", "success": False}

    return {
        "objects": objects,
        "count": len(objects),
        "success": True,
        "was_truncated": finish_reason == "length"
    }


def modify(prompt, current_scene):
    """Modify an existing scene based on a text prompt."""
    # Compact the scene JSON to save tokens
    scene_json = json.dumps(current_scene, separators=(',', ':'))
    # Truncate if too long to avoid context overflow
    if len(scene_json) > 4000:
        scene_json = json.dumps(current_scene[:20], separators=(',', ':'))
        scene_json += "  // ... (showing first 20 objects)"

    msg = (
        f"Current scene:\n{scene_json}\n\n"
        f"Modification: {prompt}\n\n"
        f"Output complete modified JSON array now:"
    )
    raw, err, finish_reason = _call([
        {"role": "system", "content": _SYS_MODIFY},
        {"role": "user", "content": msg}
    ], max_tokens=8000)

    if err:
        return {"objects": [], "error": err, "success": False}

    objects, parse_err = _repair_json(raw)
    if parse_err:
        return {"objects": [], "error": parse_err, "raw": raw[:300], "success": False}

    objects = [_sanitize_object(obj, i) for i, obj in enumerate(objects) if isinstance(obj, dict)]
    objects = [o for o in objects if o is not None]

    if not objects:
        return {"objects": [], "error": "No valid objects returned.", "success": False}

    return {"objects": objects, "count": len(objects), "success": True}


def _sanitize_object(obj, index):
    """Ensure object has all required fields with sensible defaults."""
    if not isinstance(obj, dict):
        return None

    # Must have a type
    obj_type = obj.get("type", "box")
    if obj_type not in ("box", "sphere", "cylinder", "cone", "torus", "plane"):
        obj_type = "box"

    # Default geometries
    default_geoms = {
        "box":      {"width": 1, "height": 1, "depth": 1},
        "sphere":   {"radius": 0.5, "widthSegments": 32, "heightSegments": 32},
        "cylinder": {"radiusTop": 0.5, "radiusBottom": 0.5, "height": 1, "radialSegments": 32},
        "cone":     {"radius": 0.5, "height": 1, "radialSegments": 32},
        "torus":    {"radius": 0.5, "tube": 0.2, "radialSegments": 16, "tubularSegments": 48},
        "plane":    {"width": 2, "height": 2},
    }

    def ensure_list(val, default, length=3):
        if isinstance(val, list) and len(val) == length:
            return [float(v) if v is not None else 0.0 for v in val]
        return default

    mat = obj.get("material", {}) or {}

    return {
        "name":     str(obj.get("name", f"Object_{index + 1}")),
        "type":     obj_type,
        "geometry": obj.get("geometry") or default_geoms[obj_type],
        "position": ensure_list(obj.get("position"), [0.0, 0.0, 0.0]),
        "rotation": ensure_list(obj.get("rotation"), [0.0, 0.0, 0.0]),
        "scale":    ensure_list(obj.get("scale"), [1.0, 1.0, 1.0]),
        "material": {
            "color":             str(mat.get("color", "#00d4ff")),
            "metalness":         float(mat.get("metalness", 0.3)),
            "roughness":         float(mat.get("roughness", 0.5)),
            "emissive":          str(mat.get("emissive", "#000000")),
            "emissiveIntensity": float(mat.get("emissiveIntensity", 0.0)),
            "opacity":           float(mat.get("opacity", 1.0)),
            "transparent":       bool(mat.get("transparent", False))
        }
    }
