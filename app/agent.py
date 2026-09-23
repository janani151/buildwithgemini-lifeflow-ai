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

FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-7b04b331c989"
GCS_BUCKET_NAME = "life-organizer-assets-7b04b331"
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
    await callback_context.add_session_to_memory()
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


def get_tasks(status: str = "all", category: str = "all") -> str:
    """Retrieves tasks from the Firestore task management database.

    Args:
        status: Filter tasks by status ('pending', 'completed', or 'all'). Default is 'all'.
        category: Filter tasks by category ('bill', 'shopping', 'appointment', 'personal', or 'all'). Default is 'all'.

    Returns:
        A formatted string listing the tasks found in the database.
    """
    db = get_firestore_client()
    tasks_ref = db.collection("tasks")
    query_ref = tasks_ref

    if status != "all":
        query_ref = query_ref.where("status", "==", status)
    if category != "all":
        query_ref = query_ref.where("category", "==", category)

    docs = query_ref.stream()
    tasks = []
    for doc in docs:
        data = doc.to_dict()
        tasks.append(data)

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
    db = get_firestore_client()
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
    db.collection("tasks").document(task_id).set(task_data)
    return f"Task successfully added with ID {task_id}: {title} (Due: {due_date})"


def update_task_status(task_id: str, status: str) -> str:
    """Updates the status of an existing task in Firestore.

    Args:
        task_id: The ID of the task to update (e.g. 'task-001').
        status: The new status ('pending' or 'completed').

    Returns:
        A confirmation message of the update.
    """
    db = get_firestore_client()
    doc_ref = db.collection("tasks").document(task_id)
    doc = doc_ref.get()
    if not doc.exists:
        return f"Error: Task with ID {task_id} was not found."

    doc_ref.update({"status": status.lower()})
    return f"Task {task_id} status successfully updated to '{status}'."


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


def generate_item_image(prompt: str, tool_context: ToolContext) -> str:
    """Generates an image for a life organizer item (such as a meal recipe, goal achievement badge, or task banner) using gemini-3.1-flash-lite-image model in global region.

    Saves the image with tool_context.save_artifact for Playground Artifacts, and uploads the image bytes directly to public Cloud Storage returning its public HTTPS URL.

    Args:
        prompt: Description of the image to generate (e.g. 'Goal achievement badge for completing weekly workout schedule').
        tool_context: ADK ToolContext injected automatically by framework.

    Returns:
        The public Cloud Storage HTTPS URL of the generated image.
    """
    try:
        client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="global")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        for part in response.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                if part.inline_data.mime_type:
                    mime_type = part.inline_data.mime_type
                break

        if not image_bytes:
            return "Error: No image bytes returned from model generation."

        ext = "png" if "png" in mime_type else "jpg"
        filename = f"item_image_{uuid.uuid4().hex[:8]}.{ext}"

        # 1. Save with tool_context.save_artifact so it shows up in Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes directly to public GCS bucket (without writing to local file)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return (
            f"🖼️ **Image Generated Successfully**\n"
            f"Artifact Saved: `{filename}`\n"
            f"Public GCS URL: {public_url}"
        )
    except Exception as e:
        return f"Image generation error: {str(e)}"


def generate_item_video(prompt: str, tool_context: ToolContext) -> str:
    """Generates a short video for a life organizer item (such as an animated daily goal achievement badge, routine video, or workout progress clip) using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the video with tool_context.save_artifact for Playground Artifacts, and uploads the video bytes directly to public Cloud Storage returning its public HTTPS URL.

    Args:
        prompt: Description of the video to generate (e.g. 'Short animated goal progress badge celebrating task completion').
        tool_context: ADK ToolContext injected automatically by framework.

    Returns:
        The public Cloud Storage HTTPS URL of the generated video.
    """
    try:
        client = genai.Client(
            vertexai=True, project=FIRESTORE_PROJECT_ID, location="global"
        )
        video_bytes = None

        # 1. Try client.interactions.create (Gemini Omni Flash Video API)
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

        # 2. Fallback to models.generate_content if interactions API returned no data
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

        if not video_bytes:
            return "Error: No video bytes returned from model generation."

        filename = f"item_video_{uuid.uuid4().hex[:8]}.mp4"
        mime_type = "video/mp4"

        # 1. Save with tool_context.save_artifact so it shows up in Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes directly to public GCS bucket (without writing to local file)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return (
            f"🎥 **Video Generated Successfully**\n"
            f"Artifact Saved: `{filename}`\n"
            f"Public GCS URL: {public_url}"
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
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property (\'h1\', \'h2\', \'body\') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or \'kind\'/\'data\'/\'metadata\' objects."
    ),
    include_schema=True,
    include_examples=True,
)

combined_instruction = (
    a2ui_instruction
    + "\n\n"
    + "MEMORY & SAFETY MANDATE:\n"
    + "1. Always remember and track all user allergies, dietary restrictions, and health facts across sessions.\n"
    + "2. When suggesting meals, shopping items, or daily plans, proactively verify against stored user allergies.\n"
    + "3. Explicitly acknowledge and store any new allergies mentioned by the user."
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
