import random
import string


def generate_match_code() -> str:
    """Generate a random 6-character match code (4 letters + 2 numbers)"""
    letters = "".join(random.choices(string.ascii_uppercase, k=4))
    numbers = "".join(random.choices(string.digits, k=2))
    return letters + numbers
