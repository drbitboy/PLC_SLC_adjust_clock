"""
sntp.py - minimal Simple Network Time Protocol (SNTP) client

Cf. https://seriot.ch/projects/tiny_ntp_client.html

Typical execution and output:

    > python sntp.py
    2022-03-12T00:09:13    <== Time from SNTP server
    2208988800.0           <== Seconds from 1900 to 1970
    1968-01-20 03:14:08    <== 2**31 seconds past 1900-01-01T00:00:00

"""
import struct
import socket
import select
import traceback
from datetime import datetime,timedelta

### Build request & server's (address,port), create socket, send request
req_addr = b'#'+b' '*47,('time.windows.com',123,)
sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
sock.sendto(*req_addr)

### Wait 3s at a time for the response
while True:
    try:
        assert select.select([sock],[],[],3),'Failed; Control-C to exit'
        break
    except KeyboardInterrupt: exit(-1)
    except: traceback.print_exc()

### Get response, parse four MSByte-first bytes of seconds since 1900
recvfrom = sock.recvfrom(6144)
sock.close()
sntpsecs = struct.unpack('>I',recvfrom[0][40:44])[0]

### Convert to time since the epoch and print
print((datetime(1900,1,1,0,0)+timedelta(seconds=sntpsecs)).isoformat())

### Print seconds offset from 1900 to 1970, date of bit30/31 rollover
print((datetime(1970,1,1,0,0)-datetime(1900,1,1,0,0)).total_seconds())
print(datetime(1900,1,1,0,0)+timedelta(seconds=1<<31))
