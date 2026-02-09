#!/usr/bin/env python3
import re
import sys
import csv

pattern = r'([a-zA-z0-9\-_\.]+)\:(\d+)\s([\d\.]+)\s(\d+)\s\[(\d+)\/([A-zA-z]{3})\/(\d{4}):(\d{2}):(\d{2}):(\d{2})\s[\+]?[\d]+\]\s"(GET|POST|PUT)\s([^\s]+)\sHTTP\/([\d\.]+)"\s(\d+)\s(\d+)\s(\d+)\s"([^"]+)"\s"([^"]+)"'

def read_file(filename):
    count = 0
    with open(filename+'.csv', 'w', newline='', encoding='UTF8') as f_out:
        writer = csv.writer(f_out)
        writer.writerow(['server_name', 'port', 'ip', 'apache process', 'day', 'month', 'year', 'hour', 'minute', 'second', 'request', 'path', 'protocol', 'status', 'size', 'response (seconds)', 'referrer', 'user agent'])
        with open(filename, 'r') as f:
            for content in f:
                match = re.match(pattern, content)
                if match:
                    writer.writerow(match.groups())
                    count = count + 1
    return count

filein = sys.argv[1]
count = read_file(filein)
print (count)