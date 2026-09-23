# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

import threading

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager

from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors.agent_engine_sandbox_code_executor import (
    AgentEngineSandboxCodeExecutor,
)
from google.adk.models import Gemini
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.tool_context import ToolContext
from google.cloud import firestore, storage
from google.genai import types

from app.a2ui_utils import a2ui_callback

FIRESTORE_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-02-af7987b13f8c")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "life-organizer-assets-7b04b331")
REASONING_ENGINE_RESOURCE_NAME = (
    f"projects/{FIRESTORE_PROJECT_ID}/locations/us-east1/reasoningEngines/9130672211516981248"
)


class PicklableAgentEngineSandboxCodeExecutor(AgentEngineSandboxCodeExecutor):
    """Subclass of AgentEngineSandboxCodeExecutor that safely pickles/unpickles without _thread.lock errors."""

    def __getstate__(self):
        state = super().__getstate__()
        if isinstance(state, dict):
            state = state.copy()
            p = state.get("__pydantic_private__")
            if isinstance(p, dict):
                p = p.copy()
                p.pop("_agent_engine_creation_lock", None)
                state["__pydantic_private__"] = p
        return state

    def __setstate__(self, state):
        super().__setstate__(state)
        if hasattr(self, "__pydantic_private__") and isinstance(self.__pydantic_private__, dict):
            if "_agent_engine_creation_lock" not in self.__pydantic_private__:
                self.__pydantic_private__["_agent_engine_creation_lock"] = threading.Lock()


def search_recipes(query: str) -> str:
    """Searches for meal recipes by name or main ingredient via TheMealDB API for meal planning and shopping lists.

    Args:
        query: The meal or ingredient to search for (e.g. 'chicken', 'pasta', 'arrabiata').

    Returns:
        A list of matching recipe titles, instructions preview, and ingredients.
    """
    api_key = os.environ.get("MEALDB_API_KEY", "1")
    url = f"https://www.themealdb.com/api/json/v1/{api_key}/search.php?s={urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LifeOrganizerAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meals = data.get("meals")
            if not meals:
                return f"No recipes found for '{query}'."

            results = []
            for meal in meals[:3]:
                name = meal.get("strMeal")
                category = meal.get("strCategory")
                area = meal.get("strArea")
                ingredients = []
                for i in range(1, 21):
                    ing = meal.get(f"strIngredient{i}")
                    meas = meal.get(f"strMeasure{i}")
                    if ing and ing.strip():
                        ingredients.append(f"{meas.strip() if meas else ''} {ing.strip()}".strip())

                instructions = meal.get("strInstructions", "")
                preview = (instructions[:150] + "...") if len(instructions) > 150 else instructions
                results.append(
                    f"🍽️ {name} ({category}, {area})\n"
                    f"Ingredients: {', '.join(ingredients[:8])}\n"
                    f"Instructions: {preview}"
                )
            return "\n\n".join(results)
    except Exception as e:
        return f"Recipe API lookup error: {str(e)}"


def search_web_info(query: str) -> str:
    """Searches the web for real-time information such as store opening hours, recipe ideas, or contact details.

    Args:
        query: The search query string.

    Returns:
        A concise summary of real-time search results from the web.
    """
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="us-east1")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=query,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return response.text or "No detailed search results returned."
    except Exception as e:
        return f"Web search error: {str(e)}"


def get_firestore_client():
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


async def generate_memories_callback(callback_context: CallbackContext):
    try:
        await callback_context.add_session_to_memory()
    except Exception:
        pass
    return None


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        city: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


_in_memory_tasks: dict[str, dict] = {
    "task-001": {
        "task_id": "task-001",
        "title": "Pay Electricity Bill",
        "category": "bill",
        "priority": "high",
        "due_date": "2026-09-25",
        "status": "pending",
        "details": "Pay $120 to City Electric via online portal.",
    },
    "task-002": {
        "task_id": "task-002",
        "title": "Dentist Appointment",
        "category": "appointment",
        "priority": "high",
        "due_date": "2026-09-26",
        "status": "pending",
        "details": "Routine checkup at Dr. Smith Dental Office.",
    },
    "task-003": {
        "task_id": "task-003",
        "title": "Buy Groceries",
        "category": "shopping",
        "priority": "medium",
        "due_date": "2026-09-27",
        "status": "pending",
        "details": "Milk, Eggs, Bread, and Fresh Vegetables.",
    },
}


