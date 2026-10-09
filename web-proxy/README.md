# Web proxy notes (WRP + Macproxy Classic)

## WRP (Web Rendering Proxy, tenox7/wrp) - port 8080

Chromium runs on the Pi and serves pages to the Falcon's CAB browser. Needs 64-bit ARM (Pi 4/5).

The patched build is upstream WRP (https://github.com/tenox7/wrp) plus `wrp-custom.patch` in this folder. The patch already includes the changed `Dockerfile`; a copy is here for reference.

### Rebuild on the Pi

```
git clone https://github.com/tenox7/wrp.git ~/wrp-custom
cd ~/wrp-custom
git apply ~/wrp-custom.patch      # copy wrp-custom.patch here first
docker build -t wrp-custom .
docker rm -f wrp
docker run -d --name wrp --restart unless-stopped -p 8080:8080 \
  -v ~/wrp-profile:/wrp-profile wrp-custom -m html -profile /wrp-profile -t gif
```

The patch was made against the upstream checkout of 15 Sep 2026; if upstream has moved on and `git apply` complains, check out that date first (`git checkout $(git rev-list -1 --before=2026-09-16 HEAD)`).

### What the patch changes

- `Dockerfile`: builds from the local patched source (`COPY . .`) instead of cloning upstream again.
- `shtml.go`: `resize.NearestNeighbor` -> `resize.Lanczos3` (sharper images).
- `shtml.go`: image URLs are a SHA256 hash of (url + type + size + option) instead of `shortuuid.New()`, so CAB can cache images across reloads. The unused `shortuuid` import is removed.
- `shtml.go`: `Cache-Control: public, max-age=86400` on `imgServerTxt`.
- `wrp.go`: text typed in the address box with no spaces and a dot (e.g. `example.com`) is opened as `http://example.com`; anything else goes to the search engine.

Settings that are NOT in the patch (they are `docker run` flags): `-m html` (HTML render mode) and `-t gif` (GIF images; PNG stalled CAB).

Note: `wrp-session.json` in the profile folder overrides command-line image type; change it with the T button in the UI or delete the file.

Open idea, not applied: `http.DefaultClient` in `fetchImage` has no timeout, so one hung image can block a whole page. Use `&http.Client{Timeout: 10 * time.Second}`.

## Macproxy Classic (rdmark/macproxy_classic) - port 5001

TLS-terminating proxy for the Highwire browser:

```
docker run -d --name macproxy --restart unless-stopped -p 5001:5001 rdmark/macproxy:latest
```

If Highwire rejects a port number, map to port 80 instead: `-p 80:5001`.
