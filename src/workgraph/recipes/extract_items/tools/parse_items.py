"""The deterministic half of extract_items (a SOLVE node, backend: subprocess): the work items out of a model's reply.

stdin   {"reply": the model's reply, "kinds": "a, b", "stages": "x, y", "max_items": "40"}
stdout  {"text": JSON text {"items": [{title, kind, stages, status, summary}, ...]}}   (an empty list when the reply holds no usable JSON)

The reply may have chatter or a markdown fence around the JSON object. An item stays only if it is a mapping with a title and one of the allowed
kinds; its stage tags are cut down to the allowed ones. At most max_items stay.
"""
import json
import sys


def json_object(raw):
    """The outermost {...} in the text as a dict, else {} (the same rule the Python path used)."""
    raw = str(raw)
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        out = json.loads(raw[i:j + 1])
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def names(text):
    return [x.strip() for x in str(text).split(",") if x.strip()]


def clean(reply, kinds, stages, max_items):
    items = json_object(reply).get("items", [])
    items = items if isinstance(items, list) else []
    out = []
    for it in items[:max_items]:
        if not isinstance(it, dict) or not it.get("title") or it.get("kind") not in kinds:
            continue
        tags = it.get("stages")
        tags = [tags] if isinstance(tags, str) else (tags if isinstance(tags, list) else [])
        out.append({**it, "stages": [t for t in (str(x).strip() for x in tags) if t in stages]})
    return out


def main():
    job = json.loads(sys.stdin.read() or "{}")
    try:
        limit = int(job.get("max_items") or 40)
    except ValueError:
        limit = 40
    items = clean(job.get("reply", ""), names(job.get("kinds", "")), names(job.get("stages", "")), limit)
    print(json.dumps({"text": json.dumps({"items": items}, ensure_ascii=False)}))


if __name__ == "__main__":
    main()
