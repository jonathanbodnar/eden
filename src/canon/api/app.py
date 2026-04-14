from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from src.canon.api.routes import (
    actors, admin, changes, chapters, chat, epochs, events, motifs,
    narration, places, scores, story, timeline, world_packets,
)

try:
    from src.canon.api.routes import videos
except ImportError:
    videos = None  # type: ignore[assignment]
from src.canon.config import settings

CACHE_PREFIXES = ("/epochs", "/chapters", "/actors", "/events", "/places", "/timeline", "/scores", "/narration-packets", "/world-packets", "/videos", "/story")


class CacheHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if request.method == "GET" and any(request.url.path.startswith(p) for p in CACHE_PREFIXES):
            response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
        return response


app = FastAPI(
    title="Edinworld Canon API",
    description="Canon & Living World-State Engine",
    version="0.2.0",
    root_path="/world-api",
)

app.add_middleware(CacheHeaderMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(epochs.router, prefix="/epochs", tags=["Epochs"])
app.include_router(chapters.router, prefix="/chapters", tags=["Chapters"])
app.include_router(actors.router, prefix="/actors", tags=["Actors"])
app.include_router(events.router, prefix="/events", tags=["Events"])
app.include_router(places.router, prefix="/places", tags=["Places"])
app.include_router(timeline.router, prefix="/timeline", tags=["Timeline"])
app.include_router(motifs.router, prefix="/motifs", tags=["Motifs"])
app.include_router(scores.router, prefix="/scores", tags=["Scores"])
app.include_router(narration.router, prefix="/narration-packets", tags=["Narration Packets"])
app.include_router(world_packets.router, prefix="/world-packets", tags=["World Packets"])
app.include_router(changes.router, prefix="/canon/changes", tags=["Changes"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(story.router, prefix="/story", tags=["Story"])
if videos:
    app.include_router(videos.router, prefix="/videos", tags=["Videos"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "edinworld-canon"}
