# Session 04 / Exercise 04 — StoreX Nginx Reverse Proxy

This repository uses two authorized minimal Spring Boot HTTP fixtures because
the original `storex-user` and `storex-product` images/source were not supplied.
It adapts the Java 21 / Spring Boot 3.5.16 / Maven build patterns inspected in
previous assignments. These are real HTTP applications, not original StoreX
production services. No StoreX business functionality or production readiness
is claimed.

## Root cause: container-local localhost

The broken proxy settings pointed to `localhost:8081` and `localhost:8082`.
Inside the Nginx container, localhost means **that Nginx container**, not the
Docker host or another service. With no backend listening there, upstream
connections fail and Nginx may return 502.

Containers on the same user-defined Compose bridge network can discover one
another through Docker service-name DNS. The correct upstreams are:

```nginx
location /users/ {
    proxy_pass http://user_service:8081/;
}
location /products/ {
    proxy_pass http://product_service:8082/;
}
```

A 502 is not always a DNS problem: refused/timed-out upstream connections,
unavailable services, and invalid upstream responses can also cause it. Inspect
Nginx error logs, DNS, upstream port/reachability, and HTTP readiness separately.

## Architecture and port boundaries

- Compose project: `rikkei-ss04-storex04`.
- `nginx_proxy`: official `nginx:alpine`, only published mapping **`80:80`**.
- `user_service`: `storex-user:latest`, internal HTTP **8081**.
- `product_service`: `storex-product:latest`, internal HTTP **8082**.
- All three explicitly share bridge network `rikkei-ss04-storex04_storex`.
- `nginx.conf` mounts at `/etc/nginx/conf.d/default.conf` **read-only**.
- Backend ports are not host-published. Nginx uses the actual container ports;
  host port mappings are only for entering the network from outside.
- Backend healthchecks issue real HTTP `/health` requests and require status
  200. Nginx waits for both healthchecks, and its own healthcheck calls both
  health endpoints through the proxy. Runtime routing tests remain mandatory.

Unpublished ports do not prevent access by the Docker host, Docker administrators,
or peers attached to the same network. No unrelated service/stack needs to stop:
host port 80 was available during preflight. Exercise 03 remains operational.

## URI prefix contract and exact paths

Within `location /users/`:

| proxy_pass setting | Client request | Upstream path |
|---|---|---|
| `http://user_service:8081/` (URI `/`) | `/users/123` | `/123` |
| `http://user_service:8081` (no URI) | `/users/123` | `/users/123` |

With a URI in `proxy_pass`, Nginx replaces the matching normalized location
prefix with that URI. The trailing slash above therefore strips `/users/` or
`/products/`; no extra rewrite directive is needed. Without a URI, an original
request normally retains its complete path. These examples apply to the simple
prefix locations used here, not every regex/variable/rewrite configuration.

The fixtures support root `/`, `/123` (user), `/42` (product), and `/health`.
They report `receivedPath` from the actual servlet request URI so rewriting can
be verified independently of which route was requested publicly.

Exact `/users` and `/products` deliberately return **308** with relative
`Location: /users/` and `/products/`; they are not claimed as direct HTTP 200
responses. Query strings are retained. `/unknown` is deliberately configured
as 404. Standard Host and X-Forwarded-* proxy headers are forwarded.

## Build and run

Requires Docker/Compose, network access to Maven Central and Docker registry,
and free host port 80. Python 3 is needed only for the acceptance driver.

```bash
ss -ltnp '( sport = :80 )'
docker build -t storex-user:latest ./user-service
docker build -t storex-product:latest ./product-service
docker compose config -q
docker compose config
docker compose up -d
docker compose exec -T nginx_proxy nginx -t
docker compose ps
docker compose logs --tail 100 nginx_proxy
docker compose logs --tail 50 user_service
docker compose logs --tail 50 product_service
```

Each multi-stage Dockerfile pins its Maven 3.9.11 / Temurin 21 base images by
digest and fixes the JAR timestamp; Spring Boot 3.5.16 manages dependency
versions. The resulting containers run as an unprivileged user. The required
`nginx:alpine` tag remains mutable; the resolved image is recorded after testing.
Only the fixture source is sent to each build context. No database credentials,
old .env files, or previous assignment code changes are needed.

## Verify public routing and Docker DNS

```bash
curl -i http://localhost/users/
curl -i http://localhost/users/123
curl -i http://localhost/products/
curl -i http://localhost/products/42
curl -i http://localhost/users
curl -i http://localhost/products
curl -i http://localhost/unknown
docker compose exec -T nginx_proxy nslookup user_service.
docker compose exec -T nginx_proxy nslookup product_service.
docker compose exec -T nginx_proxy wget -qO- --header='Host: localhost' http://user_service:8081/123
docker compose exec -T nginx_proxy wget -qO- --header='Host: localhost' http://product_service:8082/42
python3 scripts/verify-routing.py --output /tmp/storex04-routing-results.json
```

The driver validates configuration and the real mounted Nginx config, waits for
health, tests every public route without automatically following redirects,
asserts service IDs/received URIs, checks internal DNS plus actual HTTP, and
checks backend port bindings and recent Nginx errors. Direct backend HTTP alone
does not satisfy proxy acceptance.

