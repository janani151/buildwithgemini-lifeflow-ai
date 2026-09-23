"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.

Why A2A: agents-cli 1.1.0 (GA) deploys ADK agents to Agent Runtime as A2A agents
and no longer registers the reasoning-engine operation schema the old
`agent_engines.get(...).stream_query()` path relied on (operation_schemas() comes
back empty). The container serves the A2A protocol over the Agent Engine HTTP
passthrough, so this proxy fetches the agent's card and sends messages with the
a2a-sdk client (the same path `agents-cli run --mode a2a` uses). This works for
both A2A and plain ADK 1.1.0 deployments (the container serves A2A either way).

Run:
  pip install -r requirements.txt
  export AGENT_ENGINE_RESOURCE_NAME="projects/.../locations/.../reasoningEngines/..."
  export AGENT_DIRECTORY="app"   # your agent's app directory (agents-cli-manifest.yaml)
  python main.py                 # -> http://localhost:8080
"""

import os
import uuid

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("PROJECT_ID", "qwiklabs-gcp-02-af7987b13f8c"))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    FilePart,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
    TransportProtocol,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/851623494397/locations/us-east1/reasoningEngines/9130672211516981248",
)
# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
# Location is embedded in the resource name: projects/<p>/locations/<loc>/reasoningEngines/<id>.
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

# A2A endpoint for an Agent Runtime deployment, via the Agent Engine HTTP
# passthrough. The card lives at the well-known path under this base.
A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"

# One set of ADC credentials, refreshed per request (access tokens expire ~1h).
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Always return JSON so the browser never receives a plain-text 500 page
    # (which shows up in the chat as "Unexpected token 'I', "Internal S"... is
    # not valid JSON"). Any server-side failure now surfaces as a readable
    # message in the chat bubble instead.
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE A2A context per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}
# Cache the agent card after the first fetch.
_card: AgentCard | None = None


async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        try:
            resp = await client.get(A2A_CARD_URL)
            resp.raise_for_status()
            card = AgentCard(**resp.json())
            card.url = A2A_BASE
            _card = card
        except Exception:
            _card = AgentCard(
                name="LifeFlow AI",
                description="LifeFlow AI Assistant",
                url=A2A_BASE,
            )
    return _card


import json
import re


def _parse_a2ui_from_text(text: str) -> list[dict]:
    """Parse embedded <a2ui-json>, <a2a_datapart_json>, or markdown A2UI JSON blocks from raw text."""
    items = []
    for match in re.finditer(r"<(a2ui-json|a2a_datapart_json)>\s*(.*?)\s*</\1>", text, re.DOTALL):
        raw_json = match.group(2).strip()
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and "data" in parsed:
                items.append(parsed["data"])
            elif isinstance(parsed, dict):
                items.append(parsed)
        except Exception:
            pass

    for match in re.finditer(r"```json\s*(\{[\s\S]*?\"beginRendering\"[\s\S]*?\})\s*```", text):
        raw_json = match.group(1).strip()
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and "data" in parsed:
                items.append(parsed["data"])
            elif isinstance(parsed, dict):
                items.append(parsed)
        except Exception:
            pass

    return items


def _clean_text_around_a2ui(text: str) -> str:
    cleaned = re.sub(r"<(a2ui-json|a2a_datapart_json)>\s*[\s\S]*?\s*</\1>", "", text)
    cleaned = re.sub(r"```json\s*\{[\s\S]*?\"beginRendering\"[\s\S]*?\}\s*```", "", cleaned)
    return cleaned.strip()


def _extract_parts(parts: list) -> list[dict]:
    """Extract displayable parts from an A2A message or task artifact.

    Converts text parts to `{"kind": "text", "text": ...}` and A2UI data parts
    to `{"kind": "a2ui", "data": ...}`.
    """
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if isinstance(root, TextPart):
            txt = root.text or ""
            ui_items = _parse_a2ui_from_text(txt)
            if ui_items:
                for ui in ui_items:
                    out.append({"kind": "a2ui", "data": ui})
            clean_txt = _clean_text_around_a2ui(txt)
            if clean_txt:
                out.append({"kind": "text", "text": clean_txt})
        elif getattr(root, "mime_type", None) == _A2UI_MIME:
            raw = getattr(root, "data", None)
            if raw:
                try:
                    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                except Exception:
                    data = None
                if data:
                    out.append({"kind": "a2ui", "data": data})
        elif isinstance(root, FilePart):
            uri = getattr(getattr(root, "file", None), "uri", None)
            if uri:
                out.append({"kind": "text", "text": uri})
    return out


_local_runner = None
_local_sessions: dict[str, str] = {}


def _get_local_runner():
    global _local_runner
    if _local_runner is None:
        from app.agent import root_agent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        _local_runner = Runner(
            agent=root_agent,
            app_name="life-organizer-assistant",
            session_service=InMemorySessionService(),
        )
    return _local_runner


async def _chat_local(user_id: str, message: str) -> list[dict]:
    from google.genai.types import Content, Part

    runner = _get_local_runner()
    session_id = _local_sessions.get(user_id)
    if not session_id:
        session = await runner.session_service.create_session(
            app_name="life-organizer-assistant", user_id=user_id
        )
        session_id = session.id
        _local_sessions[user_id] = session_id

    msg = Content(role="user", parts=[Part.from_text(text=message)])
    out_parts = []
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=msg
    ):
        content = getattr(event, "content", None)
        if content:
            for p in getattr(content, "parts", []):
                text = None
                if hasattr(p, "text") and p.text:
                    text = p.text
                elif hasattr(p, "inline_data") and p.inline_data and hasattr(p.inline_data, "data"):
                    try:
                        raw = p.inline_data.data
                        if isinstance(raw, bytes):
                            text = raw.decode("utf-8")
                        else:
                            text = str(raw)
                    except Exception:
                        pass
                if text:
                    ui_items = _parse_a2ui_from_text(text)
                    if ui_items:
                        for ui in ui_items:
                            out_parts.append({"kind": "a2ui", "data": ui})
                    clean_txt = _clean_text_around_a2ui(text)
                    if clean_txt:
                        out_parts.append({"kind": "text", "text": clean_txt})
    return out_parts


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    try:
        async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
            card = await _get_card(client)
            factory = ClientFactory(
                ClientConfig(
                    supported_transports=[
                        TransportProtocol.jsonrpc,
                        TransportProtocol.http_json,
                    ],
                    httpx_client=client,
                )
            )
            a2a_client = factory.create(card)

            msg = Message(
                message_id=str(uuid.uuid4()),
                role=Role.user,
                parts=[Part(root=TextPart(text=message))],
                context_id=_contexts.get(user_id),
            )

            last_task = None
            got_artifact_update = False
            async for event in a2a_client.send_message(msg):
                if not isinstance(event, tuple):
                    continue
                task, update = event
                if task is not None:
                    last_task = task
                    if getattr(task, "context_id", None):
                        _contexts[user_id] = task.context_id
                if isinstance(update, TaskArtifactUpdateEvent):
                    got_artifact_update = True
                    parts.extend(_extract_parts(update.artifact.parts))

            if not got_artifact_update and last_task is not None:
                for artifact in getattr(last_task, "artifacts", None) or []:
                    parts.extend(_extract_parts(artifact.parts))
    except Exception:
        # Seamless fallback to local ADK runner if remote A2A endpoint is unauthorized (403) or offline
        parts = await _chat_local(user_id, message)

    if not parts:
        # The turn produced no text or UI (e.g. the agent only ran tools, or a
        # tool stalled). Be honest rather than silent.
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


# Serve generated files directory and chat UI
GENERATED_DIR = os.path.join(os.path.dirname(__file__), "static", "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated_static")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
