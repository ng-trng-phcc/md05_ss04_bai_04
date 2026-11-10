"""Verify real public Nginx routes and internal service HTTP/DNS without port exposure."""

import argparse
import http.client
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "rikkei-ss04-storex04"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path)
args = parser.parse_args()


def run(*command):
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=True)
    return result.stdout.strip()


def compose(*command):
    return run("docker", "compose", *command)


def request(path):
    client = http.client.HTTPConnection("localhost", 80, timeout=10)
    try:
        client.request("GET", path)
        response = client.getresponse()
        body = response.read().decode()
        return {"path": path, "status": response.status, "headers": dict(response.getheaders()),
                "body": json.loads(body) if "application/json" in response.getheader("Content-Type", "") else body}
    finally:
        client.close()


compose("config", "-q")
config = json.loads(compose("config", "--format", "json"))
assert config["name"] == PROJECT
assert set(config["services"]) == {"nginx_proxy", "user_service", "product_service"}
assert {s["image"] for s in config["services"].values()} == {"nginx:alpine", "storex-user:latest", "storex-product:latest"}
for service in config["services"].values():
    assert set(service["networks"]) == {"storex"}
assert config["networks"]["storex"]["driver"] == "bridge"
nginx_config = (ROOT / "nginx.conf").read_text()
assert "proxy_pass http://user_service:8081/;" in nginx_config
assert "proxy_pass http://product_service:8082/;" in nginx_config
assert "localhost" not in nginx_config and "rewrite " not in nginx_config
proxy = config["services"]["nginx_proxy"]
assert proxy["ports"][0]["target"] == 80 and proxy["ports"][0]["published"] == "80"
mount = proxy["volumes"][0]
assert mount["type"] == "bind" and mount["target"] == "/etc/nginx/conf.d/default.conf" and mount["read_only"]
assert Path(mount["source"]) == ROOT / "nginx.conf"
for name in ("user_service", "product_service"):
    assert not config["services"][name].get("ports")
    assert proxy["depends_on"][name]["condition"] == "service_healthy"
print("PASS: effective Compose/upstream/network/readonly mount/no-backend-host-port assertions", flush=True)

deadline = time.monotonic() + 90
while True:
    ids = compose("ps", "-q").splitlines()
    containers = json.loads(run("docker", "inspect", *ids)) if ids else []
    if len(containers) == 3 and all(c["State"].get("Health", {}).get("Status") == "healthy" for c in containers):
        break
    assert time.monotonic() < deadline, "services did not become healthy"
    time.sleep(1)
by_service = {c["Config"]["Labels"]["com.docker.compose.service"]: c for c in containers}
for name, container in by_service.items():
    assert container["State"]["Running"] and container["RestartCount"] == 0
    assert set(container["NetworkSettings"]["Networks"]) == {PROJECT + "_storex"}
    if name != "nginx_proxy":
        assert not container["HostConfig"]["PortBindings"]
        assert all(bindings is None for bindings in container["NetworkSettings"]["Ports"].values())
actual_mount = next(m for m in by_service["nginx_proxy"]["Mounts"] if m["Destination"] == "/etc/nginx/conf.d/default.conf")
assert not actual_mount["RW"]
validation = compose("exec", "-T", "nginx_proxy", "nginx", "-t")
assert "test is successful" in validation
print(validation, flush=True)

matrix = []
for path, service, received, identity in (
        ("/users/", "user-service", "/", None),
        ("/users/123", "user-service", "/123", ("userId", 123)),
        ("/products/", "product-service", "/", None),
        ("/products/42", "product-service", "/42", ("productId", 42)),
        ("/users/health", "user-service", "/health", ("status", "UP")),
        ("/products/health", "product-service", "/health", ("status", "UP"))):
    result = request(path)
    assert result["status"] == 200
    assert result["headers"]["Server"].startswith("nginx/")
    assert result["body"]["service"] == service and result["body"]["receivedPath"] == received
    if identity:
        assert result["body"][identity[0]] == identity[1]
    matrix.append(result)
    print("PUBLIC ROUTE:", path, result["status"], json.dumps(result["body"]), flush=True)
for path in ("/users", "/products"):
    result = request(path)
    assert result["status"] == 308 and result["headers"]["Location"] == path + "/"
    matrix.append(result)
    print("EXACT PATH:", path, "308 Location=" + result["headers"]["Location"], flush=True)
unknown = request("/unknown")
assert unknown["status"] == 404
matrix.append(unknown)
print("UNKNOWN PATH: /unknown", unknown["status"], flush=True)
query_redirect = request("/users?source=lab")
assert query_redirect["status"] == 308 and query_redirect["headers"]["Location"] == "/users/?source=lab"
query_route = request("/products/42?source=lab")
assert query_route["status"] == 200 and query_route["body"]["productId"] == 42 and query_route["body"]["receivedPath"] == "/42"

internal = {}
for name, port, path, service in (("user_service", 8081, "/123", "user-service"), ("product_service", 8082, "/42", "product-service")):
    # Absolute DNS query avoids BusyBox appending the host DNS search suffix.
    dns = compose("exec", "-T", "nginx_proxy", "nslookup", name + ".")
    address = by_service[name]["NetworkSettings"]["Networks"][PROJECT + "_storex"]["IPAddress"]
    assert address in dns
    # The required Docker names contain underscores, which Tomcat rejects in Host.
    body = json.loads(compose("exec", "-T", "nginx_proxy", "wget", "-q", "-T", "3", "--header=Host: localhost", "-O", "-", f"http://{name}:{port}{path}"))
    assert body["service"] == service and body["receivedPath"] == path
    internal[name] = {"port": port, "dns": dns, "body": body, "published_ports": False}
    print("INTERNAL DNS + HTTP:", name, port, json.dumps(body), flush=True)
for name in config["services"]:
    logs = compose("logs", "--no-color", "--tail", "100", name)
    assert "[error]" not in logs and "[emerg]" not in logs
    if name == "nginx_proxy":
        assert ' 502 ' not in logs
network = json.loads(run("docker", "network", "inspect", PROJECT + "_storex"))[0]
assert network["Driver"] == "bridge" and set(network["Containers"]) == {c["Id"] for c in containers}
results = {"checked_at": datetime.now(timezone.utc).isoformat(), "project": PROJECT,
           "nginx_validation": validation, "routing_matrix": matrix, "internal": internal,
           "states": {name: {"healthy": True, "restarts": c["RestartCount"], "id": c["Id"]} for name, c in by_service.items()},
           "backend_ports_unpublished": True, "config_mount_read_only": True,
           "query_redirect": query_redirect, "query_route": query_route}
if args.output:
    assert args.output.parent.is_dir()
    args.output.write_text(json.dumps(results, indent=2) + "\n")
print("PASS: all mandatory HTTP requests passed THROUGH Nginx, correct service/IDs/received URIs, exact redirects, unknown 404, internal DNS/HTTP, no 502, no backend host exposure", flush=True)
