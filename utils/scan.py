#!/usr/bin/env python

from __future__ import print_function

"""This is a utility written specificaly with linux and the /proc file system
in mind.  Use the 'scan_pid' method to get a report on how many files a
particular process has open.  It will give details into the number of open
tcp/udp/unix sockets with local/remote host and state information.  It
will tell you specifically what files are open.


It was written with hope that if the icecube DAQ did start leaking
file descriptors, this would enable some useful debugging reports to
be generated.
"""

import sys
import glob
import os
import re
import struct
import socket


def fixed_ntoa(n):
    """python 2.6.2 on spts has a broken socket.inet_ntoa"""

    n = socket.ntohl(n)

    d = 256 * 256 * 256
    q = []
    while d > 0:
        m, n = divmod(n, d)
        q.append(str(m))
        d = d / 256
    return '.'.join(q)


def read_unix_proc(proc_unix_path="/proc/net/unix", debug=True):
    """This method was written specifically with linux and the /proc
    file system in mind.  The /proc/net/unix file contains information
    about all unix sockets open on the system.  One of the fields in
    each entry is an 'inode' which can be used to link information
    from a process to this specific unix socket.

    Num       RefCount Protocol Flags    Type St Inode Path

    Note that some of the state information referenced here was taken
    from the source code for the netstat utility.
    """
    proto_map = {0: "unix"}

    type_map = {1: "STREAM",
                2: "DGRAM",
                3: "RAW",
                4: "RDM",
                5: "SEQPACKET",
                }

    results = {}

    with open(proc_unix_path, 'r') as file_descriptor:
        for line in file_descriptor:

            match = re.search(("([\d+A-Fa-f]+)\:\s+([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\s+([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\s+([\dA-Fa-f]+)\s+"
                               "([\d]+)\s+([.+$]?)"), line)
            if match:
                proto_str = match.group(3)
                type_str = match.group(5)
                inode_str = match.group(7)
                file_str = match.group(8)

                proto_int = int(proto_str, 16)
                type_int = int(type_str, 16)
                inode = int(inode_str)

                proto_str = proto_map.get(proto_int, "UNKNOWN")
                type_str = type_map.get(type_int, "UNKNOWN")

                if debug:
                    print("UNIX:")
                    print("\t", inode, ", ", proto_str, ", ", \
                        type_str, ", ", file_str)
                results[inode] = (proto_str, type_str, file_str)
    return results


def read_tcp_proc(proc_tcp_path="/proc/net/tcp", debug=True):
    """This method was written specifically with linux and the /proc
    file system in mind.  The /proc/net/tcp file contains information
    about all tcp sockets open on the system.  One of the fields in
    each entry is an 'inode' which can be used to link information
    from a process to this specific tcp socket.

    sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt
    uid  timeout inode

    Note that some of the state information referenced here was taken
    from the source code for the netstat utility.
    """
    tcp_state_dict = {1: "ESTABLISHED",
                      2: "SYN_SENT",
                      3: "SYN_RECV",
                      4: "FIN_WAIT1",
                      5: "FIN_WAIT2",
                      6: "TIME_WAIT",
                      7: "CLOSE",
                      8: "CLOSE_WAIT",
                      9: "LAST_ACK",
                      10: "LISTEN",
                      11: "CLOSING"}

    results = {}

    with open(proc_tcp_path, 'r') as file_descriptor:
        for line in file_descriptor:
            match = re.search(("(\d+)\:\s+([\dA-Fa-f]+)\:"
                               "([\dA-Fa-f]+)\s+([\dA-Fa-f]+)\:"
                               "([\dA-Fa-f]+)\s+([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\:([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\:([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\s+([\d]+)\s+"
                               "([\d]+)\s+([\d]+)"), line)
            if match:
                local_addr = match.group(2)
                local_port = match.group(3)

                remote_addr = match.group(4)
                remote_port = match.group(5)

                state = match.group(6)
                state = int(state, 16)
                state = tcp_state_dict.get(state, "UNKNOWN")

                tx = int(match.group(7), 16)
                rx = int(match.group(8), 16)

                uid = int(match.group(12))
                inode = int(match.group(14))

                # from hex to a python integer
                local_addr = int(local_addr, 16)

                local_ip = fixed_ntoa(local_addr)

                # get the local port number ( hex to python int )
                local_port = int(local_port, 16)

                # from hex to a python integer
                remote_addr = int(remote_addr, 16)
                # from a python integer to a dotted quad
                remote_ip = fixed_ntoa(remote_addr)

                # get the remote port number ( hex to python int )
                remote_port = int(remote_port, 16)

                if debug:
                    print("TCP (", local_ip, ":", local_port, ") -> (", \
                        remote_ip, ":", remote_port, ") State: ", state)
                    print("tx: ", tx, " rx: ", rx, " uid: ", uid, \
                        " inode: ", inode)

                results[inode] = (local_ip, local_port, remote_ip,
                                  remote_port, state, rx, rx)

    return results


