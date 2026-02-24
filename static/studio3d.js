"use strict";

/* ══════════════════════════════════════════════════════════════
   J.A.R.V.I.S — 3D Studio Engine
   Three.js viewport, AI generation, editing, export
   ══════════════════════════════════════════════════════════════ */

// ── Globals ──────────────────────────────────────────────────
let scene, camera, renderer, controls, transformControls;
let raycaster, mouse;
let sceneObjects = [];   // { mesh, data }
let selectedObject = null;
let transformMode = "translate";
let gridHelper, ambientLight, dirLight;

// DOM refs
const canvasContainer = document.getElementById("s3d-canvas-container");
const sceneList = document.getElementById("s3d-scene-list");
const aiMessages = document.getElementById("s3d-ai-messages");
const aiPrompt = document.getElementById("s3d-ai-prompt");
const btnGenerate = document.getElementById("s3d-btn-generate");
const btnModify = document.getElementById("s3d-btn-modify");
const propsContainer = document.getElementById("s3d-props");
const viewportStats = document.getElementById("s3d-viewport-stats");
const projectList = document.getElementById("s3d-project-list");
const jsonInput = document.getElementById("s3d-json-input");
const btnSaveProject = document.getElementById("s3d-save-project");
const btnUploadJson = document.getElementById("s3d-upload-json");
const btnRefreshProj = document.getElementById("s3d-refresh-projects");


// ── Three.js Init ────────────────────────────────────────────
function initScene() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x040a14);
  scene.fog = new THREE.FogExp2(0x040a14, 0.035);

  // Camera
  camera = new THREE.PerspectiveCamera(60, canvasContainer.clientWidth / canvasContainer.clientHeight, 0.1, 1000);
  camera.position.set(5, 4, 8);
  camera.lookAt(0, 0, 0);

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setSize(canvasContainer.clientWidth, canvasContainer.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;
  canvasContainer.appendChild(renderer.domElement);

  // Orbit controls
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 1;
  controls.maxDistance = 100;
  controls.maxPolarAngle = Math.PI * 0.85;

  // Transform controls
  transformControls = new THREE.TransformControls(camera, renderer.domElement);
  transformControls.setMode("translate");
  transformControls.addEventListener("dragging-changed", e => {
    controls.enabled = !e.value;
  });
  transformControls.addEventListener("objectChange", () => {
    if (selectedObject) {
      const m = selectedObject.mesh;
      selectedObject.data.position = [m.position.x, m.position.y, m.position.z];
      selectedObject.data.rotation = [m.rotation.x, m.rotation.y, m.rotation.z];
      selectedObject.data.scale = [m.scale.x, m.scale.y, m.scale.z];
      updatePropsPanel();
    }
  });
  scene.add(transformControls);

  // Grid
  gridHelper = new THREE.GridHelper(20, 20, 0x003344, 0x001a22);
  scene.add(gridHelper);

  // Ground plane (invisible, for shadows)
  const groundGeo = new THREE.PlaneGeometry(40, 40);
  const groundMat = new THREE.ShadowMaterial({ opacity: 0.3 });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  ground.userData.isGround = true;
  scene.add(ground);

  // Lighting
  ambientLight = new THREE.AmbientLight(0x334466, 0.6);
  scene.add(ambientLight);

  dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
  dirLight.position.set(8, 12, 8);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 2048;
  dirLight.shadow.mapSize.height = 2048;
  dirLight.shadow.camera.near = 0.5;
  dirLight.shadow.camera.far = 50;
  dirLight.shadow.camera.left = -15;
  dirLight.shadow.camera.right = 15;
  dirLight.shadow.camera.top = 15;
  dirLight.shadow.camera.bottom = -15;
  scene.add(dirLight);

  const hemi = new THREE.HemisphereLight(0x0088cc, 0x002244, 0.3);
  scene.add(hemi);

  // Raycaster
  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  // Events
  renderer.domElement.addEventListener("click", onCanvasClick);
  window.addEventListener("resize", onResize);
  window.addEventListener("keydown", onKeyDown);

  animate();
  updateStats();
}

// ── Animation Loop ───────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

