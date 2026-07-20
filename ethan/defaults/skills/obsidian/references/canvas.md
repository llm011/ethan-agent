# JSON Canvas Spec 1.0

A canvas file (`.canvas`) contains nodes and edges in JSON format.

```json
{
  "nodes": [
    {
      "id": "6f0ad84f44ce9c17",
      "type": "text",
      "x": 0, "y": 0, "width": 400, "height": 200,
      "text": "# Hello World"
    }
  ],
  "edges": []
}
```

## Node Types
- `text`: Plain text with Markdown.
- `file`: Path to file within the vault.
- `link`: External URL.
- `group`: Visual containers.

## Coordinates
- `x` increases right, `y` increases down.
- Position is the top-left corner.
- Space nodes 50-100px apart.
