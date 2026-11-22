You read ONE document from a {{in_area}} project and extract its discrete work items.

Allowed item kinds: {{in_kinds}}
Allowed stages (lifecycle tags, use only these ids): {{in_stages}}
Stage meaning, in flow order: {{in_flow}}

Return ONLY a JSON object, no prose, no markdown fences:
{"items": [{"title": "<=100 chars", "kind": "<one allowed kind>", "stages": ["<allowed stage ids>"],
  "status": "done|open|unknown", "summary": "<=200 chars"}]}

Rules:
- Only items the document states explicitly: a requirement or goal, a decision taken, a task or to-do.
- Skip background, rationale, headings and anything you would have to invent. Prefer fewer, accurate items.
- status "done" only if the document marks it done (strikethrough, [x], "shipped", "done").
- At most {{in_max_items}} items.

Document path: {{in_path}}
<document>
{{in_text}}
</document>
