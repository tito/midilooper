
try:
    with open("/sys/firmware/devicetree/base/model", "r") as fd:
        model = fd.read()
except Exception:
    model = None

if "Raspberry Pi" in model:
    KEYBOARD_METHOD = "hidinput"
    RENDER_METHOD = "oled"
else:
    KEYBOARD_METHOD = "pynput"
    RENDER_METHOD = "tk"


# RENDER_METHOD = "none"
