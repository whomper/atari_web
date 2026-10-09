# troll-proxy (email for TROLL)

```
TROLL --plain IMAP :1143--> [falcon_imap_logproxy.py] --verified TLS--> imap.mail.me.com:993
TROLL --plain SMTP :25  --> Postfix on the Pi (relays to iCloud; not in this folder)
```

| Port on the Pi (192.168.68.126) | For | Program |
|---|---|---|
| 1143 | TROLL incoming (IMAP) | troll-proxy (`falcon_imap_logproxy.py`) |
| 25 | TROLL outgoing (SMTP) | Postfix on the Pi, set up separately |
| 143, 587 | MAIL.PRG incoming / outgoing | mail-proxy: a plain TLS tunnel, see [whomper/mail `gateway/`](https://github.com/whomper/mail/tree/main/gateway) |

troll-proxy is for TROLL only. MAIL.PRG does its own MIME, HTML and Hebrew
layout and wants the original messages, so it uses mail-proxy on the
standard ports; both run side by side on the Pi.

In TROLL: IMAP server `192.168.68.126` port `1143`, SMTP server
`192.168.68.126` port `25`.

The Pi's firewall (ufw) must let the Falcon in on these ports:

```
sudo ufw allow from 192.168.68.129 to any port 1143 proto tcp   # troll-proxy
sudo ufw allow from 192.168.68.129 to any port 25 proto tcp     # Postfix
sudo ufw allow from 192.168.68.129 to any port 143 proto tcp    # mail-proxy
sudo ufw allow from 192.168.68.129 to any port 587 proto tcp    # mail-proxy
```

Rewrites only what TROLL downloads. Originals in iCloud are never modified.

- Fixes multipart `Content-Type` (TROLL needs `boundary="..."` as the only parameter, no trailing `;`, no `type=`).
- Strips HTML (keeps text/plain, or converts HTML-only mail to text).
- Removes invisible characters and emoji; typographic punctuation becomes ASCII.
- Hebrew: `--hebrew-mode glyph` shows real Hebrew letters in the Atari ST character set (0xC2-0xDC) in visual order; `phonetic` gives "Shalom Olam"; `literal` is letter-for-letter.
- Passwords and message bodies are never logged.

## Install on the Pi

```
scp falcon_imap_logproxy.py falcon-imap-logproxy.service hebrew_words.txt install_falcon_proxy.sh erez@192.168.68.126:~/
ssh erez@192.168.68.126 'bash ~/install_falcon_proxy.sh'
```

Installed files: `/opt/falcon-imap/falcon_imap_logproxy.py`, `/opt/falcon-imap/hebrew_words.txt`, `/etc/systemd/system/falcon-imap-logproxy.service` (IMAP on 1143).

The port is in `falcon-imap-logproxy.service` (`--port 1143`); keep it off 143 and 587, which mail-proxy uses.

After editing the word list: `sudo systemctl restart falcon-imap-logproxy.service`.

## Useful flags

`--rewrite --keep-html --no-translit --no-clean --hebrew-mode {phonetic,literal,glyph} --glyph-width N --glyph-cte {8bit,quoted-printable,base64} --glyph-subject {encoded-q,encoded,raw,phonetic} --glyph-subject-label LABEL --hebrew-words FILE --version`

## TROLL findings

- Glyph mode: unknown charset `x-atari-st` with 8bit or quoted-printable works; base64 does not.
- Encoded-word subjects get a `{LABEL}` prefix in TROLL (default label `x` gives `{X}`); `--glyph-subject phonetic` avoids it.
- Quoted-printable soft line breaks need CRLF.
