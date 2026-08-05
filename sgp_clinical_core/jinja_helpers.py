import json

def parse_notes_json(notes_str):
    """Safely parse notes JSON string for use in print formats."""
    if not notes_str:
        return {}
    try:
        return json.loads(notes_str)
    except Exception:
        return {}