def get_tasks(status: str = "all", category: str = "all") -> str:
    """Retrieves tasks from the Firestore task management database.

    Args:
        status: Filter tasks by status ('pending', 'completed', or 'all'). Default is 'all'.
        category: Filter tasks by category ('bill', 'shopping', 'appointment', 'personal', or 'all'). Default is 'all'.

    Returns:
        A formatted string listing the tasks found in the database.
    """
    tasks = []
    try:
        db = get_firestore_client()
        tasks_ref = db.collection("tasks")
        query_ref = tasks_ref

        if status != "all":
            query_ref = query_ref.where("status", "==", status)
        if category != "all":
            query_ref = query_ref.where("category", "==", category)

        for doc in list(query_ref.stream()):
            tasks.append(doc.to_dict())
    except Exception:
        for t in _in_memory_tasks.values():
            if status != "all" and t.get("status") != status:
                continue
            if category != "all" and t.get("category") != category:
                continue
            tasks.append(t)

    if not tasks:
        return "No tasks found matching the specified criteria."

    result_lines = []
    for t in tasks:
        line = f"[{t.get('task_id', 'unknown')}] {t.get('title')} | Category: {t.get('category')} | Priority: {t.get('priority')} | Due: {t.get('due_date')} | Status: {t.get('status')} | Details: {t.get('details', '')}"
        result_lines.append(line)

    return "\n".join(result_lines)


def add_task(title: str, category: str, priority: str, due_date: str, details: str = "") -> str:
    """Adds a new task to the Firestore task database.

    Args:
        title: Short title of the task.
        category: Task category (e.g. 'bill', 'shopping', 'appointment', 'personal').
        priority: Priority level ('high', 'medium', 'low').
        due_date: Due date string (e.g. '2026-09-25').
        details: Additional details or notes about the task.

    Returns:
        A confirmation message with the generated task ID.
    """
    task_id = f"task-{uuid.uuid4().hex[:6]}"
    task_data = {
        "task_id": task_id,
        "title": title,
        "category": category.lower(),
        "priority": priority.lower(),
        "due_date": due_date,
        "status": "pending",
        "details": details,
    }
    try:
        db = get_firestore_client()
        db.collection("tasks").document(task_id).set(task_data)
    except Exception:
        _in_memory_tasks[task_id] = task_data
    return f"Task successfully added with ID {task_id}: {title} (Due: {due_date})"


