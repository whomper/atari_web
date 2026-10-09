#!/bin/bash
# Installs / updates troll-proxy from the files in this folder:
#   IMAP 1143  falcon_imap_logproxy.py (rewrites mail for TROLL)
#   SMTP 1025  stunnel to iCloud (troll-smtp.conf)
# The standard ports 143 and 587 are left for mail-proxy (MAIL.PRG).
set -e
cd "$(dirname "$0")"
for f in falcon_imap_logproxy.py falcon-imap-logproxy.service hebrew_words.txt troll-smtp.conf; do
  [ -f "$f" ] || { echo "MISSING FILE: $f (copy all files first)"; exit 1; }
done
python3 falcon_imap_logproxy.py --version
sudo install -d -m 755 /opt/falcon-imap
sudo install -m 644 falcon_imap_logproxy.py /opt/falcon-imap/
# never overwrite a word list you have edited
[ -f /opt/falcon-imap/hebrew_words.txt ] || sudo install -m 644 hebrew_words.txt /opt/falcon-imap/
sudo install -m 644 falcon-imap-logproxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable falcon-imap-logproxy.service >/dev/null 2>&1
sudo systemctl restart falcon-imap-logproxy.service

# SMTP for TROLL
command -v stunnel4 >/dev/null || command -v stunnel >/dev/null || sudo apt-get install -y -qq stunnel4
sudo install -m 644 troll-smtp.conf /etc/stunnel/
[ -f /etc/default/stunnel4 ] && sudo sed -i 's/^ENABLED=0/ENABLED=1/' /etc/default/stunnel4
sudo systemctl enable stunnel4 >/dev/null 2>&1 || true
sudo systemctl restart stunnel4

sleep 3
echo "--- service state: $(systemctl is-active falcon-imap-logproxy.service)"
echo "--- last log lines:"
sudo journalctl -u falcon-imap-logproxy.service -n 4 --no-pager | cut -c1-220
echo "--- listening ports (expect python3 on :1143 and stunnel on :1025;"
echo "    :143 and :587 are mail-proxy's, if it is installed):"
sudo ss -ltnp | grep -E ':(143|1143|587|1025)\b' || echo "(nothing listening!)"
