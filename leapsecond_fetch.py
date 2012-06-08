#!env python

from ftplib import FTP
import socket
import re
import os

def fetch_latestleap(host = 'tycho.usno.navy.mil', path='/pub/ntp'):
    try:
        ftp = FTP(host)
    except socket.error:
        print "Failed to connect to host: '%s'" % host
        return

    ftp.login()

    ftp.cwd(path)

    file_list = ftp.nlst()

    # we are only interested in files that match the lattern
    # leap-seconds.nnnnnnnn

    lsec_pattern = re.compile('^leap-seconds\.([0-9]*)$')
    times_list = []
    match_dict = {}
    for fname in file_list:
        m = lsec_pattern.match(fname)
        if m:
            file_time = int(m.group(1))
            match_dict[file_time] = fname
            times_list.append(file_time)

    if len(times_list)==0:
        print "Did not find any leap second files @ ftp://%s%s" % (host, path)
        return

    latest_time = max(times_list)
    latest_file = match_dict[latest_time]

    print "Latest leapsecond file: %s" % latest_file

    print "Checking to see if we already have that file"
    if os.path.exists(latest_file):
        print "We already have the latest leapsecond file"
        print "latest_file: %s" % latest_file
        return

    print "A new leapsecond file exists, fetching it"
    ftp.retrbinary('RETR %s' % latest_file, 
                   open(latest_file, 'wb').write)
        
    
    ftp.close()

    print "Fetch complete"


if __name__ == "__main__":
    fetch_latestleap(host='tycho.usno.navy.mil', path='/pub/ntp')

    
