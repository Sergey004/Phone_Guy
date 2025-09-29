#!/usr/bin/env python3
import sys
import time
import logging
import pjsua2 as pj
from rtp_streamer import RtpStreamerMediaPort

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)


class MyAccount(pj.Account):
    def __init__(self):
        super().__init__()
        self.current_call = None

    def onRegState(self, prm):
        info = self.getInfo()
        logging.info(f"Account registration: {info.regIsActive} ({prm.code} {prm.reason})")

    def onIncomingCall(self, prm):
        call = MyCall(self, prm.callId)
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"Incoming call from {ci.remoteUri}")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        call.answer(prm)


class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID):
        super().__init__(acc, call_id)
        self.rtp_port = None

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}")
        if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")

    def onCallMediaState(self, prm):
        ci = self.getInfo()
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                logging.info("Audio active, attaching RTP streamer")
                am = self.getMedia(mi.index)
                aud_med = pj.AudioMedia.typecastFromMedia(am)

                # кастомный порт
                self.rtp_port = RtpStreamerMediaPort(clock_rate=8000)
                aud_med.startTransmit(self.rtp_port)
                self.rtp_port.startTransmit(aud_med)


class VoIPBot:
    def __init__(self, sip_domain, sip_user, sip_pass, local_ip="0.0.0.0"):
        self.ep = pj.Endpoint()
        self.ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.uaConfig.threadCnt = 1
        ep_cfg.logConfig.level = 5
        self.ep.libInit(ep_cfg)

        # Транспорт
        tcfg = pj.TransportConfig()
        tcfg.port = 5060
        tcfg.boundAddr = local_ip
        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

        self.ep.libStart()
        logging.info("PJSUA2 started")

        # Аккаунт
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{sip_user}@{sip_domain}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_domain}"
        cred = pj.AuthCredInfo("digest", "*", sip_user, 0, sip_pass)
        acc_cfg.sipConfig.authCreds.append(cred)

        self.account = MyAccount()
        self.account.create(acc_cfg)

    def make_call(self, uri):
        call = MyCall(self.account)
        prm = pj.CallOpParam(True)
        call.makeCall(uri, prm)
        self.account.current_call = call

    def destroy(self):
        if self.account and self.account.current_call and self.account.current_call.rtp_port:
            self.account.current_call.rtp_port.save_to_wav("captured_audio.wav")
        self.ep.libDestroy()
        logging.info("Destroyed")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        sys.exit(1)

    domain, user, passwd = sys.argv[1:4]
    bot = VoIPBot(domain, user, passwd)

    if len(sys.argv) > 4:
        target = sys.argv[4]
        bot.make_call(target)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bot.destroy()