def read_udp_proc(proc_udp_path="/proc/net/udp", debug=True):
    """This method was written specifically with linux and the /proc
    file system in mind.  The /proc/net/udp file contains information
    about all udp sockets open on the system.  One of the fields in
    each entry is an 'inode' which can be used to link information
    from a process to this specific udp socket.

    The fields look like this:
    sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt
    uid  timeout inode ref pointer drops

    Note that some of the state information referenced here was taken
    from the source code for the netstat utility.
    """
    udp_state_dict = {1: "ESTABLISHED",
                      7: ""
                      }
    results = {}
    with open(proc_udp_path, 'r') as file_descriptor:
        for line in file_descriptor:

            match = re.search(("([\d]+)\:\s+([\dA-Fa-f]+)\:"
                               "([\dA-Fa-f]+)\s+([\dA-Fa-f]+)\:"
                               "([\dA-Fa-f]+)\s+([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\:([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\:([\dA-Fa-f]+)\s+"
                               "([\dA-Fa-f]+)\s+([\d]+)\s+"
                               "([\d]+)\s+([\d]+)"), line)

            if match:
                local_addr = match.group(2)
                local_port = match.group(3)

                remote_addr = match.group(4)
                remote_port = match.group(5)

                state = match.group(6)
                state = int(state, 16)
                state = udp_state_dict.get(state, "UNKNOWN")

                tx = int(match.group(7), 16)
                rx = int(match.group(8), 16)

                uid = int(match.group(12))
                inode = int(match.group(14))

                # from hex to a python integer
                local_addr = int(local_addr, 16)
                # from a python integer to a dotted quad
                local_ip = fixed_ntoa(local_addr)

                # get the local port number ( hex to python int )
                local_port = int(local_port, 16)

                # from hex to a python integer
                remote_addr = int(remote_addr, 16)
                # from a python integer to a dotted quad
                remote_ip = fixed_ntoa(remote_addr)

                # get the remote port number ( hex to python int )
                remote_port = int(remote_port, 16)

                if debug:
                    print("UDP (", local_ip, ":", local_port, ") -> (", \
                        remote_ip, ":", remote_port, ") State: ", state)
                    print("tx: ", tx, " rx: ", rx, " uid: ", uid, \
                        " inode: ", inode)

                results[inode] = (local_ip, local_port, remote_ip,
                                  remote_port, state, rx, rx)
    return results


def scan_pid(pid, debug_flag=False):
    """scan_pid is a tool written specifically for linux and the proc
    file system.  Given a pid this tool looks at the files in the
    /proc/<pid>/fd directory.  The files in this directory appear one
    for each file that <pid> has open.  Each of these files is
    symlinked to something useful.

    If the symlink points to something in the form of socket:[inode number]
    That inode number will be referenced in:
       /proc/net/udp
       /proc/net/tcp
       /proc/net/unix

    This will get you information about the state of the socket, the
    local and remote hosts etc

    If the symlink points to an actual valid path it's considered a file.

    There are other types though...  Like "pipes"
    """

    socket_re = re.compile("socket\:\[(\d+)\]")

    # build up the path
    fd_dir = os.path.join("/proc", "%d" % pid, "fd", "*")

    files = glob.glob(fd_dir)

    # number of open files
    num_open_files = len(files)
    num_sockets = 0
    num_files = 0
    num_other = 0

    # build up maps needed for sockets
    tcp_map = read_tcp_proc(debug=debug_flag)
    udp_map = read_udp_proc(debug=debug_flag)
    unix_map = read_unix_proc(debug=debug_flag)

    tcp_socket_map = {}
    udp_socket_map = {}
    unix_sockets = []
    open_files = []

    for file_name in files:
        link_name = os.readlink(file_name)

        sock_match = socket_re.match(link_name)
        if(sock_match):
            socket_inode = int(sock_match.group(1))
            num_sockets = num_sockets + 1

            if socket_inode in tcp_map:
                remote_host = tcp_map[socket_inode][2]
                if remote_host not in tcp_socket_map:
                    tcp_socket_map[remote_host] = []
                tcp_socket_map[remote_host].append(tcp_map[socket_inode])
            elif socket_inode in udp_map:
                remote_host = udp_map[socket_inode][2]
                if remote_host not in udp_socket_map:
                    udp_socket_map[remote_host] = []
                udp_socket_map[remote_host].append(udp_map[socket_inode])
            elif socket_inode in unix_map:
                unix_sockets.append(unix_map[socket_inode])
            else:
                print("Uknown socket %d" % socket_inode)
            continue

        # check to see if the link points to a valid file
        if os.path.exists(link_name):
            open_files.append(link_name)
            num_files = num_files + 1
            continue

        num_other = num_other + 1

    print("Report for pid %d" % pid)
    print("Number of open files: %d" % num_open_files)
    print("Number of sockets: %d" % num_sockets)
    print("Number of files: %d" % num_files)
    print("Number of other (pipes etc ): %d" % num_other)

    print_details(tcp_socket_map, udp_socket_map, unix_sockets, open_files)


def print_details(tcp_socket_map, udp_socket_map, unix_sockets, open_files):
    """Takes the details generated by the scan_pid method and generates a
    report to standard out."""

    # tcp sockets
    print("")
    print("TCP Socket Details:")
    print("-" * 60)
    for key in tcp_socket_map:
        if len(tcp_socket_map[key]) > 1:
            print("There are %d connections to %s" % \
                (len(tcp_socket_map[key]), key))

        for entry in tcp_socket_map[key]:
            print("Local %-15s:%6d\tRemote: %15s:%6d\tState: %s " \
                "(rx: %d, tx:%d)" % entry)

    # udp sockets
    print("")
    print("UDP Socket Details:")
    print("-" * 60)
    for key in udp_socket_map:
        if len(udp_socket_map[key]) > 1:
            print("There are %d connections to %s" % \
                (len(udp_socket_map[key]), key))
        for entry in udp_socket_map[key]:
            print("Local %-15s:%6d\tRemote: %15s:%6d\tState: %s " \
                "(rx: %d, tx: %d)" % entry)

    # unix sockets
    print("")
    print("Unix Socket Details:")
    print("-" * 60)
    for entry in unix_sockets:
        print("%-15s\t%15s\t%s" % entry)

    # files
    print("")
    print("Open Files:")
    print("-" * 60)
    for entry in open_files:
        print(entry)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("%s <pid of process to scan>" % sys.argv[0])
        sys.exit(-1)

    pid = int(sys.argv[1])
    scan_pid(pid)