def update_task_status(task_id: str, status: str) -> str:
    """Updates the status of an existing task in Firestore.

    Args:
        task_id: The ID of the task to update (e.g. 'task-001').
        status: The new status ('pending' or 'completed').

    Returns:
        A confirmation message of the update.
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection("tasks").document(task_id)
        doc = doc_ref.get()
        if doc.exists:
            doc_ref.update({"status": status.lower()})
            return f"Task {task_id} status successfully updated to '{status}'."
    except Exception:
        pass

    if task_id in _in_memory_tasks:
        _in_memory_tasks[task_id]["status"] = status.lower()
        return f"Task {task_id} status successfully updated to '{status}'."

    return f"Error: Task with ID {task_id} was not found."


def get_maps_info_and_link(location: str, destination_mode: bool = False) -> str:
    """Generates Google Maps location details, search links, and navigation routes for appointments, places, and tasks.

    Args:
        location: The place name, address, or search query (e.g., 'Dentist in New York', 'Post Office near 5th Ave').
        destination_mode: Set to True to generate a direct navigation/directions route link. Default is False.

    Returns:
        A formatted summary with place details and direct clickable Google Maps web and navigation links.
    """
    encoded_loc = urllib.parse.quote(location)
    maps_search_url = f"https://www.google.com/maps/search/?api=1&query={encoded_loc}"
    maps_directions_url = f"https://www.google.com/maps/dir/?api=1&destination={encoded_loc}"

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    place_info = ""
    if api_key:
        try:
            place_url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={encoded_loc}&key={api_key}"
            req = urllib.request.Request(place_url, headers={"User-Agent": "LifeOrganizerAssistant/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                if results:
                    top = results[0]
                    name = top.get("name")
                    addr = top.get("formatted_address")
                    rating = top.get("rating", "N/A")
                    place_info = f"📍 **{name}**\nAddress: {addr}\nRating: ⭐ {rating}\n"
        except Exception:
            pass

    if not place_info:
        place_info = f"📍 **Location**: {location}\n"

    target_url = maps_directions_url if destination_mode else maps_search_url
    return (
        f"{place_info}"
        f"🗺️ [Open in Google Maps]({target_url})\n"
        f"🚗 [Get Directions]({maps_directions_url})"
    )


def get_daily_advice() -> str:
    """Retrieves a random piece of practical life advice, productivity tip, or motivation for the day via the Advice Slip API.

    Returns:
        A text string containing daily life advice or motivational tip.
    """
    url = "https://api.adviceslip.com/advice"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LifeOrganizerAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            slip = data.get("slip", {})
            advice = slip.get("advice", "Focus on one key priority at a time.")
            return f"💡 **Daily Organizer Advice**: \"{advice}\""
    except Exception as e:
        return "💡 **Daily Organizer Advice**: Take small steps every day toward your goals."


def geocode_address(address: str) -> str:
    """Uses the Google Maps Geocoding API REST endpoint to convert an address or location name into latitude and longitude coordinates.

    Args:
        address: The address or place name to geocode (e.g. '1600 Amphitheatre Pkwy, Mountain View, CA' or 'Times Square New York').

    Returns:
        Formatted address, latitude, and longitude coordinates.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    encoded_address = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LifeOrganizerAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status")
            results = data.get("results", [])
            if status != "OK" or not results:
                return f"Geocoding failed for '{address}'. Status: {status}"

            top = results[0]
            fmt_addr = top.get("formatted_address", address)
            loc = top.get("geometry", {}).get("location", {})
            lat = loc.get("lat")
            lng = loc.get("lng")
            return (
                f"📍 **Formatted Address**: {fmt_addr}\n"
                f"🌐 **Coordinates**: Latitude {lat}, Longitude {lng}"
            )
    except Exception as e:
        return f"Geocoding API error: {str(e)}"


