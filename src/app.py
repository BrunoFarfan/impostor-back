import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .models import JoinMatchRequest, StartMatchRequest
from .core import (
    WebSocketManager,
    MatchManager,
    active_connections,
    websocket_to_player,
)
from .game import VoteManager, RoleManager, PhaseManager

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/match/create")
async def create_match():
    """Generate and return a match code, creating a new match entry"""
    match_code = MatchManager.create_match()
    return {"match_code": match_code}


@app.post("/match/join")
async def join_match(request: JoinMatchRequest):
    """Add a player to a match and return the player id"""
    result = await MatchManager.join_match(request.match_code, request.name)
    if result is None:
        return {"error": "Match not found"}
    return result


@app.post("/match/start")
async def start_match(request: StartMatchRequest):
    """Assign roles and start the match"""
    return await RoleManager.assign_roles_and_start(request.match_code)


@app.get("/match/{match_code}/state")
async def get_match_state(match_code: str):
    """Get the current state of a match for manual lobby refresh"""
    match_info = MatchManager.get_match_info(match_code)
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

                if message_type == "votingReadiness":
                    readiness = message.get("value", False)
                    await PhaseManager.handle_voting_readiness(
                        code, player_id, readiness
                    )
                elif message_type == "vote":
                    target_id = message.get("target")
                    if target_id:
                        await VoteManager.handle_vote(code, player_id, target_id)
                elif message_type == "role_proposition":
                    proposition = message.get("proposition", "")
                    await RoleManager.handle_role_proposition(
                        code, player_id, proposition
                    )
                else:
                    await websocket.send_text(data)

            except json.JSONDecodeError:
                await websocket.send_text(data)

    except WebSocketDisconnect:
        player_info = websocket_to_player.get(websocket)
        if player_info:
            await MatchManager.reassign_host_if_needed(
                player_info["match_code"], player_info["player_id"]
            )
            del websocket_to_player[websocket]

        if code in active_connections:
            active_connections[code].remove(websocket)
            if not active_connections[code]:
                del active_connections[code]

        await WebSocketManager.broadcast_match_state(code)
        print(f"Client disconnected from match: {code}, player: {player_id}")
