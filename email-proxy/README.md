# Falcon IMAP proxy (email)

```
TROLL --plain IMAP--> [proxy :143 on the Pi] --verified TLS--> imap.mail.me.com:993
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

Installed files: `/opt/falcon-imap/falcon_imap_logproxy.py`, `/opt/falcon-imap/hebrew_words.txt`, `/etc/systemd/system/falcon-imap-logproxy.service`.

After editing the word list: `sudo systemctl restart falcon-imap-logproxy.service`.

## Useful flags

`--rewrite --keep-html --no-translit --no-clean --hebrew-mode {phonetic,literal,glyph} --glyph-width N --glyph-cte {8bit,quoted-printable,base64} --glyph-subject {encoded-q,encoded,raw,phonetic} --glyph-subject-label LABEL --hebrew-words FILE --version`

## TROLL findings

- Glyph mode: unknown charset `x-atari-st` with 8bit or quoted-printable works; base64 does not.
- Encoded-word subjects get a `{LABEL}` prefix in TROLL (default label `x` gives `{X}`); `--glyph-subject phonetic` avoids it.
- Quoted-printable soft line breaks need CRLF.
