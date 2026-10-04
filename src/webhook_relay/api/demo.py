"""Demo-only endpoint that plays the role of the provider's media CDN.

Registered only when ``APP_ENV=demo`` so the storage path can be exercised end to end
without any network access: the sender script rewrites recording URLs to point here.
"""

from __future__ import annotations

import math
import struct

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/demo", tags=["demo"], include_in_schema=False)

SAMPLE_RATE = 8000
DURATION_SECONDS = 1


def synthetic_wav(duration_seconds: int = DURATION_SECONDS, frequency_hz: float = 440.0) -> bytes:
    """Build a tiny valid PCM WAV (mono, 8 kHz, 16-bit) containing a sine tone."""
    frames = SAMPLE_RATE * duration_seconds
    samples = (
        int(12_000 * math.sin(2 * math.pi * frequency_hz * i / SAMPLE_RATE)) for i in range(frames)
    )
    pcm = struct.pack(f"<{frames}h", *samples)
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm


_SAMPLE = synthetic_wav()


@router.get("/media/{name}")
async def demo_media(name: str) -> Response:
    """Serve a synthetic recording for any ``*.wav`` name (anything else is 404)."""
    if not name.endswith(".wav"):
        raise HTTPException(status_code=404, detail="not found")
    return Response(content=_SAMPLE, media_type="audio/wav")
