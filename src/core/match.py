import random
import string
from .state import matches


class MatchManager:
    @staticmethod
    def get_match_info(match_code: str) -> dict | None:
        """Get match information"""
        if match_code not in matches:
            return None

        players = []
        for player_id, player_data in matches[match_code]["players"].items():
            players.append(
                {
                    "id": player_id,
                    "name": player_data["name"],
                    "host": player_data["host"],
                    "ready_to_vote": player_data["ready_to_vote"],
                    "alive": player_data["alive"],
                }
            )

        return {
            "phase": matches[match_code]["phase"],
            "can_start": matches[match_code]["can_start"],
            "round": matches[match_code]["round"],
            "players": players,
        }

    @staticmethod
    def create_match() -> str:
        """Create a new match and return the match code"""
        letters = "".join(random.choices(string.ascii_uppercase, k=4))
        numbers = "".join(random.choices(string.digits, k=2))
        match_code = letters + numbers

        matches[match_code] = {
            "players": {},
            "can_start": False,
            "phase": "lobby",
            "round": 1,
            "votes": {},
            "secret_character": "Kanye West",
            "propositions": {},
        }

        return match_code

    @staticmethod
    async def join_match(match_code: str, player_name: str):
        """Add a player to a match"""
        from .websocket import WebSocketManager

        if match_code not in matches:
            return None

        if matches[match_code]["phase"] != "lobby":
            return None

        player_id = f"p{random.randint(0, 10**6)}"
        is_host = len(matches[match_code]["players"]) == 0

        matches[match_code]["players"][player_id] = {
            "name": player_name,
            "alive": True,
            "host": is_host,
            "ready_to_vote": False,
            "role": "normal",
        }

        await WebSocketManager.broadcast_match_state(match_code)
        return {"player_id": player_id, "name": player_name, "host": is_host}

    @staticmethod
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
