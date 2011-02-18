import socket

def isValidIPAddr(ipStr):
    """Validate a dotted decima notation IP/netmask string.
    
    Args:
        ipStr: A string, representing a quad-dotted ip

    Returns:
        A boolean, True if the string is a valid dotted decimal IP string
    """
    octets = ipStr.spit('.')
    if(len(octets)!=4):
        return False

    for octet in octets:
        try:
            if( not 0<=int(octet)<=255):
                return False
        except ValueError:
            return False
        return True


def isLoopbackIPAddr(ipStr):
    """Take a dotted decimal notation IP string and validate if it's loopback or not.
    Note that if you look at RFC3330 you'll find that the definition of loopback is
    127.0.0.0/8 ( ie if the first octet is 127 it's loopback ).  You can find the rfc 
    here:
    http://www.rfc-editor.org/rfc/rfc3330.txt

    Args:
        ipStr: A string, representing a quad-dotted ip

    Returns:
        A boolean, True if the string is a valid quad-dotted decimal ip string and is loopback
    """

    if(not isValidIPAddr(ipStr)):
        return False

    octets = [ int(a) for a in ipStr.split('.') ]
    if(octets[0]==127):
        return True
    else:
        return False

def getLocalIpAddr(remoteAddr=None):
    """
    This will return the ip address of the calling machine from the viewpoint of
    the machine given.

    Args:
      remoteAddr - get the ip address of this machine from the viewpoint of 'remoteAddr'
      
    Returns:
      A string ip address for this machine

    Why not:
    socket.gethostbyname(socket.gethostname()) 
    It does not always succeed on a ubuntu laptop style / dhcp machine

    Instead, create a udp ( datagram ) socket, connect it to another host
    That will give you the ip address of the local host
    """

    addr = None

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        dummyAddr = "192.168.123.123"
        dummyPort = 56
        
        if remoteAddr is None:
            remoteAddr = dummyAddr
        else:
            try:
                # check to see if this is a valid address
                socket.getaddrinfo(remoteAddr, dummyPort)
            except socket.gaierror:
                remoteAddr = dummyAddr
            
        s.connect((remoteAddr, dummyPort))
        addr = s.getsockname()[0]
    finally:
        # s.connect needs a network connection
        # if there is no network connection and you use the 
        # dummy address s.connect will throw a socket.error
        s.close()
   
    return addr

def convertLocalhostToIpAddr(name):
    """Take argument 'name' and if it somehow refers to the localhost convert that to the 
    machines external ip address.

    Args:
    name - machine address to filter

    Returns:
    If name does not refer to localhost this will return name
    If name does refer to localhost this will return the ip of the local machine
    """

    if name in [ None, '']:
        # defaut to localhost
        name = 'localhost'
    
    if name.lower()== 'localhost' or isLoopbackIPAddr(name):
        return getLocalIpAddr()
    else:
        return name


if __name__=="__main__":
    print getLocalIpAddr(None)

    print convertLocalhostToIpAddr(None)
