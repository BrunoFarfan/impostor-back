from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random
import string
import json

app = FastAPI()

active_connections: dict[str, list[WebSocket]] = {}

# Track which player_id corresponds to each websocket connection
websocket_to_player: dict[WebSocket, dict] = {}

matches: dict[str, dict] = {}


def _get_match_info(match_code: str) -> dict | None:
    """Private function to get match information, filtering out disconnected players"""
    if match_code not in matches:
        return None

    # Get connected player IDs from active websockets
    connected_player_ids = set()
    if match_code in active_connections:
        for websocket in active_connections[match_code]:
            if websocket in websocket_to_player:
                player_info = websocket_to_player[websocket]
                if player_info["match_code"] == match_code:
                    connected_player_ids.add(player_info["player_id"])

    # Only include connected players
    players = []
    for player_id, player_data in matches[match_code]["players"].items():
        if player_id in connected_player_ids:
            players.append(
                {
                    "id": player_id,
                    "name": player_data["name"],
                    "host": player_data["host"],
                }
            )

    return {
        "players": players,
        "phase": matches[match_code]["phase"],
    }


async def broadcast_match_state(match_code: str):
    """Broadcast the current match state to all connected clients in the match"""
    if match_code not in active_connections:
        return

    match_info = _get_match_info(match_code)
    if not match_info:
        return

    message = {"type": "lobby_update", **match_info}

    message_json = json.dumps(message)
    disconnected_websockets = []
    for websocket in active_connections[match_code]:
        try:
            await websocket.send_text(message_json)
        except Exception:
            disconnected_websockets.append(websocket)

    for websocket in disconnected_websockets:
        active_connections[match_code].remove(websocket)


async def broadcast_phase_change(match_code: str, new_phase: str):
    """Broadcast a phase change event to all connected clients in the match"""
    if match_code not in active_connections:
        return

    message = {"type": "phase_change", "phase": new_phase}

    message_json = json.dumps(message)
    disconnected_websockets = []
    for websocket in active_connections[match_code]:
        try:
            await websocket.send_text(message_json)
        except Exception:
            disconnected_websockets.append(websocket)

    for websocket in disconnected_websockets:
        active_connections[match_code].remove(websocket)


async def send_private_message(match_code: str, player_id: str, message: dict):
    """Send a private message to a specific player"""
    if match_code not in active_connections:
        return

    message_json = json.dumps(message)
    for websocket in active_connections[match_code]:
        if websocket in websocket_to_player:
            player_info = websocket_to_player[websocket]
            if (
                player_info["match_code"] == match_code
                and player_info["player_id"] == player_id
            ):
                try:
                    await websocket.send_text(message_json)
                except Exception:
                    pass  # Handle disconnected websocket silently
                break


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

    matches[match_code] = {"players": {}, "phase": "lobby"}

    return {"match_code": match_code}


@app.post("/match/join")
async def join_match(request: JoinMatchRequest):
    """Add a player to a match and return the player id"""
    if request.match_code not in matches:
        return {"error": "Match not found"}

    player_id = f"p{random.randint(0, 10**6)}"

    is_host = len(matches[request.match_code]["players"]) == 0

    matches[request.match_code]["players"][player_id] = {
        "name": request.name,
        "alive": True,
        "host": is_host,
    }

    await broadcast_match_state(request.match_code)

    return {"player_id": player_id, "name": request.name, "host": is_host}


class StartMatchRequest(BaseModel):
    match_code: str


@app.post("/match/start")
async def start_match(request: StartMatchRequest):
    """Assign roles and start the match"""
    if request.match_code not in matches:
        return {"error": "Match not found"}

    match_info = _get_match_info(request.match_code)
    if not match_info or len(match_info["players"]) < 3:
        return {"error": "Need at least 3 connected players to start"}

    connected_players = match_info["players"]

    impostor_player = random.choice(connected_players)
    impostor_id = impostor_player["id"]

    roles = {}
    for player in connected_players:
        if player["id"] == impostor_id:
            roles[player["id"]] = "impostor"
        else:
            roles[player["id"]] = "Kanye West"

    matches[request.match_code]["roles"] = roles
    matches[request.match_code]["phase"] = "role_assignment"

    await broadcast_phase_change(request.match_code, "role_assignment")

    for player in connected_players:
        player_role = roles[player["id"]]
        private_message = {"type": "role_assignment", "role": player_role}
        await send_private_message(request.match_code, player["id"], private_message)

    return {"success": True, "phase": "role_assignment"}


@app.get("/match/{match_code}/state")
async def get_match_state(match_code: str):
    """Get the current state of a match for manual lobby refresh"""
    match_info = _get_match_info(match_code)
    if not match_info:
        return {"error": "Match not found"}

    return match_info


@app.websocket("/ws/match/{code}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, code: str, player_id: str):
    """WebSocket endpoint for match communication"""
    await websocket.accept()

    print(f"Client connected to match: {code}, player: {player_id}")

    if code not in active_connections:
        active_connections[code] = []
    active_connections[code].append(websocket)

    websocket_to_player[websocket] = {"match_code": code, "player_id": player_id}

    try:
        while True:
            data = await websocket.receive_text()

            await websocket.send_text(data)

    except WebSocketDisconnect:
        if websocket in websocket_to_player:
            del websocket_to_player[websocket]

        if code in active_connections:
            active_connections[code].remove(websocket)
            if not active_connections[code]:
                del active_connections[code]

        await broadcast_match_state(code)
        print(f"Client disconnected from match: {code}, player: {player_id}")
