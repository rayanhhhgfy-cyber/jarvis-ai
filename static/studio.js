"use strict";

let monacoEditor=null, currentFilePath=null, lastGenerated="", isDirty=false;

const fileTree      = document.getElementById("file-tree");
const aiOutput      = document.getElementById("ai-output");
const aiPrompt      = document.getElementById("ai-prompt");
const generateBtn   = document.getElementById("generate-btn");
const applyBtn      = document.getElementById("apply-btn");
const saveBtn       = document.getElementById("save-btn");
const explainBtn    = document.getElementById("explain-btn");
const downloadBtn   = document.getElementById("download-btn");
const genPreview    = document.getElementById("gen-preview");
const genCode       = document.getElementById("gen-code-display");
const curFile       = document.getElementById("current-filename");
const newFileBtn    = document.getElementById("new-file-btn");
const newFolderBtn  = document.getElementById("new-folder-btn");
const refreshBtn    = document.getElementById("refresh-btn");
const modal         = document.getElementById("new-file-modal");
const modalInput    = document.getElementById("new-file-name");
const modalConfirm  = document.getElementById("create-confirm");
const modalCancel   = document.getElementById("create-cancel");
const modalTitle    = document.getElementById("modal-title");
const useContext    = document.getElementById("use-context");
const closePreview  = document.getElementById("close-preview");
const clkTime       = document.getElementById("clk-time");
const clkDate       = document.getElementById("clk-date");

// Clock
setInterval(()=>{
  const now=new Date();
  clkTime.textContent=now.toLocaleTimeString("en-US",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  clkDate.textContent=now.toLocaleDateString("en-US",{weekday:"short",month:"short",day:"2-digit",year:"numeric"});
},1000);

// Background canvas
(function(){
  const c=document.getElementById("bg-canvas"); if(!c) return;
  const x=c.getContext("2d");
  function r(){c.width=window.innerWidth;c.height=window.innerHeight;d();}
  function d(){
    x.clearRect(0,0,c.width,c.height);
    const W=c.width,H=c.height,vx=W/2,vy=H*0.48;
    x.strokeStyle="rgba(0,180,220,0.12)";x.lineWidth=0.5;
    for(let i=0;i<=16;i++){const t=i/16,y=H*0.3+t*H*0.7;x.beginPath();x.moveTo(vx-vx*t,y);x.lineTo(vx+(W-vx)*t,y);x.stroke();}
    for(let i=0;i<=20;i++){x.beginPath();x.moveTo(vx,vy);x.lineTo((i/20)*W,H);x.stroke();}
  }
  r(); window.addEventListener("resize",r);
})();

// Monaco init
function initMonaco() {
  require.config({paths:{vs:"https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs"}});
  require(["vs/editor/editor.main"],function(){
    monacoEditor=monaco.editor.create(document.getElementById("monaco-editor"),{
      value:"// Open a file from the Explorer, or ask JARVIS to generate code →",
      language:"javascript",theme:"vs-dark",fontSize:14,
      fontFamily:"'JetBrains Mono','Courier New',monospace",
      minimap:{enabled:true},scrollBeyondLastLine:false,automaticLayout:true,
      wordWrap:"on",lineNumbers:"on",renderLineHighlight:"all",
      cursorBlinking:"smooth",smoothScrolling:true,padding:{top:10}
    });
    monacoEditor.onDidChangeModelContent(()=>{
      if(currentFilePath){isDirty=true;curFile.textContent=currentFilePath+" ●";}
    });
    monacoEditor.addCommand(monaco.KeyMod.CtrlCmd|monaco.KeyCode.KeyS, saveFile);
    loadTree();
  });
}

function getLang(name) {
  const ext=name.split(".").pop().toLowerCase();
  return {py:"python",js:"javascript",ts:"typescript",html:"html",css:"css",
          json:"json",md:"markdown",sql:"sql",sh:"shell",txt:"plaintext",
          yml:"yaml",yaml:"yaml",xml:"xml",php:"php",java:"java",
          c:"c",cpp:"cpp",go:"go",rs:"rust",rb:"ruby"}[ext]||"plaintext";
}

function getIcon(name) {
  const ext=name.split(".").pop().toLowerCase();
  return {py:"🐍",js:"📜",ts:"📘",html:"🌐",css:"🎨",json:"📋",
          md:"📝",sql:"🗄️",sh:"⚙️",txt:"📄",yml:"⚙️",yaml:"⚙️"}[ext]||"📄";
}

// File tree
async function loadTree() {
  try {
    const r=await fetch("/studio/files"); const d=await r.json();
    renderTree(d.tree, fileTree);
  } catch(e){ fileTree.innerHTML=`<div class="tree-empty">Error: ${e.message}</div>`; }
}

function renderTree(items, container) {
  container.innerHTML="";
  if(!items||!items.length){
    container.innerHTML='<div class="tree-empty">No files yet.<br/>Create one or ask JARVIS.</div>'; return;
  }
  items.forEach(item=>{
    const el=document.createElement("div");
    el.className="tree-item"+(item.type==="folder"?" folder":"");
    el.dataset.path=item.path;
    el.innerHTML=`<span>${item.type==="folder"?"📁":getIcon(item.name)}</span><span style="flex:1">${item.name}</span><button class="delete-btn" title="Delete">✕</button>`;
    el.querySelector(".delete-btn").addEventListener("click",e=>{e.stopPropagation();deleteItem(item.path,item.name);});
    if(item.type==="file") el.addEventListener("click",()=>openFile(item.path,el));
    container.appendChild(el);
    if(item.type==="folder"&&item.children?.length){
      const ch=document.createElement("div"); ch.className="tree-children";
      renderTree(item.children,ch); container.appendChild(ch);
    }
  });
}

async function openFile(path, el) {
  document.querySelectorAll(".tree-item").forEach(i=>i.classList.remove("active"));
  if(el) el.classList.add("active");
  try {
    const r=await fetch("/studio/read",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path})});
    const d=await r.json();
    if(d.error){alert(d.error);return;}
    currentFilePath=path; isDirty=false; curFile.textContent=path;
    const lang=getLang(path.split("/").pop());
    if(monacoEditor){ const m=monaco.editor.createModel(d.content,lang); monacoEditor.setModel(m); }
  } catch(e){ addAI(`Error opening: ${e.message}`); }
}

