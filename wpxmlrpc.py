#!/usr/bin/env python3
import subprocess
import requests

def is_origin_facing(el):
    return el['service'] == 'CLOUDFRONT_ORIGIN_FACING'

def update_cloudfront_whitelist(json, jail_name):
    response = requests.get(json)
    data = response.json()
    prefixes = data['prefixes']
    origin_facing = list(filter(is_origin_facing, prefixes))
    for stuff in origin_facing:
        ip = stuff['ip_prefix']
        try:
            subprocess.run(['fail2ban-client', 'set', jail_name, 'addignoreip', ip], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error whitelisting {ip}: {e}")

def update_fail2ban_whitelist(json, jail_name):
    response = requests.get(json)
    data = response.json()

    for ip in data:
             try:
                 subprocess.run(['fail2ban-client', 'set', jail_name, 'addignoreip', ip], check=True)
             except subprocess.CalledProcessError as e:
                 print(f"Error whitelisting {ip}: {e}")
# params and invoke
json_url = 'https://jetpack.com/ips-v4.json'
fail2ban_jail = 'wpxmlrpc'  # Replace with your jail name
update_fail2ban_whitelist(json_url, fail2ban_jail)
json_url = 'https://ip-ranges.amazonaws.com/ip-ranges.json'
fail2ban_jail = 'cloudfront'
update_cloudfront_whitelist(json_url, fail2ban_jail)
subprocess.run(['fail2ban-client', 'reload' ])