// ── Resize ───────────────────────────────────────────────────
function onResize() {
  const w = canvasContainer.clientWidth;
  const h = canvasContainer.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

// ── Keyboard shortcuts ──────────────────────────────────────
function onKeyDown(e) {
  if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
  if (e.key === "w" || e.key === "W") setTransformMode("translate");
  if (e.key === "e" || e.key === "E") setTransformMode("rotate");
  if (e.key === "r" || e.key === "R") setTransformMode("scale");
  if (e.key === "Delete" || e.key === "Backspace") deleteSelected();
  if (e.key === "Escape") deselectAll();
}

// ── Object Selection ─────────────────────────────────────────
function onCanvasClick(e) {
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const meshes = sceneObjects.map(o => o.mesh);
  const intersects = raycaster.intersectObjects(meshes, true);

  if (intersects.length > 0) {
    let hitMesh = intersects[0].object;
    // Walk up to find the root user mesh
    while (hitMesh.parent && !sceneObjects.find(o => o.mesh === hitMesh)) {
      hitMesh = hitMesh.parent;
    }
    const obj = sceneObjects.find(o => o.mesh === hitMesh);
    if (obj) selectObject(obj);
  } else {
    deselectAll();
  }
}

function selectObject(obj) {
  deselectAll();
  selectedObject = obj;

  // Highlight all meshes in the hierarchy
  obj.mesh.traverse(child => {
    if (child.isMesh && child.material) {
      // Store original emissive if not already stored
      if (child.userData.origEmissive === undefined) {
        child.userData.origEmissive = child.material.emissive ? child.material.emissive.getHex() : 0;
        child.userData.origEmissiveIntensity = child.material.emissiveIntensity || 0;
      }
      if (child.material.emissive) {
        child.material.emissive.setHex(0x00aaff);
        child.material.emissiveIntensity = 0.25;
      }
    }
  });

  transformControls.attach(obj.mesh);
  updateSceneList();
  updatePropsPanel();
}

function deselectAll() {
  if (selectedObject) {
    selectedObject.mesh.traverse(child => {
      if (child.isMesh && child.material && child.userData.origEmissive !== undefined) {
        if (child.material.emissive) {
          child.material.emissive.setHex(child.userData.origEmissive);
          child.material.emissiveIntensity = child.userData.origEmissiveIntensity;
        }
      }
    });
  }
  selectedObject = null;
  transformControls.detach();
  updateSceneList();
  updatePropsPanel();
}

// ── Transform Mode ───────────────────────────────────────────
function setTransformMode(mode) {
  transformMode = mode;
  transformControls.setMode(mode);
  document.querySelectorAll(".s3d-transform-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
}

// ── Delete Object ────────────────────────────────────────────
function deleteSelected() {
  if (!selectedObject) return;
  transformControls.detach();
  scene.remove(selectedObject.mesh);
  sceneObjects = sceneObjects.filter(o => o !== selectedObject);
  selectedObject = null;
  updateSceneList();
  updatePropsPanel();
  updateStats();
  addAIMessage("system", "🗑️ Object deleted.");
}

function deleteObjectByIndex(idx) {
  const obj = sceneObjects[idx];
  if (!obj) return;
  if (selectedObject === obj) {
    transformControls.detach();
    selectedObject = null;
  }
  scene.remove(obj.mesh);
  sceneObjects.splice(idx, 1);
  updateSceneList();
  updatePropsPanel();
  updateStats();
}

// ── Add Primitive ────────────────────────────────────────────
function addPrimitive(type) {
  const data = {
    name: type.charAt(0).toUpperCase() + type.slice(1),
    type: type,
    geometry: getDefaultGeometry(type),
    position: [0, type === "plane" ? 0.01 : 0.5, 0],
    rotation: [type === "plane" ? -Math.PI / 2 : 0, 0, 0],
    scale: [1, 1, 1],
    material: {
      color: "#00d4ff",
      metalness: 0.3,
      roughness: 0.5,
      emissive: "#000000",
      emissiveIntensity: 0,
      opacity: 1.0,
      transparent: false
    }
  };
  const mesh = buildMesh(data);
  scene.add(mesh);
  const obj = { mesh, data };
  sceneObjects.push(obj);
  selectObject(obj);
  updateStats();
  addAIMessage("system", `➕ Added ${data.name}`);
}

function getDefaultGeometry(type) {
  switch (type) {
    case "box": return { width: 1, height: 1, depth: 1 };
    case "sphere": return { radius: 0.5, widthSegments: 32, heightSegments: 32 };
    case "cylinder": return { radiusTop: 0.5, radiusBottom: 0.5, height: 1, radialSegments: 32 };
    case "cone": return { radius: 0.5, height: 1, radialSegments: 32 };
    case "torus": return { radius: 0.5, tube: 0.2, radialSegments: 16, tubularSegments: 48 };
    case "plane": return { width: 2, height: 2 };
    default: return { width: 1, height: 1, depth: 1 };
  }
}

// ── Build Three.js Mesh from Data ────────────────────────────
function buildMesh(data) {
  let geometry;
  const g = data.geometry || {};

  switch (data.type) {
    case "box":
      geometry = new THREE.BoxGeometry(g.width || 1, g.height || 1, g.depth || 1);
      break;
    case "sphere":
      geometry = new THREE.SphereGeometry(g.radius || 0.5, g.widthSegments || 32, g.heightSegments || 32);
      break;
    case "cylinder":
      geometry = new THREE.CylinderGeometry(g.radiusTop || 0.5, g.radiusBottom || 0.5, g.height || 1, g.radialSegments || 32);
      break;
    case "cone":
      geometry = new THREE.ConeGeometry(g.radius || 0.5, g.height || 1, g.radialSegments || 32);
      break;
    case "torus":
      geometry = new THREE.TorusGeometry(g.radius || 0.5, g.tube || 0.2, g.radialSegments || 16, g.tubularSegments || 48);
      break;
    case "plane":
      geometry = new THREE.PlaneGeometry(g.width || 2, g.height || 2);
      break;
    default:
      geometry = new THREE.BoxGeometry(1, 1, 1);
  }

  const mat = data.material || {};
  const material = new THREE.MeshStandardMaterial({
    color: mat.color || "#00d4ff",
    metalness: mat.metalness ?? 0.3,
    roughness: mat.roughness ?? 0.5,
    emissive: mat.emissive || "#000000",
    emissiveIntensity: mat.emissiveIntensity ?? 0,
    transparent: mat.transparent || mat.opacity < 1,
    opacity: mat.opacity ?? 1.0,
    side: THREE.DoubleSide
  });

  const mesh = new THREE.Mesh(geometry, material);
  const p = data.position || [0, 0, 0];
  const r = data.rotation || [0, 0, 0];
  const s = data.scale || [1, 1, 1];
  mesh.position.set(p[0], p[1], p[2]);
  mesh.rotation.set(r[0], r[1], r[2]);
  mesh.scale.set(s[0], s[1], s[2]);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.name = data.name || "Object";

  return mesh;
}

// ── Load Objects from AI Response ────────────────────────────
function loadObjects(objectsData) {
  // Clear existing
  clearScene();

  objectsData.forEach((data, i) => {
    if (!data.name) data.name = `Object_${i + 1}`;
    const mesh = buildMesh(data);
    scene.add(mesh);
    sceneObjects.push({ mesh, data });
  });

  updateSceneList();
  updateStats();

  // Frame camera to fit objects
  if (sceneObjects.length > 0) {
    frameCameraToFit();
  }
}

function clearScene() {
  transformControls.detach();
  selectedObject = null;
  sceneObjects.forEach(o => scene.remove(o.mesh));
  sceneObjects = [];
  updateSceneList();
  updatePropsPanel();
  updateStats();
}

function frameCameraToFit() {
  const box = new THREE.Box3();
  sceneObjects.forEach(o => box.expandByObject(o.mesh));
  const center = new THREE.Vector3();
  box.getCenter(center);
  const size = new THREE.Vector3();
  box.getSize(size);
  const maxDim = Math.max(size.x, size.y, size.z);
  const dist = maxDim * 2;
  camera.position.set(center.x + dist * 0.7, center.y + dist * 0.5, center.z + dist * 0.7);
  controls.target.copy(center);
  controls.update();
}

// ── Scene Hierarchy List ─────────────────────────────────────
function updateSceneList() {
  if (sceneObjects.length === 0) {
    sceneList.innerHTML = `
      <div class="s3d-scene-empty">
        No objects yet.<br/>Ask JARVIS to generate<br/>a 3D model for you.
      </div>`;
    return;
  }

  sceneList.innerHTML = sceneObjects.map((obj, i) => {
    const icon = getTypeIcon(obj.data.type);
    const sel = selectedObject === obj ? " selected" : "";
    return `
      <div class="s3d-scene-item${sel}" onclick="selectObjectByIndex(${i})">
        <span class="s3d-item-icon">${icon}</span>
        <span class="s3d-item-name">${obj.data.name}</span>
        <button class="s3d-item-delete" onclick="event.stopPropagation();deleteObjectByIndex(${i})" title="Delete">✕</button>
      </div>`;
  }).join("");
}

function selectObjectByIndex(i) {
  if (sceneObjects[i]) selectObject(sceneObjects[i]);
}

function getTypeIcon(type) {
  const icons = { box: "📦", sphere: "🔮", cylinder: "🧪", cone: "📐", torus: "💍", plane: "⬜" };
  return icons[type] || "🔷";
}

// ── Properties Panel ─────────────────────────────────────────
function updatePropsPanel() {
  if (!selectedObject) {
    propsContainer.innerHTML = `
      <div class="s3d-no-selection">
        Select an object to<br/>edit its properties
      </div>`;
    return;
  }

  const d = selectedObject.data;
  const p = d.position || [0, 0, 0];
  const r = d.rotation || [0, 0, 0];
  const s = d.scale || [1, 1, 1];
  const m = d.material || {};

  propsContainer.innerHTML = `
    <div class="s3d-panel-header">
      <span>📋 ${d.name}</span>
    </div>
    <div class="s3d-prop-group">
      <div class="s3d-prop-group-title">POSITION</div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label x">X</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${p[0].toFixed(2)}" onchange="setProp('position',0,this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label y">Y</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${p[1].toFixed(2)}" onchange="setProp('position',1,this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label z">Z</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${p[2].toFixed(2)}" onchange="setProp('position',2,this.value)"/>
      </div>
    </div>
    <div class="s3d-prop-group">
      <div class="s3d-prop-group-title">ROTATION (RAD)</div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label x">X</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${r[0].toFixed(2)}" onchange="setProp('rotation',0,this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label y">Y</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${r[1].toFixed(2)}" onchange="setProp('rotation',1,this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label z">Z</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${r[2].toFixed(2)}" onchange="setProp('rotation',2,this.value)"/>
      </div>
    </div>
    <div class="s3d-prop-group">
      <div class="s3d-prop-group-title">SCALE</div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label x">X</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${s[0].toFixed(2)}" onchange="setProp('scale',0,this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label y">Y</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${s[1].toFixed(2)}" onchange="setProp('scale',1,this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label z">Z</span>
        <input type="number" class="s3d-prop-input" step="0.1" value="${s[2].toFixed(2)}" onchange="setProp('scale',2,this.value)"/>
      </div>
    </div>
    <div class="s3d-prop-group">
      <div class="s3d-prop-group-title">MATERIAL & COLOR</div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label" style="color:var(--cyan)">🎨</span>
        <span class="s3d-prop-tag">DIFFUSE</span>
        <input type="color" class="s3d-prop-input" value="${m.color || '#00d4ff'}" onchange="setMat('color',this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label" style="color:var(--amber)">✨</span>
        <span class="s3d-prop-tag">GLOW</span>
        <input type="color" class="s3d-prop-input" value="${m.emissive || '#000000'}" onchange="setMat('emissive',this.value)"/>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label" style="color:var(--amber);font-size:8px">INT</span>
        <input type="range" class="s3d-prop-slider" min="0" max="2" step="0.1" value="${m.emissiveIntensity ?? 0}" oninput="setMat('emissiveIntensity',this.value);this.nextElementSibling.textContent=parseFloat(this.value).toFixed(2)"/>
        <span class="s3d-prop-value">${(m.emissiveIntensity ?? 0).toFixed(2)}</span>
      </div>
      <div class="s3d-prop-row" style="margin-top:8px">
        <span class="s3d-prop-label" style="color:var(--txt-dim);font-size:8px">MTL</span>
        <input type="range" class="s3d-prop-slider" min="0" max="1" step="0.05" value="${m.metalness ?? 0.3}" oninput="setMat('metalness',this.value);this.nextElementSibling.textContent=parseFloat(this.value).toFixed(2)"/>
        <span class="s3d-prop-value">${(m.metalness ?? 0.3).toFixed(2)}</span>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label" style="color:var(--txt-dim);font-size:8px">RGH</span>
        <input type="range" class="s3d-prop-slider" min="0" max="1" step="0.05" value="${m.roughness ?? 0.5}" oninput="setMat('roughness',this.value);this.nextElementSibling.textContent=parseFloat(this.value).toFixed(2)"/>
        <span class="s3d-prop-value">${(m.roughness ?? 0.5).toFixed(2)}</span>
      </div>
      <div class="s3d-prop-row">
        <span class="s3d-prop-label" style="color:var(--txt-dim);font-size:8px">OPC</span>
        <input type="range" class="s3d-prop-slider" min="0" max="1" step="0.05" value="${m.opacity ?? 1}" oninput="setMat('opacity',this.value);this.nextElementSibling.textContent=parseFloat(this.value).toFixed(2)"/>
        <span class="s3d-prop-value">${(m.opacity ?? 1).toFixed(2)}</span>
      </div>
    </div>
    <div class="s3d-prop-group" style="border-bottom:none;">
      <button class="s3d-add-btn" style="width:100%;padding:6px" onclick="duplicateSelected()">📋 Duplicate Object</button>
    </div>`;
}

function setProp(prop, axis, value) {
  if (!selectedObject) return;
  const v = parseFloat(value) || 0;
  selectedObject.data[prop][axis] = v;
  const m = selectedObject.mesh;
  if (prop === "position") m.position.setComponent(axis, v);
  if (prop === "rotation") { const r = selectedObject.data.rotation; m.rotation.set(r[0], r[1], r[2]); }
  if (prop === "scale") m.scale.setComponent(axis, v);
}

function setMat(prop, value) {
  if (!selectedObject) return;
  const m = selectedObject.mesh;

  const updateMat = (mesh) => {
    const mat = mesh.material;
    if (!mat) return;
    if (prop === "color") mat.color.set(value);
    else if (prop === "emissive") mat.emissive.set(value);
    else if (prop === "emissiveIntensity") mat.emissiveIntensity = parseFloat(value);
    else if (prop === "metalness") mat.metalness = parseFloat(value);
    else if (prop === "roughness") mat.roughness = parseFloat(value);
    else if (prop === "opacity") {
      const v = parseFloat(value);
      mat.opacity = v;
      mat.transparent = v < 1;
    }
  };

  if (m.isMesh) {
    updateMat(m);
  } else {
    m.traverse(child => {
      if (child.isMesh) {
        // If it's a sub-mesh, we might want to store original emissive separately
        // but for now we just apply.
        updateMat(child);
      }
    });
  }

  // Update data object
  if (!selectedObject.data.material) selectedObject.data.material = {};
  selectedObject.data.material[prop] = (prop === "color" || prop === "emissive") ? value : parseFloat(value);
  if (prop === "opacity") selectedObject.data.material.transparent = parseFloat(value) < 1;
}

function duplicateSelected() {
  if (!selectedObject) return;
  const d = JSON.parse(JSON.stringify(selectedObject.data));
  d.name = d.name + "_copy";
  d.position[0] += 1;
  const mesh = buildMesh(d);
  scene.add(mesh);
  const obj = { mesh, data: d };
  sceneObjects.push(obj);
  selectObject(obj);
  updateStats();
  addAIMessage("system", `📋 Duplicated as ${d.name}`);
}

// ── Stats ────────────────────────────────────────────────────
function updateStats() {
  if (viewportStats) {
    viewportStats.textContent = `Objects: ${sceneObjects.length} | Triangles: ${countTriangles()}`;
  }
}

function countTriangles() {
  let count = 0;
  sceneObjects.forEach(o => {
    o.mesh.traverse(child => {
      if (child.isMesh && child.geometry) {
        if (child.geometry.index) {
          count += child.geometry.index.count / 3;
        } else if (child.geometry.attributes.position) {
          count += child.geometry.attributes.position.count / 3;
        }
      }
    });
  });
  return Math.round(count);
}

// ── AI Chat ──────────────────────────────────────────────────
function addAIMessage(type, text) {
  const welcome = document.querySelector(".s3d-ai-welcome");
  if (welcome) welcome.remove();

  const el = document.createElement("div");
  el.className = `s3d-ai-msg ${type}`;
  el.innerHTML = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
  aiMessages.appendChild(el);
  aiMessages.scrollTop = aiMessages.scrollHeight;
}

function addLoadingMessage() {
  const el = document.createElement("div");
  el.className = "s3d-ai-msg jarvis s3d-loading-msg";
  el.innerHTML = `
    <div class="s3d-loading">
      <div class="s3d-loading-dots"><span></span><span></span><span></span></div>
      <span style="font-family:var(--fmono);font-size:11px;color:var(--cyan-d)">JARVIS is generating your model...</span>
    </div>`;
  aiMessages.appendChild(el);
  aiMessages.scrollTop = aiMessages.scrollHeight;
}

function removeLoadingMessage() {
  const el = document.querySelector(".s3d-loading-msg");
  if (el) el.remove();
}

// ── AI Generation ────────────────────────────────────────────
// ── AI Generation ────────────────────────────────────────────
async function generateModel() {
  const prompt = aiPrompt.value.trim();
  if (!prompt) return;

  const engine = document.querySelector('input[name="s3d-engine"]:checked').value;

  if (engine === "highpoly") {
    generateHighPoly(prompt);
    return;
  }

  addAIMessage("user", prompt);
  aiPrompt.value = "";
  btnGenerate.disabled = true;
  btnModify.disabled = true;
  addLoadingMessage();

  try {
    const res = await fetch("/studio3d/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt })
    });
    const data = await res.json();
    removeLoadingMessage();

    if (data.success && data.objects && data.objects.length > 0) {
      loadObjects(data.objects);
      addAIMessage("jarvis", `✅ Generated **${data.count} objects** for your model. Click any object to edit its properties, or use the transform gizmo to move/rotate/scale.`);
    } else {
      addAIMessage("jarvis", `❌ ${data.error || "Failed to generate model. Try a different prompt."}`);
    }
  } catch (e) {
    removeLoadingMessage();
    addAIMessage("jarvis", `❌ Error: ${e.message}`);
  }

  btnGenerate.disabled = false;
  btnModify.disabled = false;
}

async function generateHighPoly(prompt) {
  addAIMessage("user", `[High Poly] ${prompt}`);
  aiPrompt.value = "";
  btnGenerate.disabled = true;
  btnModify.disabled = true;
  addLoadingMessage();

  try {
    const res = await fetch("/studio3d/generate_highpoly", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt })
    });
    const data = await res.json();

    if (data.success) {
      pollTaskStatus(data.task_id);
    } else {
      removeLoadingMessage();
      addAIMessage("jarvis", `❌ ${data.error}`);
      btnGenerate.disabled = false;
      btnModify.disabled = false;
    }
  } catch (e) {
    removeLoadingMessage();
    addAIMessage("jarvis", `❌ Error: ${e.message}`);
    btnGenerate.disabled = false;
    btnModify.disabled = false;
  }
}