async function saveFile() {
  if(!currentFilePath||!monacoEditor) return;
  try {
    const r=await fetch("/studio/write",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:currentFilePath,content:monacoEditor.getValue()})});
    const d=await r.json();
    if(d.success){isDirty=false;curFile.textContent=currentFilePath;addAI(`✅ Saved **${currentFilePath}**`);}
  } catch(e){ addAI(`Error saving: ${e.message}`); }
}

async function deleteItem(path,name) {
  if(!confirm(`Delete "${name}"?`)) return;
  try {
    const r=await fetch("/studio/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path})});
    const d=await r.json();
    if(d.success){if(currentFilePath===path){currentFilePath=null;curFile.textContent="No file open";if(monacoEditor)monacoEditor.setValue("// File deleted");}loadTree();}
  } catch(e){ alert("Error: "+e.message); }
}

// New file/folder
let createMode="file";
newFileBtn.addEventListener("click",()=>{createMode="file";modalTitle.textContent="Create New File";modalInput.placeholder="e.g. app.py or folder/index.html";modal.classList.remove("hidden");modalInput.focus();});
newFolderBtn.addEventListener("click",()=>{createMode="folder";modalTitle.textContent="Create New Folder";modalInput.placeholder="e.g. my-project";modal.classList.remove("hidden");modalInput.focus();});
modalCancel.addEventListener("click",()=>{modal.classList.add("hidden");modalInput.value="";});
modalInput.addEventListener("keydown",e=>{if(e.key==="Enter")modalConfirm.click();if(e.key==="Escape")modalCancel.click();});

modalConfirm.addEventListener("click",async()=>{
  const name=modalInput.value.trim(); if(!name) return;
  const path=createMode==="folder"?name+"/.keep":name;
  const defaults={py:"# Python script\n\ndef main():\n    pass\n\nif __name__==\"__main__\":\n    main()\n",js:"// JavaScript\n\n",html:"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\"/>\n  <title>Document</title>\n</head>\n<body>\n\n</body>\n</html>\n",css:"/* Stylesheet */\n\n",json:"{\n\n}\n",md:"# Title\n\n"};
  const ext=name.split(".").pop().toLowerCase();
  const content=createMode==="folder"?"":( defaults[ext]||"");
  try {
    const r=await fetch("/studio/write",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path,content})});
    const d=await r.json();
    if(d.success){modal.classList.add("hidden");modalInput.value="";await loadTree();if(createMode==="file"){setTimeout(()=>{const el=document.querySelector(`[data-path="${path}"]`);openFile(path,el);},150);}}
  } catch(e){ alert("Error: "+e.message); }
});

