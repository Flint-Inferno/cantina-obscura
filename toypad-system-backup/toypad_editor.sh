#!/bin/bash
sleep 1 && sudo -u "${SUDO_USER:-$USER}" xdg-open http://localhost:8080 &
sudo python3 /home/Cantina_Obscura/toypad_led_editor.py
