# Deployment and operations

## Local development

Use the package entrypoint from the project virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m gemini_web2api
```

For a local-only agent setup, prefer:

```json
{
  "host": "127.0.0.1",
  "port": 8081
}
```

Binding to `0.0.0.0` makes the HTTP service reachable from other network interfaces and therefore requires deliberate authentication/network controls.

## Process management

Only one bridge implementation should own a production port.

Before starting a service:

```bash
ss -ltnp | grep ':8081' || true
```

Use the maintained package entrypoint consistently:

```bash
python -m gemini_web2api
```

Do not mix the historical top-level script and package entrypoint on the same port.

## Docker

The repository contains a Dockerfile and Compose configuration. Configuration and session files should be mounted rather than baked into an image.

Example:

```bash
cp config.example.json config.json

docker build -t gemini-web2api .

docker run --rm \
  -p 8081:8081 \
  -v "$PWD/config.json:/app/config.json:ro" \
  gemini-web2api
```

If authentication is required, mount the session file separately and point `cookie_file` inside the container at the mounted path. Never commit or bake the session into a Docker layer.

## Proxy

The modern upstream client accepts an explicit `proxy` configuration. Standard proxy environment variables may also be respected by the underlying HTTP stack.

Use an explicit proxy only when necessary and test the proxy path separately from authentication/session validity.

## Network isolation

For a workstation-only bridge:

```text
agent client → 127.0.0.1:8081 → Gemini Web
```

For a shared network deployment:

```text
client network → authenticated gateway/reverse proxy → bridge → Gemini Web
```

The project does not claim to provide a hardened internet-facing security boundary by itself.

## Health checks

There is no claim that a simple process-alive check proves upstream health.

Recommended layered checks:

1. TCP/listener check.
2. `/v1/models` protocol check.
3. authenticated upstream generation check.
4. streaming check.
5. real-client smoke check when upgrading the transport.

## Release operations

Before treating a transport change as released:

- run the deterministic suite;
- run compile and diff checks;
- run trajectory/performance regressions;
- run credential scans;
- verify current release-status documentation;
- perform a fresh authenticated live Gemini Web test;
- perform Hermes/OpenCode real-client checks.
