from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random
import string
import json
import asyncio

app = FastAPI()

active_connections: dict[str, list[WebSocket]] = {}

websocket_to_player: dict[WebSocket, dict] = {}

matches: dict[str, dict] = {}


def _get_match_info(match_code: str) -> dict | None:
    """Private function to get match information"""
    if match_code not in matches:
        return None

    players = []
    for player_id, player_data in matches[match_code]["players"].items():
        players.append(
            {
                "id": player_id,
                "name": player_data["name"],
                "host": player_data["host"],
                "toggled": player_data["toggled"],
                "alive": player_data["alive"],
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

    message = {"type": "match_state_update", **match_info}

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


async def reassign_host_if_needed(match_code: str, disconnected_player_id: str):
    """Reassign host to the first remaining player if the host disconnected"""
    if match_code not in matches:
        return

    if disconnected_player_id in matches[match_code]["players"]:
        was_host = matches[match_code]["players"][disconnected_player_id]["host"]
        del matches[match_code]["players"][disconnected_player_id]

        if was_host and matches[match_code]["players"]:
            first_player_id = next(iter(matches[match_code]["players"]))
            matches[match_code]["players"][first_player_id]["host"] = True

            for player_id, player_data in matches[match_code]["players"].items():
                if player_id != first_player_id:
                    player_data["host"] = False


async def handle_toggle(match_code: str, player_id: str, toggle_value: bool):
    """Handle a player's toggle action and check for phase transition"""
    if match_code not in matches:
        return

    if player_id not in matches[match_code]["players"]:
        return

    matches[match_code]["players"][player_id]["toggled"] = toggle_value

    all_toggled = True
    alive_players = []

    for pid, player_data in matches[match_code]["players"].items():
        if player_data["alive"]:
            alive_players.append(pid)
            if not player_data["toggled"]:
                all_toggled = False

    await broadcast_match_state(match_code)

    if all_toggled and len(alive_players) > 0:
        for pid, player_data in matches[match_code]["players"].items():
            player_data["toggled"] = False

        matches[match_code]["phase"] = "voting"
        await broadcast_phase_change(match_code, "voting")


def _validate_vote(match_code: str, player_id: str) -> bool:
    """Validate if a player can vote"""
    if match_code not in matches:
        return False

    if player_id not in matches[match_code]["players"]:
        return False

    if not matches[match_code]["players"][player_id]["alive"]:
        return False

    if player_id in matches[match_code]["votes"]:
        return False

    return True


def _store_vote(match_code: str, player_id: str, target_id: str):
    """Store a player's vote"""
    matches[match_code]["votes"][player_id] = target_id


def _get_alive_players(match_code: str) -> list[str]:
    """Get list of alive player IDs"""
    alive_players = []
    for pid, player_data in matches[match_code]["players"].items():
        if player_data["alive"]:
            alive_players.append(pid)
    return alive_players


def _all_players_voted(match_code: str) -> bool:
    """Check if all alive players have voted"""
    alive_players = _get_alive_players(match_code)
    voted_players = set(matches[match_code]["votes"].keys())
    alive_players_set = set(alive_players)

    return voted_players >= alive_players_set and len(alive_players) > 0


async def _process_elimination(match_code: str) -> str | None:
    """Count votes and eliminate the most voted player. Returns eliminated player ID."""
    vote_counts = {}
    for voter, target in matches[match_code]["votes"].items():
        if target in vote_counts:
            vote_counts[target] += 1
        else:
            vote_counts[target] = 1

    if not vote_counts:
        return None

    max_votes = max(vote_counts.values())
    most_voted = [pid for pid, count in vote_counts.items() if count == max_votes]

    eliminated_player_id = random.choice(most_voted)

    eliminated_player_role = matches[match_code]["players"][eliminated_player_id]["role"]
    eliminated_player_name = matches[match_code]["players"][eliminated_player_id]["name"]

    matches[match_code]["players"][eliminated_player_id]["alive"] = False

    reveal_message = {
        "type": "reveal_result",
        "eliminated_player": eliminated_player_id,
        "eliminated_player_role": eliminated_player_role,
        "eliminated_player_name": eliminated_player_name,
    }
    await broadcast_to_match(match_code, reveal_message)

    await broadcast_phase_change(match_code, "reveal")

    return eliminated_player_id


def _count_alive_by_role(match_code: str) -> tuple[int, int]:
    """Count alive impostors and normal players. Returns (impostors, normal)"""
    alive_impostors = 0
    alive_normal = 0

    for pid, player_data in matches[match_code]["players"].items():
        if player_data["alive"]:
            if player_data["role"] == "impostor":
                alive_impostors += 1
            else:
                alive_normal += 1

    return alive_impostors, alive_normal


async def _check_win_conditions_and_continue(match_code: str):
    """Check win conditions and either end game or continue to next round"""
    alive_impostors, alive_normal = _count_alive_by_role(match_code)
    total_alive = alive_impostors + alive_normal

    if alive_impostors >= (total_alive / 2):
        game_over_message = {"type": "game_over", "winner": "impostors"}
        await broadcast_to_match(match_code, game_over_message)
        await broadcast_phase_change(match_code, "game_over")
    elif alive_impostors == 0:
        game_over_message = {"type": "game_over", "winner": "normal"}
        await broadcast_to_match(match_code, game_over_message)
        await broadcast_phase_change(match_code, "game_over")
    else:
        matches[match_code]["round"] += 1
        matches[match_code]["phase"] = "round"
        await broadcast_phase_change(match_code, "round")


async def handle_vote(match_code: str, player_id: str, target_id: str):
    """Handle a player's vote and check for elimination/win conditions"""
    if not _validate_vote(match_code, player_id):
        return

    _store_vote(match_code, player_id, target_id)

    if _all_players_voted(match_code):
        await _process_elimination(match_code)
        matches[match_code]["votes"] = {}
        await asyncio.sleep(5) # wait 5 seconds before going to next round/game over
        await _check_win_conditions_and_continue(match_code)


async def broadcast_to_match(match_code: str, message: dict):
    """Broadcast a message to all connected clients in the match"""
    if match_code not in active_connections:
        return

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
    letters = "".join(random.choices(string.ascii_uppercase, k=4))
    numbers = "".join(random.choices(string.digits, k=2))
    match_code = letters + numbers

    matches[match_code] = {
        "players": {},
        "phase": "lobby",
        "round": 1,
        "votes": {},
        "secret_character": "Kanye West",
    }

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
        "toggled": False,
        "role": "normal",
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

    for player in connected_players:
        if player["id"] == impostor_id:
            matches[request.match_code]["players"][player["id"]]["role"] = "impostor"
        else:
            matches[request.match_code]["players"][player["id"]]["role"] = "normal"

    matches[request.match_code]["phase"] = "role_assignment"

    await broadcast_phase_change(request.match_code, "role_assignment")

    for player in connected_players:
        player_role = matches[request.match_code]["players"][player["id"]]["role"]
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

            try:
                message = json.loads(data)
                message_type = message.get("type")

                if message_type == "toggle":
                    toggle_value = message.get("value", False)
                    await handle_toggle(code, player_id, toggle_value)
                elif message_type == "vote":
                    target_id = message.get("target")
                    if target_id:
                        await handle_vote(code, player_id, target_id)
                else:
                    await websocket.send_text(data)

            except json.JSONDecodeError:
                await websocket.send_text(data)

    except WebSocketDisconnect:
        player_info = websocket_to_player.get(websocket)
        if player_info:
            await reassign_host_if_needed(
                player_info["match_code"], player_info["player_id"]
            )
            del websocket_to_player[websocket]

        if code in active_connections:
            active_connections[code].remove(websocket)
            if not active_connections[code]:
                del active_connections[code]

        await broadcast_match_state(code)
        print(f"Client disconnected from match: {code}, player: {player_id}")
