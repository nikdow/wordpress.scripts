#!/usr/bin/env python3
import subprocess
import requests

def update_fail2ban_whitelist(json, jail_name):
    response = requests.get(json)
    data = response.json()

    for ip in data:
             try:
                 subprocess.run(['fail2ban-client', 'set', jail_name, 'addignoreip', ip], check=True)
                 print(f"Whitelisted {ip} in {jail_name}")
             except subprocess.CalledProcessError as e:
                 print(f"Error whitelisting {ip}: {e}")
    subprocess.run(['fail2ban-client', 'reload' ])
# params and invoke
json_url = 'https://jetpack.com/ips-v4.json'
fail2ban_jail = 'wpxmlrpc'  # Replace with your jail name
update_fail2ban_whitelist(json_url, fail2ban_jail)
