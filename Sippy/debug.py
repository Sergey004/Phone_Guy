DEBUG = True
TRANSMIT_DELAY_REDUCTION = 0.0
REGISTER_FAILURE_THRESHOLD = 3

def debug(s, e=None):
    if DEBUG:
        print(s)
    elif e is not None:
        print(e)
