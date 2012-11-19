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

    # From the folks at nist:
    # Levine, Judah Dr. judah.levine@nist.gov via icecube.wisc.edu 
    # to Matt 
    # Hello,
    # The expiration date of the file is changed as I get new information from the 
    # International Earth Rotation Service (IERS) about future leap seconds. The extension changes
    # ONLY when a new leap second has been announced. So, if the extension is unchanged, then no new 
    # leap second is pending. If the expiration date has changed then this is based on new information
    # from the IERS.
    #
    # ANNOYING...  no way to check and see if the file has been updated without fetching it

    print "A fetching: %s" % latest_file 
    ftp.retrbinary('RETR %s' % latest_file, 
                   open(latest_file, 'wb').write)
        
    
    ftp.close()

    print "Fetch complete"


if __name__ == "__main__":
    fetch_latestleap(host='tycho.usno.navy.mil', path='/pub/ntp')

    
