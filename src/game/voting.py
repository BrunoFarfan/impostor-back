import random
import asyncio
from ..core.state import matches
from ..core.websocket import WebSocketManager


class VoteManager:
    @staticmethod
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

    @staticmethod
    def _store_vote(match_code: str, player_id: str, target_id: str):
        """Store a player's vote"""
        matches[match_code]["votes"][player_id] = target_id

    @staticmethod
    def _get_alive_players(match_code: str) -> list[str]:
        """Get list of alive player IDs"""
        alive_players = []
        for pid, player_data in matches[match_code]["players"].items():
            if player_data["alive"]:
                alive_players.append(pid)
        return alive_players

    @staticmethod
    def _all_players_voted(match_code: str) -> bool:
        """Check if all alive players have voted"""
        alive_players = VoteManager._get_alive_players(match_code)
        voted_players = set(matches[match_code]["votes"].keys())
        alive_players_set = set(alive_players)

        return voted_players >= alive_players_set and len(alive_players) > 0

    @staticmethod
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

        eliminated_player_role = matches[match_code]["players"][eliminated_player_id][
            "role"
        ]
        eliminated_player_name = matches[match_code]["players"][eliminated_player_id][
            "name"
        ]

        matches[match_code]["players"][eliminated_player_id]["alive"] = False

        reveal_message = {
            "type": "reveal_result",
            "eliminated_player": eliminated_player_id,
            "eliminated_player_role": eliminated_player_role,
            "eliminated_player_name": eliminated_player_name,
        }
        await WebSocketManager.broadcast_to_match(match_code, reveal_message)

        await WebSocketManager.broadcast_phase_change(match_code, "reveal")

        return eliminated_player_id

    @staticmethod
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

    @staticmethod
    async def _check_win_conditions_and_continue(match_code: str):
        """Check win conditions and either end game or continue to next round"""
        alive_impostors, alive_normal = VoteManager._count_alive_by_role(match_code)
        total_alive = alive_impostors + alive_normal

        if alive_impostors >= (total_alive / 2):
            game_over_message = {"type": "game_over", "winner": "impostor"}
            await WebSocketManager.broadcast_to_match(match_code, game_over_message)
            await WebSocketManager.broadcast_phase_change(match_code, "game_over")
        elif alive_impostors == 0:
            game_over_message = {"type": "game_over", "winner": "normal"}
            await WebSocketManager.broadcast_to_match(match_code, game_over_message)
            await WebSocketManager.broadcast_phase_change(match_code, "game_over")
        else:
            matches[match_code]["round"] += 1
            matches[match_code]["phase"] = "round"
            await WebSocketManager.broadcast_phase_change(match_code, "round")

    @staticmethod
    async def handle_vote(match_code: str, player_id: str, target_id: str):
        """Handle a player's vote and check for elimination/win conditions"""
        if not VoteManager._validate_vote(match_code, player_id):
            return

        VoteManager._store_vote(match_code, player_id, target_id)

        if VoteManager._all_players_voted(match_code):
            await VoteManager._process_elimination(match_code)
            matches[match_code]["votes"] = {}
            await asyncio.sleep(
                5
            )  # wait 5 seconds before going to next round/game over
            await VoteManager._check_win_conditions_and_continue(match_code)
