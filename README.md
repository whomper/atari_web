# atari_web

Raspberry Pi gateway that gives an Atari Falcon (TOS/MagiC, STinG) access to modern email and the modern web.

| Folder | What it is |
|---|---|
| [`email-proxy/`](email-proxy/) | IMAP proxy for the TROLL mail client and iCloud Mail. Rewrites only what TROLL sees; originals stay untouched. |
| [`web-proxy/`](web-proxy/) | Notes and settings for the web side (WRP and Macproxy Classic on the same Pi). |

Pi: `192.168.68.126` (user `erez`). Falcon: `192.168.68.129`.
