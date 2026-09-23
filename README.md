# LifeFlow AI 🚀

A comprehensive, intelligent AI agent for personal daily organization, task prioritization, shopping lists, financial budget math, map navigation, and motivational progress media generation. Built on Google Cloud's **Agent Development Kit (ADK)** and deployed to **Vertex AI Agent Engine**.

![LifeFlow AI Demo](./demo.gif)

> 📹 *Note: A standalone high-definition video player is also available in the repository as [`./demo.mp4`](./demo.mp4).*

---

## 🌟 Capabilities & Verified Features

This repository contains the complete codebase for **LifeFlow AI**. Below are the capabilities **actively implemented** in [`app/agent.py`](file:///config/Desktop/Session1/life-organizer-assistant/app/agent.py):

### 1. 🗄️ Task Management & Database Persistence
- **Google Cloud Firestore Integration**: Automatically stores, updates, and retrieves user tasks, due dates, and status (`get_tasks`, `add_task`, `update_task_status`).

### 2. 🧠 Long-Term Memory (Vertex AI Memory Bank)
- **Cross-Session Fact Persistence**: Uses `PreloadMemoryTool` and custom callbacks (`generate_memories_callback`) to remember user preferences, health facts, and dietary restrictions across independent chat sessions.

### 3. 🖼️ Multi-Modal Media Generation & Cloud Storage
- **Image Generation (`gemini-3.1-flash-lite-image`)**: Generates goal achievement badges and visual cards, saves artifacts, and uploads public assets to **Google Cloud Storage**.
- **Omni Model Video Generation (`gemini-omni-flash-preview`)**: Generates short domain videos using Google's Omni model in the `global` region and returns public Cloud Storage HTTPS URLs.

### 4. 🎨 Adaptive UI (A2UI v0.8)
- **Rich Card Surface Rendering**: Emits native A2UI JSON structures (`Card`, `Column`, `Row`, `Text`, `Image`, `Video`) rendered seamlessly by the included FastAPI proxy and custom frontend.

### 5. 💻 Secure Code Execution Sandbox
- **Agent Platform Sandbox**: Uses `PicklableAgentEngineSandboxCodeExecutor` to safely execute Python code for complex budget calculations and multi-step data processing.

### 6. 🗺️ Location & Navigation Tools
- **Google Geocoding API**: Converts street addresses into latitude and longitude coordinates (`geocode_address`).
- **Google Places API (New)**: Discovers nearby amenities, stores, and fitness centers (`find_nearby_places`).
- **Google Maps Navigation Links**: Generates estimated distances and interactive Google Maps direction URLs (`get_maps_info_and_link`).

### 7. ⛅ Real-Time Utilities
- **Weather API Integration**: Fetches real-time weather forecasts via Open-Meteo (`get_weather`).
- **Timezone Clock**: Queries current local times across time zones (`get_current_time`).

---

## 📋 Project Status

| Feature / Integration | Status | Implementation Details |
| :--- | :--- | :--- |
| **Agent Engine / ADK** | ✅ **Active** | Built on Google ADK 0.8+ with A2UI callbacks |
| **Google Cloud Firestore** | ✅ **Active** | Task CRUD operations wired in `app/agent.py` |
| **Google Cloud Storage** | ✅ **Active** | Public asset hosting for generated images & videos |
| **Vertex AI Memory Bank** | ✅ **Active** | Cross-session memory preloading & synthesis |
| **Gemini Image & Video Tools** | ✅ **Active** | `gemini-3.1-flash-lite-image` & `gemini-omni-flash-preview` |
| **A2UI Surface Rendering** | ✅ **Active** | A2UI v0.8 renderer built into FastAPI proxy & web UI |
| **Code Execution Sandbox** | ✅ **Active** | Vertex Reasoning Engine Python Sandbox |
| **RAG / Vector Corpus Retrieval** | ⏳ *Planned* | *Planned for future document grounding; not yet implemented in agent tools.* |

---

## 🛠️ Local Setup & Run Instructions

To run **LifeFlow AI** locally on your workstation, follow these steps:

### Prerequisites
- Python 3.11+
- Google Cloud SDK (`gcloud`) authenticated to your GCP project

### 1. Environment Setup
Create a `.env` file or export your GCP configuration in your terminal:
```bash
export GOOGLE_CLOUD_PROJECT="<your-gcp-project-id>"
export GOOGLE_CLOUD_LOCATION="us-east1"
export AGENT_ENGINE_RESOURCE_NAME="projects/<project-number>/locations/us-east1/reasoningEngines/<engine-id>"
export AGENT_DIRECTORY="app"
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Option A: Run Local ADK Developer Web UI
To test the agent directly using the ADK Web interface:
```bash
adk web --port 8080 --allow_origins "*" --reload_agents
```

### 4. Option B: Run FastAPI Proxy & Custom Chat Frontend
To launch the custom web interface with built-in A2UI renderer:
```bash
cd frontend
pip install -r requirements.txt
python main.py
```
*The web interface will start locally on port 8080.*

---

## 📁 Repository Structure

```
.
├── app/
│   ├── agent.py                 # Core ADK agent, tools, instructions & callbacks
│   └── __init__.py
├── frontend/
│   ├── main.py                  # FastAPI proxy talking A2A protocol to Agent Runtime
│   ├── static/
│   │   ├── index.html           # Rebranded LifeFlow AI web interface & A2UI renderer
│   │   └── icon.png             # Modern 3D glassmorphic app icon
│   └── requirements.txt
├── agents-cli-manifest.yaml     # Agents CLI deployment manifest
├── deployment_metadata.json     # Agent Runtime resource metadata
├── demo.gif                     # Optimized looping video demonstration
├── demo.mp4                     # Standalone demo video player
└── README.md                    # Project documentation
```
