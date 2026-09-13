"""Entry point: python -m gemini_web2api"""
import argparse
import os

from .config import CONFIG, load_config, find_config
from .models import MODELS
from .gemini import HAS_HTTPX
from .hardened_server import HardenedGeminiHandler, HardenedThreadedServer
from .security import validate_bind
from . import __version__


def main():
    parser = argparse.ArgumentParser(description="Gemini Web to OpenAI-compatible API")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--cookie-file", type=str, default=None)
    parser.add_argument("--proxy", type=str, default=None, help="HTTP proxy, e.g. http://127.0.0.1:7890")
    parser.add_argument("--version", action="version", version=f"gemini-agent-bridge {__version__}")
    args = parser.parse_args()

    config_path = args.config or os.environ.get("GEMINI_WEB2API_CONFIG") or find_config()
    if config_path:
        load_config(config_path)

    if args.port is not None:
        CONFIG["port"] = args.port
    if args.host is not None:
        CONFIG["host"] = args.host
    if args.cookie_file:
        CONFIG["cookie_file"] = args.cookie_file
    if args.proxy:
        CONFIG["proxy"] = args.proxy

    validate_bind(str(CONFIG["host"]), CONFIG.get("api_keys") or [])
    if not CONFIG.get("cookie_file"):
        raise SystemExit("Gemini Web authentication cookie is required for the modern backend")

    port = int(CONFIG["port"])
    server = HardenedThreadedServer((CONFIG["host"], port), HardenedGeminiHandler)
    print(f"gemini-agent-bridge v{__version__}")
    print(f"  Listening: http://{CONFIG['host']}:{port}")
    print(f"  Base URL:  http://{CONFIG['host']}:{port}/v1")
    print(f"  Models:    {', '.join(MODELS.keys())}")
    print("  Backend:   modern gemini-webapi")
    print("  Auth:      local-only by default; API keys required for remote bind")
    print(f"  Streaming: {'httpx (true streaming)' if HAS_HTTPX else 'buffered fallback'}")
    print(f"  Body limit: {int(CONFIG['max_request_body_bytes'])} bytes")
    print(f"  Image limit: {int(CONFIG['max_image_bytes'])} bytes")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
