# Web proxy notes (WRP + Macproxy Classic)

Status: documentation only. The patched WRP source lives on the Pi in `~/wrp-custom` and has NOT been uploaded yet (see bottom).

## WRP (Web Rendering Proxy, tenox7/wrp) - port 8080

Chromium runs on the Pi and serves pages to the Falcon's CAB browser. Needs 64-bit ARM (Pi 4/5).

Custom image built from the patched local source, run with:

```
docker run -d --name wrp --restart unless-stopped -p 8080:8080 \
  -v ~/wrp-profile:/wrp-profile wrp-custom -m html -profile /wrp-profile -t gif
```

Patches applied to the upstream source:
- default render mode `html` (`-m html`)
- `shtml.go`: `resize.NearestNeighbor` -> `resize.Lanczos3` (sharper images)
- default image type GIF (`-t gif`); PNG stalled CAB
- deterministic SHA256-based image URLs instead of `shortuuid.New()` so CAB can cache images; unused `shortuuid` import removed
- `Cache-Control: public, max-age=86400` on `imgServerTxt`
- Dockerfile modified to build from local patched source instead of re-cloning upstream

Note: `wrp-session.json` in the profile overrides command-line image type; change it with the T button in the UI or delete the file.

Open idea: `http.DefaultClient` in `fetchImage` has no timeout, so one hung image can block a whole page. Use `&http.Client{Timeout: 10 * time.Second}`.

## Macproxy Classic (rdmark/macproxy_classic) - port 5001

TLS-terminating proxy for the Highwire browser:

```
docker run -d --name macproxy --restart unless-stopped -p 5001:5001 rdmark/macproxy:latest
```

If Highwire rejects a port number, map to port 80 instead: `-p 80:5001`.

## To upload the patched WRP source

On the Pi: `cd ~/wrp-custom && git diff > wrp-custom.patch` (plus the modified `Dockerfile`), then send them to Claude or copy them into `web-proxy/`.
