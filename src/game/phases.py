from ..core.state import matches
from ..core.websocket import WebSocketManager


class PhaseManager:
    @staticmethod
    async def handle_voting_readiness(match_code: str, player_id: str, readiness: bool):
        """Handle a player's voting readiness and check for phase transition"""
        if match_code not in matches:
            return

        if player_id not in matches[match_code]["players"]:
            return

        matches[match_code]["players"][player_id]["ready_to_vote"] = readiness

        all_ready_to_vote = True
        alive_players = []

        for pid, player_data in matches[match_code]["players"].items():
            if player_data["alive"]:
                alive_players.append(pid)
                if not player_data["ready_to_vote"]:
                    all_ready_to_vote = False

        await WebSocketManager.broadcast_match_state(match_code)

        if all_ready_to_vote and len(alive_players) > 0:
            for pid, player_data in matches[match_code]["players"].items():
                player_data["ready_to_vote"] = False

            matches[match_code]["phase"] = "voting"
            await WebSocketManager.broadcast_phase_change(match_code, "voting")
