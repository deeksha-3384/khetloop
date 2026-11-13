/* KhetLoop frontend configuration (owner: P3)
 * Loaded FIRST on every page. Only these four values are meant to be edited.
 */

// Flask backend base URL (API_BASE_URL in .env.example)
const API_BASE = "http://localhost:5000";

// true  = read mock JSON files from MOCK_BASE (no backend needed)
// false = call the real Flask API at API_BASE
const USE_MOCK = true;

// Value of the X-Expert-Key header (EXPERT_API_KEY in .env.example).
// This is the demo key from the contract, not a Supabase key.
const EXPERT_KEY = "demo-expert-key";

// Folder of mock JSON files, relative to the server root.
// Serve from the repo root, so this is /frontend/mocks/.
// When P1 pushes shared/mocks/, change ONLY this line to "/shared/mocks/".
const MOCK_BASE = "/frontend/mocks/";