async function pollTaskStatus(taskId) {
  try {
    const res = await fetch(`/studio3d/task_status/${taskId}`);
    const data = await res.json();

    if (data.success) {
      if (data.status === "success" && data.model_url) {
        removeLoadingMessage();
        loadGLB(data.model_url);
        addAIMessage("jarvis", "✅ **High-Poly model ready!** I've injected the production mesh into your viewport. You can move, scan, and change its colors.");
        btnGenerate.disabled = false;
        btnModify.disabled = false;
      } else if (data.status === "failed") {
        removeLoadingMessage();
        addAIMessage("jarvis", "❌ Tripo AI failed to generate the model. Try a simpler prompt.");
        btnGenerate.disabled = false;
        btnModify.disabled = false;
      } else {
        // Still running
        const loadingText = document.querySelector(".s3d-loading span");
        if (loadingText) loadingText.textContent = `JARVIS is crafting mesh... ${data.progress}%`;
        setTimeout(() => pollTaskStatus(taskId), 3000);
      }
    } else {
      removeLoadingMessage();
      addAIMessage("jarvis", `❌ ${data.error}`);
      btnGenerate.disabled = false;
      btnModify.disabled = false;
    }
  } catch (e) {
    removeLoadingMessage();
    addAIMessage("jarvis", `❌ Error: ${e.message}`);
    btnGenerate.disabled = false;
    btnModify.disabled = false;
  }
}

