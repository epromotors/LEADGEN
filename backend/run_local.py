import sys
import asyncio
import selectors
import uvicorn

def main():
    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        loop="none",
        log_level="info",
    )
    server = uvicorn.Server(config)
    
    if sys.platform == "win32":
        # Python 3.14 on Windows loop_factory for psycopg compatibility
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.run(server.serve(), loop_factory=loop_factory)
    else:
        asyncio.run(server.serve())

if __name__ == "__main__":
    main()