refreshBtn.addEventListener("click",loadTree);

// AI generation
generateBtn.addEventListener("click",generateCode);
aiPrompt.addEventListener("keydown",e=>{if(e.key==="Enter"&&e.ctrlKey)generateCode();});

async function generateCode() {
  const prompt=aiPrompt.value.trim(); if(!prompt) return;
  let currentFile="",filename=currentFilePath?currentFilePath.split("/").pop():"";
  if(useContext.checked&&monacoEditor&&currentFilePath) currentFile=monacoEditor.getValue();
  addUser(prompt); aiPrompt.value="";
  generateBtn.disabled=true; generateBtn.textContent="⚡ Generating…";
  applyBtn.disabled=true; genPreview.style.display="none";
  addAI("Generating code, please wait…");
  try {
    const r=await fetch("/studio/ai",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt,current_file:currentFile,filename})});
    const d=await r.json();
    aiOutput.lastElementChild?.remove();
    if(d.success&&d.code){
      lastGenerated=d.code;
      addAI("✅ Done! Click **Apply** to insert into editor, or **Save** after applying.");
      genCode.textContent=d.code.substring(0,800)+(d.code.length>800?"\n\n...(full code will be applied)":"");
      genPreview.style.display="flex"; genPreview.style.flexDirection="column";
      applyBtn.disabled=false;
    } else { addAI(`❌ ${d.explanation||"Generation failed."}`); }
  } catch(e){ aiOutput.lastElementChild?.remove(); addAI(`❌ Error: ${e.message}`); }
  generateBtn.disabled=false; generateBtn.textContent="⚡ Generate";
}

applyBtn.addEventListener("click",()=>{
  if(!lastGenerated||!monacoEditor) return;
  monacoEditor.setValue(lastGenerated); isDirty=true;
  if(currentFilePath) curFile.textContent=currentFilePath+" ●";
  addAI("✅ Code applied! Press **Ctrl+S** to save."); genPreview.style.display="none"; applyBtn.disabled=true;
});
closePreview.addEventListener("click",()=>{ genPreview.style.display="none"; });

explainBtn.addEventListener("click",async()=>{
  if(!monacoEditor||!currentFilePath){addAI("Open a file first.");return;}
  const code=monacoEditor.getValue(); if(!code.trim()) return;
  addAI("Analyzing your code…"); explainBtn.disabled=true;
  try {
    const r=await fetch("/studio/explain",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code,filename:currentFilePath})});
    const d=await r.json();
    aiOutput.lastElementChild?.remove(); addAI(d.explanation);
  } catch(e){ aiOutput.lastElementChild?.remove(); addAI(`Error: ${e.message}`); }
  explainBtn.disabled=false;
});

saveBtn.addEventListener("click",saveFile);
downloadBtn.addEventListener("click",()=>{
  if(!monacoEditor||!currentFilePath) return;
  const blob=new Blob([monacoEditor.getValue()],{type:"text/plain"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(blob);
  a.download=currentFilePath.split("/").pop(); a.click();
});

function addAI(text) {
  document.querySelector(".ai-welcome")?.remove();
  const el=document.createElement("div"); el.className="ai-msg jarvis";
  el.innerHTML=text.replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/\n/g,"<br>");
  aiOutput.appendChild(el); aiOutput.scrollTop=aiOutput.scrollHeight;
}
function addUser(text) {
  document.querySelector(".ai-welcome")?.remove();
  const el=document.createElement("div"); el.className="ai-msg user";
  el.textContent=text; aiOutput.appendChild(el); aiOutput.scrollTop=aiOutput.scrollHeight;
}

initMonaco();
