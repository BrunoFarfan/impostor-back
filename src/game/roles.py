import random
from ..core.state import matches
from ..core.websocket import WebSocketManager
from ..core.match import MatchManager


class RoleManager:
    @staticmethod
    async def handle_role_proposition(
        match_code: str, player_id: str, proposition: str
    ):
        """Handle a player's role proposition"""
        if match_code not in matches:
            return

        if player_id not in matches[match_code]["players"]:
            return

        matches[match_code]["propositions"][player_id] = proposition

        if proposition and proposition.strip():
            matches[match_code]["can_start"] = True
            await WebSocketManager.broadcast_match_state(match_code)

    @staticmethod
    async def assign_roles_and_start(match_code: str):
        """Assign roles and start the match"""
        if match_code not in matches:
            return {"error": "Match not found"}

        match_info = MatchManager.get_match_info(match_code)
        if not match_info or len(match_info["players"]) < 3:
            return {"error": "Need at least 3 connected players to start"}

        if not matches[match_code]["can_start"]:
            return {"error": "Need at least one role proposition to start"}

        connected_players = match_info["players"]
        impostor_player = random.choice(connected_players)
        impostor_id = impostor_player["id"]

        available_propositions = []
        propositions = matches[match_code]["propositions"]

        for player in connected_players:
            player_id = player["id"]
            if player_id != impostor_id and player_id in propositions:
                proposition = propositions[player_id].strip()
                if proposition:
                    available_propositions.append(proposition)

        if available_propositions:
            selected_role = random.choice(available_propositions)
        else:
            selected_role = "Kanye West"

        matches[match_code]["secret_character"] = selected_role

        for player in connected_players:
            if player["id"] == impostor_id:
                matches[match_code]["players"][player["id"]]["role"] = "impostor"
            else:
                matches[match_code]["players"][player["id"]]["role"] = (
                    selected_role.title()
                )

        matches[match_code]["phase"] = "role_assignment"
        await WebSocketManager.broadcast_phase_change(match_code, "role_assignment")

        # Send each player their role privately
        for player in connected_players:
            player_role = matches[match_code]["players"][player["id"]]["role"]
            if player_role == "impostor":
                role_to_send = "impostor"
            else:
                role_to_send = selected_role

            private_message = {"type": "role_assignment", "role": role_to_send}
            await WebSocketManager.send_private_message(
                match_code, player["id"], private_message
            )

        return {"success": True, "phase": "role_assignment"}
