# Soulmate MCP adapter

This stdio MCP server exposes six privacy-minimal tools through a separately
scoped external service identity. It calls the owner's local daemon; it never
opens the SQLite database or exposes raw evidence, memories, outcomes, or notes.

Create an external identity in the desktop **External Agents** screen, copy the
API key shown once, then configure an MCP client with:

```json
{
  "command": "uv",
  "args": ["run", "decision-twin", "mcp"],
  "env": {
    "SOULMATE_BASE_URL": "http://127.0.0.1:7432",
    "SOULMATE_API_KEY": "<key-shown-once>"
  }
}
```

Grant only the scopes required by the selected tools. Revoking either the key or
the external identity takes effect on the next request, and every request is
recorded in the daemon's local audit log without its arguments or API key.
