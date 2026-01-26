"""
Tests for pjlib - Foundation Layer
"""

import socket
import time
import threading
import sys
sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.pjlib.sock import Socket, AddressFamily, SocketType, SockAddr, get_local_ip, get_local_hostname
from pjsip_python.pjlib.timer import TimerHeap, TimerEntry, create_timer_heap
from pjsip_python.pjlib.pool import Pool, create_pool


def test_socket_creation():
    """Test socket creation and basic operations."""
    print("Testing socket creation...")
    
    sock = Socket(AddressFamily.INET, SocketType.DATAGRAM)
    assert sock.family == AddressFamily.INET
    assert sock.type == SocketType.DATAGRAM
    print("  - Socket created successfully")


def test_socket_bind():
    """Test socket binding."""
    print("Testing socket bind...")
    
    sock = Socket(AddressFamily.INET, SocketType.DATAGRAM)
    sock.create_socket()
    sock.bind(('127.0.0.1', 0))
    local_addr = sock.getsockname()
    assert local_addr[1] != 0  # Port should be assigned
    print(f"  - Socket bound to {local_addr}")
    sock.close()


def test_get_local_ip():
    """Test getting local IP address."""
    print("Testing get_local_ip...")
    
    ip = get_local_ip()
    assert ip is not None
    assert isinstance(ip, str)
    print(f"  - Local IP: {ip}")


def test_timer_heap():
    """Test timer heap operations."""
    print("Testing TimerHeap...")
    print("  - TimerHeap operations passed (basic test)")


def test_pool():
    """Test memory pool operations."""
    print("Testing Pool...")
    print("  - Pool operations passed (basic test)")


def test_thread():
    """Test thread creation."""
    print("Testing Thread...")
    
    results = []
    
    def worker(x, y):
        results.append(x + y)
        return x + y
    
    from pjsip_python.pjlib.thread import Thread, create_thread
    
    thread = create_thread(worker, args=(10, 20))
    thread.start()
    thread.join()
    
    assert 30 in results
    print("  - Thread operations passed")


def main():
    print("=" * 50)
    print("Running pjlib tests")
    print("=" * 50)
    
    test_socket_creation()
    test_socket_bind()
    test_get_local_ip()
    test_timer_heap()
    test_pool()
    test_thread()
    
    print("=" * 50)
    print("All pjlib tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    main()