The trailing dot in `nslookup` prevents BusyBox from appending the host's DNS
search suffix. Direct `wget` still connects to the service name, but sends a
valid HTTP `Host: localhost` header because Tomcat rejects underscores in HTTP
hostnames. Nginx forwards the public Host header in the normal proxy flow.

## Observed results and evidence

Verified on **2026-11-11 (UTC+07:00)** using Docker 29.5.3 and Compose 5.1.4.
Both fixture builds returned Maven `BUILD SUCCESS`; runtime Java was Temurin
21.0.13 and the tested Nginx version was 1.31.8.

- `docker compose config -q`: passed, effective configuration assertions passed.
- Actual mounted configuration: `nginx -t` reported syntax OK and test successful.
- All three services running and healthy, with zero restarts.
- All public responses below were received through Nginx on host port 80,
  with the Nginx Server header, not directly from a host-published backend.

| Public path | Actual HTTP status | Backend service | Actual backend `receivedPath` / result |
|---|---|---|---|
| `/users/` | 200 | `user-service` | `/` |
| `/users/123` | 200 | `user-service` | `/123`, `userId=123`, Demo Shopper |
| `/products/` | 200 | `product-service` | `/` |
| `/products/42` | 200 | `product-service` | `/42`, `productId=42`, Demo Travel Mug |
| `/users/health` | 200 | `user-service` | `/health`, `status=UP` |
| `/products/health` | 200 | `product-service` | `/health`, `status=UP` |
| `/users` | 308 | Nginx redirect | `Location: /users/` |
| `/products` | 308 | Nginx redirect | `Location: /products/` |
| `/unknown` | 404 | Nginx | Not proxied |

Also verified `/users?source=lab` returns 308 with
`Location: /users/?source=lab`, and `/products/42?source=lab` returns the product
with `receivedPath=/42`. No 502 occurred in successful routing tests or the
inspected Nginx logs; no Nginx error/emergency entries were found.

From inside `nginx_proxy`, DNS resolved `user_service` to `172.27.0.3` and
`product_service` to `172.27.0.2`. HTTP to the actual internal ports 8081/8082
returned the expected fixture objects. Those IPs are observations, not
configuration. Docker inspect showed `{"8081/tcp":null}` and
`{"8082/tcp":null}`: neither backend has a published host port. Host listener
checks on 8081 and 8082 were also empty. The configuration mount has `RW=false`.

An initial generic BusyBox `nslookup` appended the host's DNS search suffix and
failed; the final test queried absolute DNS names. Initial direct `wget`
requests sent underscore-containing Host headers and received HTTP 400 from
Tomcat. The final direct test used the same valid Host contract as Nginx. Public
Nginx routes passed throughout; these internal diagnostic issues were not
misreported as proxy failures or hidden by altering service names.

Resolved image IDs:

```text
storex-user:latest     sha256:bf583effb4bfe1cb7203a831dafb47db6a5f54d5a7018d411fe2b9228529ead5
storex-product:latest  sha256:97d803cd68832ce17bc3ce49bdb3e9ef899689b0a545097871d6c6fce578401c
nginx:alpine          sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11
```

### Authentic evidence

Unmodified 2560×1440 PNGs were captured from live Foot terminals under Hyprland
using grim. PNG integrity and OCR checks confirmed the terminal evidence.
Screenshots are Release assets rather than source files:

- [Release ss04-bai-04](https://github.com/ng-trng-phcc/md05_ss04_bai_04/releases/tag/ss04-bai-04)
- [evidence_04.png](https://github.com/ng-trng-phcc/md05_ss04_bai_04/releases/download/ss04-bai-04/evidence_04.png):
  live healthy services and all four actual HTTP 200 proxy responses with service
  identifiers, object IDs, and received backend paths.
- [evidence_04_routing.png](https://github.com/ng-trng-phcc/md05_ss04_bai_04/releases/download/ss04-bai-04/evidence_04_routing.png):
  live Nginx validation, shared network/DNS/internal HTTP, absent backend host
  bindings, exact-path redirects, and unknown-route status.
- [storex04-routing-results.json](https://github.com/ng-trng-phcc/md05_ss04_bai_04/releases/download/ss04-bai-04/storex04-routing-results.json):
  actual recorded acceptance results.

SHA-256:

```text
e3a785b4433dc644e5ae43e1a13b82500a6ccd65870a0e3ebdba0e9cf75e4d1b  evidence_04.png
6b15a782d44d85c376379801792e04b6bfca66ea8f648388ec9874579d949e19  evidence_04_routing.png
```

### Resource preservation

After fetching the new Nginx image, a read-only before/after baseline preserved
36 existing containers, 12 networks, 43 volumes, and 31 images, all previous
assignment files/container states, host PostgreSQL, global Git identity, and
existing home worktree changes. New runtime resources are exactly the three
Exercise 04 containers, one project bridge, the two fixture images, the fetched
Nginx image, and retained build cache. No volumes or temporary test containers
were created. Audit/capture helpers and generated results remain outside the
repository in `/tmp/opencode/`.

## Limitations and lifecycle

Static upstream names are resolved by this simple Nginx configuration when it
loads. If a backend is recreated at a different IP, reload/recreate the proxy
after the backend is ready, or design dynamic upstream resolution separately.
`depends_on` gates startup; it does not guarantee later automatic recovery.

Keep the verified stack running. If stopping it intentionally later, use
`docker compose stop`. No global Docker cleanup or unrelated-resource deletion
is part of this exercise.
