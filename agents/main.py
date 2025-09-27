import sys
import argparse
import time
import logging
import json

from pjsua2 import *
import pjsua2 as pj # type: ignore


class MyCall(Call):
    def __init__(self, acc, call_id=INVALID_ID):
        Call.__init__(self, acc, call_id)
        self.player = None
        self.recorder = None

    def onCallState(self, prm):
        ci = self.getInfo()
        print(">>> Call state:", ci.stateText, "last code:", ci.lastStatusCode)
        if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            print(">>> Call disconnected")
            if self.player:
                self.player = None
            if self.recorder:
                self.recorder = None

    def onCallMediaState(self, prm):
        ci = self.getInfo()
        
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                aud_med = AudioMedia.typecastFromMedia(self.getMedia(mi.index))

                # Проигрываем WAV в звонок
                self.player = MediaPlayer("output.wav")
                self.player.startTransmit(aud_med)
                print(">>> WAV file is being played into the call")

                # Записываем входящий звук
                self.recorder = MediaRecorder("input.wav")
                aud_med.startTransmit(self.recorder)
                print(">>> Call audio is being recorded to input.wav")


class MyAccount(Account):
    def __init__(self, cfg):
        Account.__init__(self)
        self.cfg = cfg

    def onRegState(self, prm):
        print(">>> Registration state:", prm.code)

    def onIncomingCall(self, prm):
        print(">>> Incoming call")
        call = MyCall(self, prm.callId)
        ans = CallOpParam()
        ans.statusCode = 200
        call.answer(ans)


class VoIPBot:
    def __init__(self, config_path="config.json"):
        logging.basicConfig(level=logging.DEBUG)
        self.logger = logging.getLogger("VoIPBot")

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        
        self.ep = Endpoint()
        self.ep.libCreate()

    def start(self, call_type="incoming", target=None):
        ep_cfg = EpConfig()
        self.ep.libInit(ep_cfg)
        self.ep.audDevManager().setNullDev()

        tcfg = TransportConfig()
        tcfg.port = self.config["sip"].get("sipPort", 5060)
        self.ep.transportCreate(PJSIP_TRANSPORT_UDP, tcfg)

        self.ep.libStart()
        self.logger.info(">>> PJSUA2 started")

        acc_cfg = AccountConfig()
        sip = self.config["sip"]
        acc_cfg.idUri = f"sip:{sip['username']}@{sip['domain']}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip['domain']}"
        cred = AuthCredInfo("digest", "*", sip["username"], 0, sip["password"])
        acc_cfg.sipConfig.authCreds.append(cred)

        self.acc = MyAccount(acc_cfg)
        self.acc.create(acc_cfg)

        time.sleep(3)  # ждём регистрацию

        if call_type == "outgoing":
            if not target:
                self.logger.error("Target URI required for outgoing calls")
                return
            call = MyCall(self.acc)
            prm = CallOpParam(True)
            call.makeCall(target, prm)
        else:
            self.logger.info("Waiting for incoming calls...")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        self.ep.libDestroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--call-type", choices=["incoming", "outgoing"], default="incoming")
    parser.add_argument("--target", help="Target SIP URI for outgoing calls")
    args = parser.parse_args()

    bot = VoIPBot(args.config)
    bot.start(args.call_type, args.target)
