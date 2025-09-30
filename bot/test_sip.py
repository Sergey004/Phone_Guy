#!/usr/bin/env python3
import sys
import time
import logging
import pjsua as pj
import wave

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)

# Глобальные переменные для хранения состояния
current_call = None
player_id = None
recorder_id = None


def on_call_state(call_id, e):
    """Callback когда меняется состояние звонка"""
    global current_call
    call_info = pj.call_get_info(call_id)
    logging.info(f"Call state: {call_info.state_text}")
    
    if call_info.state == pj.CallState.DISCONNECTED:
        logging.info("Call disconnected")
        current_call = None


def on_call_media_state(call_id, e):
    """Callback когда меняется медиа-состояние"""
    global player_id, recorder_id
    
    call_info = pj.call_get_info(call_id)
    logging.info(f"Media state changed for call {call_id}")
    
    if call_info.media_state == pj.MediaState.ACTIVE:
        logging.info("Media is active, setting up audio routing")
        
        # Получаем conference slot звонка
        call_slot = call_info.conf_slot
        logging.info(f"Call conference slot: {call_slot}")
        
        try:
            # ===== ВОСПРОИЗВЕДЕНИЕ (output.wav -> собеседник) =====
            try:
                player_id = pj.player_create("output.wav", loop=True)
                player_slot = pj.player_get_slot(player_id)
                logging.info(f"Player created with slot: {player_slot}")
                
                # Подключаем плеер к звонку
                pj.conf_connect(player_slot, call_slot)
                logging.info("Connected: player -> call")
            except pj.Error as e:
                logging.error(f"Failed to create/connect player: {e}")
            
            # ===== ЗАПИСЬ (собеседник -> captured_audio.wav) =====
            try:
                recorder_id = pj.recorder_create("captured_audio.wav")
                recorder_slot = pj.recorder_get_slot(recorder_id)
                logging.info(f"Recorder created with slot: {recorder_slot}")
                
                # Подключаем звонок к рекордеру
                pj.conf_connect(call_slot, recorder_slot)
                logging.info("Connected: call -> recorder")
            except pj.Error as e:
                logging.error(f"Failed to create/connect recorder: {e}")
            
            logging.info("Audio routing setup complete")
            
        except Exception as e:
            logging.error(f"Error in media setup: {e}")
            import traceback
            traceback.print_exc()


def on_incoming_call(acc_id, call_id, rdata):
    """Callback для входящих звонков"""
    global current_call
    
    call_info = pj.call_get_info(call_id)
    logging.info(f"Incoming call from {call_info.remote_info}")
    
    current_call = call_id
    
    # Автоматически отвечаем
    pj.call_answer(call_id, 200)


def main(domain, user, password):
    global player_id, recorder_id
    
    # Инициализация библиотеки
    lib = pj.Lib()
    
    try:
        # Создаем endpoint
        lib.init(log_cfg=pj.LogConfig(level=4, callback=None))
        
        # Создаем UDP транспорт
        transport = lib.create_transport(pj.TransportType.UDP, 
                                        pj.TransportConfig(5060))
        logging.info(f"SIP transport started on {transport.info().host}:{transport.info().port}")
        
        # Запускаем pjsua
        lib.start()
        logging.info("PJSUA started")
        
        # Создаем аккаунт
        acc_cfg = pj.AccountConfig(
            domain=domain,
            username=user,
            password=password
        )
        
        acc = lib.create_account(acc_cfg, set_default=True, cb=pj.AccountCallback(
            on_incoming_call=on_incoming_call
        ))
        
        logging.info(f"Account created: {acc.info().uri}")
        
        # Ждем регистрации
        time.sleep(2)
        acc_info = acc.info()
        if acc_info.reg_status == 200:
            logging.info(f"Registration successful: {acc_info.reg_status} {acc_info.reg_reason}")
        else:
            logging.warning(f"Registration status: {acc_info.reg_status} {acc_info.reg_reason}")
        
        # Основной цикл
        logging.info("Waiting for incoming calls... Press Ctrl+C to exit")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("\nShutting down...")
        
    except pj.Error as e:
        logging.error(f"PJSUA error: {e}")
    
    finally:
        # Cleanup
        if current_call:
            try:
                pj.call_hangup(current_call)
            except:
                pass
        
        if player_id:
            try:
                pj.player_destroy(player_id)
                logging.info("Player destroyed")
            except:
                pass
        
        if recorder_id:
            try:
                pj.recorder_destroy(recorder_id)
                logging.info("Recorder destroyed")
            except:
                pass
        
        lib.destroy()
        logging.info("PJSUA destroyed")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password>")
        sys.exit(1)
    
    domain, user, password = sys.argv[1:4]
    main(domain, user, password)