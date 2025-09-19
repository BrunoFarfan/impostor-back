from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random
import string
import decouple
import json


frontend_url: str = str(decouple.config("FRONTEND_URL"))

app = FastAPI()

active_connections: dict[str, list[WebSocket]] = {}

matches: dict[str, dict] = {}


async def broadcast_match_state(match_code: str):
    """Broadcast the current match state to all connected clients in the match"""
    if match_code not in matches or match_code not in active_connections:
        return

    players = []
    for player_id, player_data in matches[match_code]["players"].items():
        players.append({"id": player_id, "name": player_data["name"]})

    message = {
        "type": "lobby_update",
        "players": players,
        "phase": matches[match_code]["phase"],
    }

    message_json = json.dumps(message)
    disconnected_websockets = []
    for websocket in active_connections[match_code]:
        try:
            await websocket.send_text(message_json)
        except Exception:
            disconnected_websockets.append(websocket)

    for websocket in disconnected_websockets:
        active_connections[match_code].remove(websocket)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JoinMatchRequest(BaseModel):
    name: str
    match_code: str


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/match/create")
async def create_match():
    """Generate and return a match code, creating a new match entry"""
    # Generate a random 6-character code (4 letters + 2 numbers)
    letters = "".join(random.choices(string.ascii_uppercase, k=4))
    numbers = "".join(random.choices(string.digits, k=2))
    match_code = letters + numbers

    # Create new match entry in matches dictionary
    matches[match_code] = {"players": {}, "phase": "lobby"}

    return {"match_code": match_code}


@app.post("/match/join")
async def join_match(request: JoinMatchRequest):
    """Add a player to a match and return the player id"""
    # Check if match exists
    if request.match_code not in matches:
        return {"error": "Match not found"}

    # Generate a unique player id
    player_id = f"p{random.randint(1, 10000)}"

    # Add player to the match
    matches[request.match_code]["players"][player_id] = {
        "name": request.name,
        "alive": True,
    }

    # Broadcast updated match state to all connected clients
    await broadcast_match_state(request.match_code)

    return {"player_id": player_id, "name": request.name}


@app.post("/match/start")
async def start_match():
    """Return dummy roles with one impostor and one character"""
    roles = {"p1": "impostor", "p2": "crewmate"}
    return {"roles": roles}


@app.websocket("/ws/match/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str):
    """WebSocket endpoint for match communication"""
    await websocket.accept()

    # Log connection with match code
    print(f"Client connected to match: {code}")

    # Add connection to active connections
    if code not in active_connections:
        active_connections[code] = []
    active_connections[code].append(websocket)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            # Echo the message back to the client
            await websocket.send_text(data)

    except WebSocketDisconnect:
        # Remove connection from active connections
        if code in active_connections:
            active_connections[code].remove(websocket)
            if not active_connections[code]:  # Remove empty list
                del active_connections[code]
        print(f"Client disconnected from match: {code}")