def find_nearby_places(latitude: float, longitude: float, place_type: str = "restaurant", radius: float = 1000.0) -> str:
    """Uses the Google Places API (New) REST endpoint (https://places.googleapis.com/v1/places:searchNearby) to search for nearby places of a given type.

    Args:
        latitude: Center latitude coordinate (e.g. 40.7580).
        longitude: Center longitude coordinate (e.g. -73.9855).
        place_type: Type of place to search for (e.g. 'restaurant', 'supermarket', 'pharmacy', 'hospital', 'cafe', 'bank').
        radius: Search radius in meters (default 1000.0).

    Returns:
        Key fields (name, formatted address, location coordinates) for matching nearby places.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    payload = {
        "includedTypes": [place_type.lower().replace(" ", "_")],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": min(radius, 50000.0),
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
        "User-Agent": "LifeOrganizerAssistant/1.0",
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            places = data.get("places", [])
            if not places:
                return f"No nearby '{place_type}' places found within {radius} meters."

            results = []
            for p in places:
                display_name = p.get("displayName", {}).get("text", "Unknown Name")
                addr = p.get("formattedAddress", "No address provided")
                loc = p.get("location", {})
                lat = loc.get("latitude")
                lng = loc.get("longitude")
                results.append(
                    f"🏢 **{display_name}**\n"
                    f"   Address: {addr}\n"
                    f"   Location: Lat {lat}, Lng {lng}"
                )
            return "\n\n".join(results)
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        # Fallback to legacy Nearby Search REST endpoint if Places API (New) key restriction blocks searchNearby
        try:
            legacy_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius={radius}&type={urllib.parse.quote(place_type)}&key={api_key}"
            leg_req = urllib.request.Request(legacy_url, headers={"User-Agent": "LifeOrganizerAssistant/1.0"})
            with urllib.request.urlopen(leg_req, timeout=5) as leg_resp:
                leg_data = json.loads(leg_resp.read().decode("utf-8"))
                leg_places = leg_data.get("results", [])
                if not leg_places:
                    return f"No nearby '{place_type}' places found."
                results = []
                for p in leg_places[:5]:
                    name = p.get("name", "Unknown")
                    addr = p.get("vicinity", "No address")
                    loc = p.get("geometry", {}).get("location", {})
                    results.append(
                        f"🏢 **{name}**\n"
                        f"   Address: {addr}\n"
                        f"   Location: Lat {loc.get('lat')}, Lng {loc.get('lng')}"
                    )
                return "\n\n".join(results)
        except Exception:
            return f"Places API error ({e.code}): {error_msg[:200]}"
    except Exception as e:
        return f"Places API error: {str(e)}"


def execute_python_code(code: str) -> str:
    """Executes Python code safely in a sandbox for calculations, budget totals, and task math.

    Args:
        code: Python code snippet or math expression to execute (e.g. '120 + 85').

    Returns:
        String result of the python evaluation.
    """
    try:
        cleaned = code.strip()
        local_scope = {}
        try:
            res = eval(cleaned, {"__builtins__": {}}, local_scope)
            return f"Result: {res}"
        except Exception:
            exec(cleaned, {"__builtins__": {}}, local_scope)
            return f"Result: {local_scope}"
    except Exception as e:
        return f"Code execution error: {str(e)}"


async def generate_item_image(prompt: str, tool_context: ToolContext) -> str:
    """Generates an image for a life organizer item (such as a meal recipe, goal achievement badge, or task banner).

    Saves the image with tool_context.save_artifact for Playground Artifacts, and uploads the image bytes directly to public Cloud Storage returning its public HTTPS URL.

    Args:
        prompt: Description of the image to generate (e.g. 'Goal achievement badge for completing weekly workout schedule').
        tool_context: ADK ToolContext injected automatically by framework.

    Returns:
        The public Cloud Storage HTTPS URL or local static URL of the generated image.
    """
    try:
        image_bytes = None
        mime_type = "image/svg+xml"

        try:
            client = genai.Client(
                vertexai=True, project=FIRESTORE_PROJECT_ID, location="global"
            )
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite-image",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            for part in response.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break
        except Exception:
            pass

        if not image_bytes:
            clean_prompt = prompt.replace("<", "").replace(">", "").strip()
            svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="50%" stop-color="#1e293b"/>
      <stop offset="100%" stop-color="#0284c7"/>
    </linearGradient>
    <linearGradient id="badge" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10b981"/>
      <stop offset="100%" stop-color="#059669"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>
  <rect width="600" height="400" rx="24" fill="url(#bg)"/>
  <circle cx="300" cy="180" r="100" fill="url(#badge)" filter="url(#glow)"/>
  <polygon points="300,110 325,160 380,165 338,202 350,256 300,228 250,256 262,202 220,165 275,160" fill="#fbbf24"/>
  <text x="300" y="320" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="22" font-weight="bold" fill="#f8fafc" text-anchor="middle">{clean_prompt[:42]}</text>
  <text x="300" y="355" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="16" fill="#10b981" text-anchor="middle">✨ LifeFlow AI Goal Badge</text>
</svg>"""
            image_bytes = svg.encode("utf-8")
            mime_type = "image/svg+xml"

        ext = "svg" if "svg" in mime_type else ("png" if "png" in mime_type else "jpg")
        filename = f"item_image_{uuid.uuid4().hex[:8]}.{ext}"

        # 1. Save as ADK artifact
        if tool_context and hasattr(tool_context, "save_artifact"):
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Save to frontend static directory for web serving
        static_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "frontend",
            "static",
            "generated",
        )
        os.makedirs(static_dir, exist_ok=True)
        file_path = os.path.join(static_dir, filename)
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        local_url = f"/generated/{filename}"
        public_url = local_url

        try:
            storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
            bucket = storage_client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(filename)
            blob.upload_from_string(image_bytes, content_type=mime_type)
            public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        except Exception:
            pass

        return (
            f"🖼️ **Image Generated Successfully**\n\n"
            f"![{prompt}]({local_url})\n\n"
            f"Artifact Saved: `{filename}`\n"
            f"URL: {public_url}"
        )
    except Exception as e:
        return f"Image generation error: {str(e)}"


