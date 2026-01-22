import socket, struct, time, threading, collections, audioop, random, logging

class PhoneGuyRTP(threading.Thread):
    def __init__(self, remote_addr, local_port):
        super().__init__(daemon=True)
        self.remote_addr = remote_addr  # Can be None for "RTP Latching" mode
        self.local_port = local_port
        self.tx_queue = collections.deque()
        self.rx_queue = collections.deque(maxlen=128)
        self.running = True
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', self.local_port))
        self.sock.setblocking(False)

        # RTP Params
        self.seq = random.randint(0, 1000)
        self.ts = random.randint(0, 1000)
        self.ssrc = 0x5E4C6079

    def add_tx_pcm(self, pcm_bytes):
        """Add PCM bytes to TX queue for sending to remote."""
        for i in range(0, len(pcm_bytes), 320):
            self.tx_queue.append(pcm_bytes[i:i+320])
    
    def get_next_rx_chunk(self, timeout=None):
        """Get next received audio chunk from RX queue."""
        if timeout is None:
            if self.rx_queue:
                return self.rx_queue.popleft()
            return None
        else:
            import time
            start = time.perf_counter()
            while time.perf_counter() - start < timeout:
                if self.rx_queue:
                    return self.rx_queue.popleft()
                time.sleep(0.01)
            return None

    def run(self):
        next_tick = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            if now < next_tick:
                time.sleep(max(0, next_tick - now))
                continue
            next_tick += 0.02

            # TX: Голос или Шум (только если remote_addr известен)
            if self.remote_addr is not None:
                chunk = self.tx_queue.popleft() if self.tx_queue else self._generate_hiss()
                if len(chunk) < 320: chunk = chunk.ljust(320, b'\x00')
                
                try:
                    payload = audioop.lin2alaw(chunk, 2)
                    header = struct.pack("!BBHII", 0x80, 0x08, self.seq, self.ts, self.ssrc)
                    self.sock.sendto(header + payload, self.remote_addr)
                except: pass

                self.seq = (self.seq + 1) & 0xFFFF
                self.ts = (self.ts + 160) & 0xFFFFFFFF

            # RX: Слушаем игрока
            try:
                while True:
                    data, addr = self.sock.recvfrom(2048)
                    # RTP Latching: Если remote_addr ещё не установлен, устанавливаем его
                    if self.remote_addr is None:
                        self.remote_addr = addr
                        logging.info(f"🔒 Locked remote RTP address: {addr}")
                    
                    if len(data) > 12:
                        self.rx_queue.append(audioop.alaw2lin(data[12:], 2))
            except BlockingIOError: pass

    def _generate_hiss(self):
        # Тот самый атмосферный шум Phone Guy
        return struct.pack('<160h', *[random.randint(-50, 50) for _ in range(160)])

    def stop(self):
        self.running = False
        self.sock.close()
