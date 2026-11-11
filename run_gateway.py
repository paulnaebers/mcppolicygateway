# Einstieg für einen MCP-Host. Den absoluten Pfad zu dieser Datei verwenden.

import asyncio

from gateway.proxy import main


if __name__ == "__main__":
    asyncio.run(main())