function loadGLB(url) {
  const loader = new THREE.GLTFLoader();
  loader.load(url, (gltf) => {
    const mesh = gltf.scene;
    mesh.name = "AI_HighPoly_Mesh";

    // Ensure it casts shadows and has standard materials
    mesh.traverse(child => {
      if (child.isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
        if (!child.name) child.name = "MeshPart";

        // Ensure material is Standard (Tripo sometimes uses Basic/Toon)
        if (child.material && !child.material.isMeshStandardMaterial) {
          const oldMat = child.material;
          child.material = new THREE.MeshStandardMaterial({
            color: oldMat.color,
            map: oldMat.map,
            metalness: 0.5,
            roughness: 0.5
          });
        }
      }
    });

    // Center the model
    const box = new THREE.Box3().setFromObject(mesh);
    const center = box.getCenter(new THREE.Vector3());
    mesh.position.sub(center);
    mesh.position.y += (box.max.y - box.min.y) / 2; // Sit on ground

    const data = {
      name: "HighPoly Mesh",
      type: "box", // Placeholder
      position: [mesh.position.x, mesh.position.y, mesh.position.z],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
      material: { color: "#ffffff", metalness: 0.5, roughness: 0.5 }
    };

    scene.add(mesh);
    const obj = { mesh, data, isGLB: true };
    sceneObjects.push(obj);
    selectObject(obj);
    updateStats();
    frameCameraToFit();
  }, (xhr) => {
    if (xhr.total > 0) {
      console.log((xhr.loaded / xhr.total * 100) + '% loaded');
    }
  }, (error) => {
    console.error(error);
    addAIMessage("jarvis", "❌ Error loading the GLB model.");
  });
}

