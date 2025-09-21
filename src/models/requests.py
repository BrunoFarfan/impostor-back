from pydantic import BaseModel


class JoinMatchRequest(BaseModel):
    name: str
    match_code: str


class StartMatchRequest(BaseModel):
    match_code: str
