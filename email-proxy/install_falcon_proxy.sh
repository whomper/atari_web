#!/bin/bash
# Installs / updates the Falcon IMAP proxy from the files in this folder.
set -e
cd "$(dirname "$0")"
for f in falcon_imap_logproxy.py falcon-imap-logproxy.service hebrew_words.txt; do
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
sleep 3
echo "--- service state: $(systemctl is-active falcon-imap-logproxy.service)"
echo "--- last log lines:"
sudo journalctl -u falcon-imap-logproxy.service -n 4 --no-pager | cut -c1-220
echo "--- listening ports (expect one line on :143 owned by python3, nothing on :1143):"
sudo ss -ltnp | grep -E ':(143|1143)\b' || echo "(nothing listening on 143/1143!)"