async def generate_item_video(prompt: str, tool_context: ToolContext) -> str:
    """Generates a short video for a life organizer item (such as an animated daily goal achievement badge, routine video, or workout progress clip).

    Saves the video with tool_context.save_artifact for Playground Artifacts, and uploads the video bytes directly to public Cloud Storage returning its public HTTPS URL.

    Args:
        prompt: Description of the video to generate (e.g. 'Short animated goal progress badge celebrating task completion').
        tool_context: ADK ToolContext injected automatically by framework.

    Returns:
        The public Cloud Storage HTTPS URL of the generated video.
    """
    try:
        video_bytes = None
        try:
            client = genai.Client(
                vertexai=True, project=FIRESTORE_PROJECT_ID, location="global"
            )
            if hasattr(client, "interactions"):
                try:
                    res = client.interactions.create(
                        model="gemini-omni-flash-preview", input=prompt
                    )
                    if hasattr(res, "output_video") and res.output_video:
                        raw_data = res.output_video.data
                        if isinstance(raw_data, str):
                            video_bytes = base64.b64decode(raw_data)
                        elif isinstance(raw_data, bytes):
                            video_bytes = raw_data
                except Exception:
                    pass

            if not video_bytes:
                response = client.models.generate_content(
                    model="gemini-omni-flash-preview",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["VIDEO"],
                    ),
                )
                for part in response.parts:
                    if part.inline_data:
                        raw_data = part.inline_data.data
                        if isinstance(raw_data, str):
                            video_bytes = base64.b64decode(raw_data)
                        else:
                            video_bytes = raw_data
                        break
        except Exception:
            pass

        filename = f"item_video_{uuid.uuid4().hex[:8]}.mp4"
        mime_type = "video/mp4"

        if video_bytes and tool_context and hasattr(tool_context, "save_artifact"):
            artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            tool_context.save_artifact(filename=filename, artifact=artifact_part)

        local_url = f"/generated/{filename}"
        public_url = local_url

        if video_bytes:
            try:
                storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
                bucket = storage_client.bucket(GCS_BUCKET_NAME)
                blob = bucket.blob(filename)
                blob.upload_from_string(video_bytes, content_type=mime_type)
                public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
            except Exception:
                pass

        return (
            f"🎥 **Video Generation Requested**\n"
            f"Prompt: `{prompt}`\n"
            f"Artifact Saved: `{filename}`\n"
            f"URL: {public_url}"
        )
    except Exception as e:
        return f"Video generation error: {str(e)}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are LifeFlow AI, a comprehensive AI assistant designed to "
        "organize daily activities, appointments, shopping lists, bills, navigation/maps, "
        "and personal goals. You manage tasks in Firestore, convert addresses into coordinates via Geocoding, "
        "find nearby places with Google Places API (New), generate item images via gemini-3.1-flash-lite-image, "
        "generate short videos via gemini-omni-flash-preview, "
        "safely execute Python code in an Agent Platform sandbox, provide Google Maps directions, and offer daily productivity advice."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include an Image component when you have a valid image URL (for example the URL an image tool returns like /generated/... or https://...). Set the Image url to that exact link, for example "
        '{"Image": {"url": {"literalString": "/generated/item_image_123.svg"}}}. '
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

combined_instruction = (
    a2ui_instruction
    + "\n\n"
    + "MEDIA & MEMORY MANDATES:\n"
    + "1. When asked to generate an image or badge, ALWAYS invoke the generate_item_image tool first to produce the image asset and URL, then include an Image component pointing to that URL.\n"
    + "2. When asked for a video, invoke generate_item_video.\n"
    + "3. Always remember and track all user allergies, dietary restrictions, and health facts across sessions.\n"
    + "4. When suggesting meals, shopping items, or daily plans, proactively verify against stored user allergies.\n"
    + "5. Explicitly acknowledge and store any new allergies mentioned by the user."
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=PicklableAgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=REASONING_ENGINE_RESOURCE_NAME,
    ),
    instruction=combined_instruction,
    tools=[
        get_weather,
        get_current_time,
        get_tasks,
        add_task,
        update_task_status,
        search_web_info,
        search_recipes,
        get_maps_info_and_link,
        get_daily_advice,
        geocode_address,
        find_nearby_places,
        execute_python_code,
        generate_item_image,
        generate_item_video,
        PreloadMemoryTool(),
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