async function modifyScene() {
  const prompt = aiPrompt.value.trim();
  if (!prompt) return;
  if (sceneObjects.length === 0) {
    addAIMessage("jarvis", "⚠️ No objects in scene to modify. Use **Generate** first.");
    return;
  }

  addAIMessage("user", `[Modify] ${prompt}`);
  aiPrompt.value = "";
  btnGenerate.disabled = true;
  btnModify.disabled = true;
  addLoadingMessage();

  const sceneData = sceneObjects.map(o => o.data);

  try {
    const res = await fetch("/studio3d/modify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, scene_objects: sceneData })
    });
    const data = await res.json();
    removeLoadingMessage();

    if (data.success && data.objects && data.objects.length > 0) {
      loadObjects(data.objects);
      addAIMessage("jarvis", `✅ Scene modified — now **${data.count} objects**. Changes applied successfully.`);
    } else {
      addAIMessage("jarvis", `❌ ${data.error || "Failed to modify scene."}`);
    }
  } catch (e) {
    removeLoadingMessage();
    addAIMessage("jarvis", `❌ Error: ${e.message}`);
  }

  btnGenerate.disabled = false;
  btnModify.disabled = false;
}

// ── Export / Download ────────────────────────────────────────
function exportGLB() {
  if (sceneObjects.length === 0) {
    addAIMessage("jarvis", "⚠️ Nothing to export. Generate or add objects first.");
    return;
  }

  const exporter = new THREE.GLTFExporter();
  const exportScene = new THREE.Scene();
  sceneObjects.forEach(o => {
    const clone = o.mesh.clone();
    clone.material = o.mesh.material.clone();
    exportScene.add(clone);
  });

  exporter.parse(exportScene, (result) => {
    const blob = new Blob([result], { type: "application/octet-stream" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "jarvis_model.glb";
    link.click();
    URL.revokeObjectURL(link.href);
    addAIMessage("system", "📥 Downloaded **jarvis_model.glb**");
  }, (err) => {
    addAIMessage("jarvis", `❌ Export error: ${err.message}`);
  }, { binary: true });
}

function exportOBJ() {
  if (sceneObjects.length === 0) {
    addAIMessage("jarvis", "⚠️ Nothing to export.");
    return;
  }

  // Simple OBJ export
  let objStr = "# Exported from J.A.R.V.I.S 3D Studio\n";
  let vertexOffset = 0;

  sceneObjects.forEach(o => {
    const mesh = o.mesh;
    const geo = mesh.geometry.clone();
    geo.applyMatrix4(mesh.matrixWorld);
    const positions = geo.attributes.position;
    const index = geo.index;

    objStr += `o ${o.data.name}\n`;
    for (let i = 0; i < positions.count; i++) {
      objStr += `v ${positions.getX(i).toFixed(4)} ${positions.getY(i).toFixed(4)} ${positions.getZ(i).toFixed(4)}\n`;
    }
    if (index) {
      for (let i = 0; i < index.count; i += 3) {
        objStr += `f ${index.getX(i) + 1 + vertexOffset} ${index.getX(i + 1) + 1 + vertexOffset} ${index.getX(i + 2) + 1 + vertexOffset}\n`;
      }
    }
    vertexOffset += positions.count;
  });

  const blob = new Blob([objStr], { type: "text/plain" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "jarvis_model.obj";
  link.click();
  URL.revokeObjectURL(link.href);
  addAIMessage("system", "📥 Downloaded **jarvis_model.obj**");
}

function exportProjectJSON() {
  if (sceneObjects.length === 0) {
    addAIMessage("jarvis", "⚠️ Nothing to export.");
    return;
  }
  const sceneData = sceneObjects.map(o => o.data);
  const blob = new Blob([JSON.stringify(sceneData, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "jarvis_project.json";
  link.click();
  URL.revokeObjectURL(link.href);
  addAIMessage("system", "📥 Downloaded **jarvis_project.json**");
}

// ── Project Management ──────────────────────────────────────
async function saveProject() {
  if (sceneObjects.length === 0) {
    addAIMessage("jarvis", "⚠️ Scene is empty. Nothing to save.");
    return;
  }
  const name = prompt("Enter project name:", "my_project");
  if (!name) return;

  const sceneData = sceneObjects.map(o => o.data);
  try {
    const res = await fetch("/studio3d/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, scene: sceneData })
    });
    const data = await res.json();
    if (data.success) {
      addAIMessage("system", `✅ Project **${name}** saved to server.`);
      listProjects();
    } else {
      alert("Error saving: " + data.error);
    }
  } catch (e) { alert("Error: " + e.message); }
}

async function listProjects() {
  try {
    const res = await fetch("/studio3d/list");
    const data = await res.json();
    if (data.success) {
      if (data.projects.length === 0) {
        projectList.innerHTML = '<div class="s3d-scene-empty">No projects saved.</div>';
        return;
      }
      projectList.innerHTML = data.projects.map(p => `
        <div class="s3d-scene-item" onclick="loadProject('${p}')">
          <span class="s3d-item-icon">📂</span>
          <span class="s3d-item-name">${p}</span>
        </div>`).join("");
    }
  } catch (e) { console.error("Error listing projects:", e); }
}

async function loadProject(name) {
  if (sceneObjects.length > 0 && !confirm("Loading will clear current scene. Continue?")) return;
  try {
    const res = await fetch("/studio3d/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    const data = await res.json();
    if (data.success) {
      loadObjects(data.scene);
      addAIMessage("system", `✅ Project **${name}** loaded.`);
    } else { alert("Error loading: " + data.error); }
  } catch (e) { alert("Error: " + e.message); }
}

function handleJsonUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    try {
      const data = JSON.parse(ev.target.result);
      if (Array.isArray(data)) {
        loadObjects(data);
        addAIMessage("system", `✅ Uploaded project **${file.name}** applied.`);
      } else {
        alert("Invalid project format. Expected JSON array of objects.");
      }
    } catch (err) { alert("Error parsing JSON: " + err.message); }
  };
  reader.readAsText(file);
}

// ── Event Bindings ───────────────────────────────────────────
btnGenerate.addEventListener("click", generateModel);
btnModify.addEventListener("click", modifyScene);
aiPrompt.addEventListener("keydown", e => {
  if (e.key === "Enter" && e.ctrlKey) generateModel();
  if (e.key === "Enter" && e.shiftKey) modifyScene();
});

btnSaveProject.addEventListener("click", saveProject);
btnUploadJson.addEventListener("click", () => jsonInput.click());
jsonInput.addEventListener("change", handleJsonUpload);
btnRefreshProj.addEventListener("click", listProjects);

// Transform mode buttons
document.querySelectorAll(".s3d-transform-btn").forEach(btn => {
  btn.addEventListener("click", () => setTransformMode(btn.dataset.mode));
});

// Add primitive buttons
document.querySelectorAll(".s3d-add-prim").forEach(btn => {
  btn.addEventListener("click", () => addPrimitive(btn.dataset.type));
});

// Clear scene
document.getElementById("s3d-clear-btn")?.addEventListener("click", () => {
  if (sceneObjects.length === 0) return;
  if (confirm("Clear all objects from the scene?")) {
    clearScene();
    addAIMessage("system", "🗑️ Scene cleared.");
  }
});

// Delete selected
document.getElementById("s3d-delete-btn")?.addEventListener("click", deleteSelected);

// Export buttons
document.getElementById("s3d-export-glb")?.addEventListener("click", exportGLB);
document.getElementById("s3d-export-obj")?.addEventListener("click", exportOBJ);
document.getElementById("s3d-export-json")?.addEventListener("click", exportProjectJSON);

// ── Init ─────────────────────────────────────────────────────
initScene();
listProjects();
addAIMessage("jarvis", "Welcome to the **3D Studio**, sir. Describe any 3D model and I'll generate it for you. You can also use the primitives panel on the left, or edit objects with the properties panel.\n\n**Shortcuts:** W = Move, E = Rotate, R = Scale, Del = Delete\n**Ctrl+Enter** = Generate, **Shift+Enter** = Modify");

