"""Ask a local Ollama vision model what a photo is and whether it belongs on a wall frame."""
import base64
import json

import httpx

JUNK = {"document", "product", "screenshot"}
SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["people", "travel", "landscape", "event", "pet", "document", "product", "screenshot", "other"]},
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["category", "score"],
}
PROMPT = (
    "You choose photos for a calm family wall frame. Classify this photo into one category: "
    "people (portraits, family, friends), travel (tourist places, trips), landscape (nature, scenery), "
    "event (party, celebration), pet (cats, dogs), "
    "document (receipt, menu, label, paper, whiteboard), "
    "product (a single object photographed to sell or record it: mug, bottle, board game, appliance, tool, furniture), "
    "screenshot, other. "
    "Then give a frame-worthiness score from 1 to 10: 10 is a beautiful or meaningful photo worth seeing daily, "
    "1 is clutter. Photos of objects, documents or screenshots score 1 to 2. Reply as JSON."
)


def judge(cfg, jpeg):
    r = httpx.post(cfg["ollama"]["url"] + "/api/chat", timeout=300, json={
        "model": cfg["ollama"]["model"], "stream": False, "format": SCHEMA, "options": {"temperature": 0},
        "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(jpeg).decode()]}],
    })
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])
