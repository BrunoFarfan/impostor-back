from fastapi import WebSocket

# Global state storage
active_connections: dict[str, list[WebSocket]] = {}
websocket_to_player: dict[WebSocket, dict] = {}
matches: dict[str, dict] = {}
