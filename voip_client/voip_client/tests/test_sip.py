import unittest
from voip_client.voip_client.sip import SipMessage, generate_digest_challenge_response, SipClient

class TestSipMessage(unittest.TestCase):
    def test_from_string(self):
        msg_str = "INVITE sip:alice@biloxi.com SIP/2.0\\r\\nVia: SIP/2.0/UDP client.example.com:5060;branch=z9hG4bK776asdhds\\r\\nMax-Forwards: 70\\r\\nTo: <sip:alice@biloxi.com>\\r\\nFrom: <sip:bob@chicago.com>;tag=1928301774\\r\\nCall-ID: a84b4c76e66710\\r\\nCSeq: 314159 INVITE\\r\\nContact: <sip:bob@chicago.com>\\r\\nContent-Type: application/sdp\\r\\nContent-Length: 142\\r\\n\\r\\nv=0\\r\\no=bob 2890844526 2890842807 IN IP4 192.0.2.1\\r\\ns=-\\r\\nc=IN IP4 192.0.2.1\\r\\nt=0 0\\r\\nm=audio 49170 RTP/AVP 0\\r\\na=rtpmap:0 PCMU/8000"
        message = SipMessage.from_string(msg_str)
        self.assertEqual(message.method, "INVITE")
        self.assertEqual(message.uri, "sip:alice@biloxi.com")
        self.assertEqual(message.headers["To"], "<sip:alice@biloxi.com>")
        self.assertEqual(message.headers["From"], "<sip:bob@chicago.com>;tag=1928301774")
        self.assertEqual(message.headers["Call-ID"], "a84b4c76e66710")
        self.assertEqual(message.headers["CSeq"], "314159 INVITE")
        self.assertEqual(message.body, "v=0\\r\\no=bob 2890844526 2890842807 IN IP4 192.0.2.1\\r\\ns=-\\r\\nc=IN IP4 192.0.2.1\\r\\nt=0 0\\r\\nm=audio 49170 RTP/AVP 0\\r\\na=rtpmap:0 PCMU/8000")

class TestDigestAuth(unittest.TestCase):
    def test_generate_digest_challenge_response(self):
        response = generate_digest_challenge_response("Mufasa", "Circle Of Life", "testrealm@host.com", "dcd98b7102dd2f0e8b11d0f600bfb0c093", "REGISTER", "sip:example.com")
        self.assertEqual(response, "6629fae49393a05397450978507c4ef1")

class TestSipClient(unittest.TestCase):
    def test_register_sends_via_header(self):
        class MockTransport:
            def __init__(self, local_ip, local_port):
                self.sent_messages = []
            def send(self, message, dest_address):
                self.sent_messages.append(message)
            def receive(self):
                return "", ("", 0)
            def close(self):
                pass

        client = SipClient(server="testserver", username="testuser", password="testpass", local_ip="192.168.1.181", local_port=5062)
        client.transport = MockTransport("192.168.1.181", 5062)
        client.register()
        self.assertEqual(len(client.transport.sent_messages), 1)
        message_str = client.transport.sent_messages[0]
        message = SipMessage.from_string(message_str)
        self.assertIn("Via", message.headers)
        self.assertEqual(message.headers["Via"], "SIP/2.0/UDP 192.168.1.181:5062;branch=z9hG4bK1")

if __name__ == "__main__":
    unittest.main()
