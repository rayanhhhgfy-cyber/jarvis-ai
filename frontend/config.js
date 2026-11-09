// ====================================================================
// J.A.R.V.I.S. OMEGA — Frontend config (backend base URL)
// ====================================================================
// Loaded by frontend/index.html BEFORE the app script.
//
// window.JARVIS_API_URL — where the dashboard talks to the backend.
//
//   "" (empty, the default below) = same-origin. Use this when the
//   backend serves the dashboard itself (Render all-in-one, or local
//   dev). The API calls and the WebSocket then go to the same host
//   that served this page.
//
//   SPLIT DEPLOY (frontend on Vercel, backend on Render): the Vercel
//   deploy sets this line to the Render backend URL, e.g.
//     window.JARVIS_API_URL = "https://jarvis-ai.onrender.com";
//   (no trailing slash). The dashboard then calls the Render API and
//   opens its WebSocket (wss://) there.
//
//   CORS note: when the frontend lives on another origin, that origin
//   must be allowed by the backend — set BACKEND_CORS_ORIGINS on
//   Render to a JSON list including the Vercel URL, e.g.
//     ["https://jarvis-frontend.vercel.app"]
//   (exact Vercel project URL goes here at deploy time).
//
// Never put a secret, token, password or cookie in this file.
window.JARVIS_API_URL = "";
