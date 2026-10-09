# atari_web

Raspberry Pi gateway that gives an Atari Falcon (TOS/MagiC, STinG) access to modern email and the modern web.

| Folder | What it is |
|---|---|
| [`email-proxy/`](email-proxy/) | troll-proxy: IMAP (port 1143) for the TROLL mail client and iCloud Mail. Rewrites only what TROLL sees; originals stay untouched. |
| [`web-proxy/`](web-proxy/) | Notes and settings for the web side (WRP and Macproxy Classic on the same Pi). |

Pi: `192.168.68.126` (user `erez`). Falcon: `192.168.68.129`.

## Mail ports on the Pi

| Port | Used by | Proxy |
|---|---|---|
| 143 (IMAP), 587 (SMTP) | MAIL.PRG | mail-proxy, from [whomper/mail `gateway/`](https://github.com/whomper/mail/tree/main/gateway) |
| 1143 (IMAP) | TROLL | troll-proxy, this repository's [`email-proxy/`](email-proxy/) |
| 25 (SMTP) | TROLL | Postfix on the Pi |
