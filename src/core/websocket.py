import json
from .state import active_connections, websocket_to_player


class WebSocketManager:
    @staticmethod
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

    @staticmethod
    async def broadcast_phase_change(match_code: str, new_phase: str):
        """Broadcast a phase change event to all connected clients in the match"""
        message = {"type": "phase_change", "phase": new_phase}
        await WebSocketManager.broadcast_to_match(match_code, message)

    @staticmethod
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
                        pass
                    break

    @staticmethod
    async def broadcast_match_state(match_code: str):
        """Broadcast the current match state to all connected clients in the match"""
        if match_code not in active_connections:
            return

        from .match import MatchManager

        match_info = MatchManager.get_match_info(match_code)
        if not match_info:
            return

        message = {"type": "match_state_update", **match_info}
        await WebSocketManager.broadcast_to_match(match_code, message)
