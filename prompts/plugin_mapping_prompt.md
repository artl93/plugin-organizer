You are updating a Logic Pro plug-in mapping JSON. Return ONLY valid JSON.

Requirements:
- Output must be a full plugin_mapping JSON object with the same schema.
- Only use Logic categories already present in the input JSON.
- Do not add or remove categories.
- Prefer explicit overrides for known plug-ins and vendor-specific rules.
- Keep existing rules and improve or extend them as needed.
- If unsure, leave the existing mapping intact.

Research policy:
- You are explicitly allowed to use web tools to look up plug-in catalogs and categories.
- If a plug-in name is ambiguous, use vendor/product pages to confirm the effect type.
- Cite nothing; return only JSON.

Input JSON includes:
- categories (Logic tag categories)
- plugins (installed AU list)
- current_mapping (existing plugin_mapping.json)

Input JSON:
{{INPUT_JSON}}
