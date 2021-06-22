import socket


def get_hostname_no_domain():
    """Get the host name of the calling machine.
    Will not return the domain name with the host name

    Args:
        None

    Returns:
        A string containing the host name of the calling machine
    """

    host_name = socket.gethostname().split('.')

    return host_name[0]


def is_valid_address(ip_str):
    """Validate a dotted decima notation IP/netmask string.

    Args:
        ip_str: A string, representing a quad-dotted ip

    Returns:
        A boolean, True if the string is a valid dotted decimal IP string
    """

    octets = str(ip_str).split('.')
    if len(octets) != 4:
        return False

    for octet in octets:
        try:
            if not 0 <= int(octet) <= 255:
                return False
        except ValueError:
            return False
        return True


def is_loopback_address(ip_str):
    """Take a dotted decimal notation IP string and validate if it's loopback
    or not.  Note that if you look at RFC3330 you'll find that the definition
    of loopback is 127.0.0.0/8 ( ie if the first octet is 127 it's loopback ).

    You can find the rfc here:
    http://www.rfc-editor.org/rfc/rfc3330.txt

    Args:
        ip_str: A string, representing a quad-dotted ip

    Returns:
        A boolean, True if the string is a valid quad-dotted decimal ip string
        and is loopback
    """

    if not is_valid_address(ip_str):
        return False

    octets = [int(num) for num in ip_str.split('.')]
    if octets[0] != 127:
        return False

    return True


def get_local_address(remote_addr=None):
    """
    This will return the ip address of the calling machine from the
    viewpoint of the machine given.

    Args:
      remote_addr - get the ip address of this machine from the
      viewpoint of 'remote_addr'

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
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        dummy_addr = "192.168.123.123"
        dummy_port = 56

        if remote_addr is None:
            remote_addr = dummy_addr
        else:
            try:
                # check to see if this is a valid address
                socket.getaddrinfo(remote_addr, dummy_port)
            except socket.gaierror:
                remote_addr = dummy_addr

        sock.connect((remote_addr, dummy_port))
        addr = sock.getsockname()[0]
    finally:
        # s.connect needs a network connection
        # if there is no network connection and you use the
        # dummy address s.connect will throw a socket.error
        sock.close()

    return addr


def convert_localhost_to_address(name):
    """Take argument 'name' and if it somehow refers to the localhost convert
    that to the machines external ip address.

    Args:
    name - machine address to filter

    Returns:
    If name does not refer to localhost this will return name
    If name does refer to localhost this will return the ip of the local
    machine
    """

    if name in [None, '']:
        # defaut to localhost
        name = 'localhost'

    if name.lower() == 'localhost' or is_loopback_address(name):
        return get_local_address()
    return name
