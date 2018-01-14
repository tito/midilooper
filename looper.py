#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Midi Looper
===========

UI:
    Display made for https://learn.adafruit.com/adafruit-pioled-128x32-mini-oled-for-raspberry-pi/
    Font are:
        https://fonts2u.com/fairfax.font
        https://fonts2u.com/fairfax-bold.font
"""

import io
import os
import json
import rtmidi
import threading
import traceback
from time import time, sleep
from rtmidi.midiconstants import (ALL_SOUND_OFF, CONTROL_CHANGE,
                                  RESET_ALL_CONTROLLERS, NOTE_ON,
                                  NOTE_OFF, SONG_START,
                                  SONG_CONTINUE, SONG_STOP)
from PIL import Image, ImageDraw, ImageFont
from config import KEYBOARD_METHOD, RENDER_METHOD

DPI = 1

if RENDER_METHOD == "tk":
    import tkinter as tk
    from PIL import ImageTk
    DPI = 5

elif RENDER_METHOD == "oled":
    import Adafruit_GPIO.SPI as SPI
    import Adafruit_SSD1306
    RST = 24
    DC = 23
    SPI_PORT = 0
    SPI_DEVICE = 0

if KEYBOARD_METHOD == "hidinput":
    from hidinput import Listener, Key, KeyCode
elif KEYBOARD_METHOD == "pynput":
    from pynput.keyboard import Listener, Key, KeyCode


global looper
Char = KeyCode.from_char
SIZE = (128, 32)
size = [x * DPI for x in SIZE]
image = None
LAG = 10 / 1000.


class Track(object):
    def __init__(self, index, midiout, looper):
        self.index = index
        self.notes = []
        self.notes_next = []
        self.recording = False
        self.muted = False
        self.on = []
        self.midiout = midiout
        self.looper = looper

    def quantize(self, clock, m):
        clock -= LAG
        diff = (clock % m)
        clock -= diff
        if diff > m / 2:
            clock += m
        return clock

    def midiin_callback(self, clock, m, data):
        print("track {}: {} {}".format(self.index, clock, m, data))
        if not self.recording:
            return
        status = m[0] & 0xF0
        if status in (NOTE_ON, NOTE_OFF):
            if looper.quantize > 0:
                clock_q = self.quantize(clock, 60 / looper.bpm / looper.quantize)
                print("quantize({}) -> {} to {}".format(looper.quantize, clock, clock_q))
                clock = clock_q
            else:
                clock -= LAG
            self.notes_next.append((clock, m, data))

    def reset(self):
        self.notes = []
        self.notes_next = []

    def start_recording(self):
        self.recording = True
        self.off()

    def stop_recording(self):
        self.recording = False
        self.merge()

    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self.off()

    def get_notes_between(self, start, end):
        if self.muted:
            return
        if start == 0:
            start = -1
        for clock, message, data in self.notes:
            if clock >= start and clock <= end:
                yield message

    def send_notes_between(self, start, end):
        send = self.midiout.send_message
        on = self.on
        for note in self.get_notes_between(start, end):
            m = note[0] & 0xF0
            s = (note[0] & 0x0F, note[1])
            if m == NOTE_ON:
                on.append(s)
            elif m == NOTE_OFF:
                if s in on:
                    on.remove(s)
            send(note)

    def off(self):
        for chn, note in self.on:
            self.midiout.send_message([NOTE_OFF | chn, note, 0])
        self.on = []

    def merge(self):
        self.notes += self.notes_next
        self.notes_next = []
        self.notes = list(sorted(self.notes, key=lambda x: x[0]))


class Player(threading.Thread):
    def __init__(self, looper, midiout):
        super(Player, self).__init__()
        self._is_playing = threading.Event()
        self._is_playing.clear()
        self.daemon = True
        self.quit = False
        self.looper = looper
        self.restart = False
        self.time_start = 0
        self.midiout = midiout
        self.start()

    @property
    def playing(self):
        return self._is_playing.is_set()

    def run(self):
        prev_deltatime = 0
        deltatime = 0
        play_notes = self.play_notes
        looper = self.looper
        tick = 0

        while not self.quit:

            if not self.playing:
                self._is_playing.wait()
                continue

            if self.restart:
                prev_deltatime = deltatime = tick = 0
                self.restart = False

            sleep(0.001)

            length = looper.length
            prev_deltatime = deltatime
            now = (time() - self.time_start)
            deltatime = now % length

            interval = looper.beat_length
            if now - tick > interval:
                self.tick()
                tick = now

            if deltatime > prev_deltatime:
                play_notes(looper, prev_deltatime, deltatime)
            else:
                play_notes(looper, prev_deltatime, length)
                self.merge_track_notes()
                play_notes(looper, 0, deltatime)

    def tick(self):
        if self.looper.with_tick:
            self.midiout.send_message([NOTE_OFF, 42, 50])
            self.midiout.send_message([NOTE_ON, 42, 50])

    def play_notes(self, looper, start, stop):
        for track in list(looper.tracks.values()):
            track.send_notes_between(start, stop)

    def merge_track_notes(self):
        for track in list(looper.tracks.values()):
            track.merge()

    def toggle_play(self):
        if self.playing:
            return self.stop()
        self.play()

    def play(self):
        if self.playing:
            return
        self.time_start = time()
        self.restart = True
        self._is_playing.set()
        self.midiout.send_message([SONG_START])
        self.tick()

    def stop(self):
        if not self.playing:
            return
        self._is_playing.clear()
        self.midiout.send_message([SONG_STOP])
        self.notes_off()

    def panic(self):
        send = self.looper.midiout.send_message
        self.stop()
        for channel in range(16):
            send([CONTROL_CHANGE, ALL_SOUND_OFF, 0])
            send([CONTROL_CHANGE, RESET_ALL_CONTROLLERS, 0])
            for note in range(128):
                send([NOTE_OFF|channel, note, 0])

    def notes_off(self):
        for track in list(looper.tracks.values()):
            track.off()

    @property
    def deltatime(self):
        return time() - self.time_start


class Looper(object):
    commands = {
        Char("r"): "reset",

        Char("q"): "stop_record",

        Char("z"): ("record", [1]),
        Char("x"): ("record", [2]),
        Char("c"): ("record", [3]),
        Char("v"): ("record", [4]),
        Char("b"): ("record", [5]),
        Char("n"): ("record", [6]),
        Char("m"): ("record", [7]),
        Char(","): ("record", [8]),

        Char("a"): ("mute", [1]),
        Char("s"): ("mute", [2]),
        Char("d"): ("mute", [3]),
        Char("f"): ("mute", [4]),
        Char("g"): ("mute", [5]),
        Char("h"): ("mute", [6]),
        Char("j"): ("mute", [7]),
        Char("k"): ("mute", [8]),

        Char("1"): ("toggle_channel", [1]),
        Char("2"): ("toggle_channel", [2]),
        Char("3"): ("toggle_channel", [3]),
        Char("4"): ("toggle_channel", [4]),
        Char("5"): ("toggle_channel", [5]),
        Char("6"): ("toggle_channel", [6]),
        Char("7"): ("toggle_channel", [7]),
        Char("8"): ("toggle_channel", [8]),

        Key.numpadadd: ("increment_measure", [1]),
        Key.numpadsubstract: ("increment_measure", [-1]),
        Key.page_up: ("increment_tempo", [10]),
        Key.page_down: ("increment_tempo", [-10]),
        Key.home: ("increment_tempo", [1]),
        Key.end: ("increment_tempo", [-1]),
        Key.insert: "decrease_quantize",
        Key.delete: "increase_quantize",

        Key.f1: "pattern_toggle",

        Key.f12: "save_settings",
        Key.f11: "load_settings",
        Key.f9: "toggle_tick",

        Key.space: "toggle_play",
        Key.esc: "panic",
        Key.caps_lock: "toggle_record_on_first_note",
        Key.numpaddivide: "midi_prev_port",
        Key.numpadmul: "midi_next_port",
        Key.numpad1: ("set_pattern_speed", [1]),
        Key.numpad2: ("set_pattern_speed", [2]),
        Key.numpad3: ("set_pattern_speed", [3]),
        Key.numpad4: ("set_pattern_speed", [4]),
    }

    QUANTIZE = (0, 1, 2, 3, 4, 8, 16)

    def __init__(self):
        self.tracks = {}
        self.shift = False
        self.ctrl = False
        self._key_pressed = []
        self.active_track = None
        self.record_on_first_note = True
        self.bpm = 120
        self.beat_per_measures = 4
        self.measures = 4
        self.port = 0
        self.quantize = 0
        self.channels = [True] * 8
        self.with_tick = False
        self.midiin = rtmidi.MidiIn()
        self.midiout = rtmidi.MidiOut()
        self.midiin_name = self.midiout_name = ""
        self.player = Player(self, self.midiout)
        self.require_length = True
        self.record_pattern = False
        self.pattern_speed = 1
        self.midi_clock = 0
        self.recalculate_length()
        self.open_midi_port()
        self.load_settings()

    def increase_quantize(self):
        index = self.QUANTIZE.index(self.quantize)
        index = min(len(self.QUANTIZE) - 1, (index + 1))
        self.quantize = self.QUANTIZE[index]

    def decrease_quantize(self):
        index = self.QUANTIZE.index(self.quantize)
        index = max(0, (index - 1))
        self.quantize = self.QUANTIZE[index]

    def stop_record(self):
        for track in self.tracks.values():
            track.stop_recording()
        self.active_track = None

    def toggle_channel(self, index):
        index -= 1
        self.channels[index] = not self.channels[index]

    def toggle_tick(self):
        self.with_tick = not self.with_tick

    @property
    def settings(self):
        return {
            "__version__": 1,
            "bpm": self.bpm,
            "measures": self.measures,
            "beat_per_measures": self.beat_per_measures,
            "port": self.port,
            "record_on_first_note": self.record_on_first_note,
            "quantize": self.quantize,
            "tracks": self.dump_tracks(),
            "channels": self.channels
        }

    def dump_tracks(self):
        tracks = []
        for track in self.tracks.values():
            tracks.append({
                "index": track.index,
                "notes": track.notes,
                "muted": track.muted
            })
        return tracks

    def save_settings(self):
        with io.open("settings.json", "w", encoding="utf-8") as fd:
            json.dump(self.settings, fd)
        print("Settings saved")

    def load_settings(self):
        try:
            with open("settings.json") as fd:
                settings = json.load(fd)
            if settings["__version__"] <= 1:
                self.bpm = settings["bpm"]
                self.beat_per_measures = settings["beat_per_measures"]
                self.measures = settings["measures"]
                self.record_on_first_note = settings["record_on_first_note"]
                self.port = settings["port"]
                self.quantize = settings["quantize"]
                self.channels = settings["channels"]
                self.recalculate_length()
                self.open_midi_port()

                self.tracks = {}
                for info in settings["tracks"]:
                    track = self.get_track(info["index"])
                    track.notes = info["notes"]
                    track.muted = info["muted"]

            print("Settings loaded")
        except:
            print("Error while loading settings")
            traceback.print_exc()

    def increment_tempo(self, amount):
        self.bpm = min(240, max(60, (self.bpm + amount)))
        self.recalculate_length()

    def increment_measure(self, amount):
        self.measures = min(24, max(1, self.measures + amount))
        self.recalculate_length()

    def recalculate_length(self):
        self.beat_length = 60 / float(self.bpm)
        self.measure_length = self.beat_length * self.beat_per_measures
        self.length = self.measure_length * self.measures
        print("BPM={} Measures={} Length={}s".format(self.bpm, self.beat_per_measures, self.length))

    def open_midi_port(self):
        if self.midiin.is_port_open():
            self.midiin.close_port()
        if self.midiout.is_port_open():
            self.midiout.close_port()
        self.midiin.open_port(self.port)
        self.midiout.open_port(self.port)
        self.midiin.set_callback(self.midiin_callback)
        self.midiin_name = self.midiin.get_port_name(self.port)
        self.midiout_name = self.midiout.get_port_name(self.port)
        self.player.midiout = self.midiout
        for track in self.tracks.values():
            track.midiout = self.midiout
        print("Connected: in={} out={}".format(self.midiin_name, self.midiout_name))

    def midi_next_port(self):
        self.port = (self.port + 1) % len(self.midiin.get_ports())
        self.open_midi_port()

    def midi_prev_port(self):
        self.port = (self.port - 1) % len(self.midiin.get_ports())
        self.open_midi_port()

    @property
    def measure(self):
        if not self.player.playing:
            return 1
        return 1 + int(self.player.deltatime / self.measure_length) % self.measures

    @property
    def beat(self):
        if not self.player.playing:
            return 0
        return 1 + int((self.player.deltatime / self.beat_length) % self.beat_per_measures)

    def reset(self):
        self.stop()
        self.tracks = {}
        if self.active_track:
            self.active_track.stop_recording()
            self.active_track = None
        self.require_length = True
        self.length = 999

    def panic(self):
        self.player.panic()

    def toggle_play(self):
        self.player.toggle_play()

    def play(self):
        if self.length is None:
            return
        self.player.play()

    def stop(self):
        self.player.stop()

    def toggle_record_on_first_note(self):
        self.record_on_first_note = not self.record_on_first_note

    def record(self, index):
        if self.ctrl:
            self.get_track(index).reset()
            return

        active_index = -1
        if self.active_track:
            active_index = self.active_track.index
            self.active_track.stop_recording()
            self.active_track = None
            if active_index == index:
                return
        self.active_track = track = self.get_track(index)
        if track.recording:
            print("stop recording")
            track.stop_recording()
        else:
            if not self.record_on_first_note:
                self.play()
                if self.require_length:
                    self.length_start = self.player.deltatime()
            print("start recording")
            track.start_recording()

    def mute(self, index):
        self.get_track(index).toggle_mute()

    def record_after(self, index):
        track = self.get_track(index)
        track.stop_recording()
        if self.require_length:
            self.length_stop = self.player.deltatime
            self.length = self.length_stop - self.length_start
            self.require_length = False
            print("-> Length is", self.length)
        self.active_track = None

    def set_pattern_speed(self, speed):
        self.pattern_speed = speed

    def pattern_toggle(self):
        if not self.record_pattern:
            self.record_pattern = True
            self.require_length = False
            self.record_on_first_note = False
            self.pattern = []
            self.pattern_channel = 0
            print("record pattern activated")
        else:
            self.record_pattern = False
            notes_per_measures = self.beat_per_measures * self.pattern_speed
            self.measures = len(self.pattern) // notes_per_measures
            track = self.get_track(0)
            note_length = self.beat_length / float(self.pattern_speed)
            print("note length={} beat length={} pattern speed={}".format(note_length, self.beat_length, self.pattern_speed))
            for index, item in enumerate(self.pattern):
                if not item:
                    continue
                note, velocity = item
                msg1 = [self.pattern_channel | NOTE_ON, note, velocity]
                msg2 = [self.pattern_channel | NOTE_ON, note, 0]
                clk1 = note_length * index
                clk2 = note_length * (index + 1)
                track.notes.append([clk1, msg1, None])
                track.notes.append([clk2, msg2, None])
            print("record pattern finished")
            print("-> pattern channel={}".format(self.pattern_channel))
            print("-> measures={}".format(self.measures))
            self.recalculate_length()

    def on_pattern_note(self, deltatime, message, data):
        cmd = message[0]
        status = cmd >> 4
        channel = cmd & 0b00001111
        print("{:b}".format(status), message)
        added = False
        if status == 0b1001 and message[2] != 0:
            note = message[1]
            self.pattern_channel = channel
            self.pattern.append((note, message[2]))
            added = True
        elif status == 0b1011 and channel == 0 and message[1] == 64 and message[2] == 127:
            self.pattern.append(None)
            self.added = True
        if added:
            print("pattern: {}".format([self.note_to_human(x) for x in self.pattern]))

    def note_to_human(self, note):
        octave = note // 12
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        return notes[note % 12] + str(octave)

    def print_midi_in(self, blob, data):
        message, deltatime = blob
        self.midi_clock += deltatime
        cmd = message[0]
        status = cmd >> 4
        channel = cmd & 0b00001111

        if status == 0b1101:
            print("MIDIIN: channel={} aftertouch={}".format(channel, message[1]))
        elif status == 0b1001:
            strnote = self.note_to_human(message[1])
            print("MIDIIN: channel={} note={} velocity={} midiclk={}".format(channel, strnote, message[2], self.midi_clock))
        elif status == 0b1011:
            print("MIDIIN: channel={} controller={} value={}".format(channel, message[1], message[2]))
        elif status == 0b1110:
            print("MIDIIN: channel={} pitchbend={} value={}".format(channel, message[1], message[2]))
        elif status == 0b1111:
            print("MIDIIN: system cmd={}".format(channel, message[1:]))
        else:
            print("MIDIIN: unknown cmd={:#08b} blob={}".format(cmd, blob, data))

    def midiin_callback(self, blob, data):
        self.print_midi_in(blob, data)
        # return
        message, deltatime = blob

        # control part
        if message[0] == SONG_START:
            return self.play()
        elif message[0] == SONG_STOP:
            return self.stop()

        if self.record_pattern:
            self.on_pattern_note(deltatime, message, data)
            return

        is_note = (message[0] & 0xF0 == NOTE_ON)
        if not is_note:
            # print("-> avoid, not a note")
            return

        channel = message[0] & 0x0F
        if not self.channels[channel]:
            # print("-> avoid, not an active channel")
            return
        if not self.active_track:
            # print("-> avoid, not active track")
            return

        if self.record_on_first_note:
            if not self.player.playing:
                self.player.play()
                if self.require_length:
                    self.length_start = self.player.deltatime
        deltatime = self.player.deltatime % self.length
        self.active_track.midiin_callback(deltatime, message, data)

    def get_track(self, index):
        if index not in self.tracks:
            self.tracks[index] = Track(index, self.midiout, self)
        return self.tracks[index]

    def dispatch_command(self, key, after=False):
        cmd, func, args = self.get_command(key, after)
        if not cmd:
            return
        print("Execute: {} {}".format(cmd, args))
        func(*args)

    def get_command(self, key, after=False):
        commands = self.commands
        cmd = commands.get(key)
        if not cmd:
            return None, None, None
        if isinstance(cmd, tuple):
            cmd, args = cmd
        else:
            args = []
        if after:
            cmd += "_after"
        if hasattr(self, cmd):
            func = getattr(self, cmd)
        else:
            cmd = func = args = None
        return cmd, func, args

    def on_key_pressed(self, key):
        if key == Key.shift:
            self.shift = True
        elif key == Key.ctrl:
            self.ctrl = True
        else:
            if key in self._key_pressed:
                return
            self._key_pressed.append(key)
            self.dispatch_command(key)

    def on_key_released(self, key):
        if key == Key.shift:
            self.shift = False
        elif key == Key.ctrl:
            self.ctrl = False
        elif key in self._key_pressed:
            self._key_pressed.remove(key)
            self.dispatch_command(key, after=True)


class UI(threading.Thread):
    def __init__(self):
        super(UI, self).__init__()
        width, height = size
        self.image = Image.new('1', (width, height))
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.truetype("fonts/Fairfax.ttf", size=10 * DPI)
        self.daemon = True
        self.cache = None
        self.start()

    def run(self):
        if RENDER_METHOD == "tk":
            self.root = tk.Tk()
            self.root.title("Midi Looper")
            self.root.geometry("{}x{}+0+0".format(*size))
            self.image1 = ImageTk.PhotoImage(self.image)
            self.panel = tk.Label(self.root, image=self.image1)
            self.panel.pack()
            self.root.after(1, self.render_and_display)
            self.root.mainloop()
            os._exit(0)
        elif RENDER_METHOD == "oled":
            self.disp = disp = Adafruit_SSD1306.SSD1306_128_32(rst=RST)
            print("Display size: {}x{}".format(disp.width, disp.height))
            disp.begin()
            disp.clear()
            disp.display()
            while True:
                self.render_and_display()
                sleep(0.5)


    def render_and_display(self):
        if self.render():
            self.display()
        if RENDER_METHOD == "tk":
            self.root.after(1, self.render_and_display)

    def render(self):
        # ▶■◼⚪⚫ (~25 chars width)
        width, height = size
        d = self.draw
        font = self.font
        player = looper.player

        def text(x, y, message):
            mx = 2
            d.text(((mx + x) * DPI, y * DPI), message, font=font, fill=255)

        state = "‣" if player.playing else "■"
        quantize = str(looper.quantize)
        channels = "".join([("+" if x else "-") for x in looper.channels])
        with_tick = "T" if looper.with_tick else " "
        top = u"{state} {bpm} {measure}-{measures} {quantize}{tick}{beat}{beatleft} {channels}".format(
            state=state,
            bpm=looper.bpm,
            measure=looper.measure,
            measures=looper.measures,
            beat="⚫" * looper.beat,
            beatleft="⚪" * (looper.beat_per_measures - looper.beat),
            port=looper.midiin_name,
            channels=channels,
            quantize=quantize,
            tick=with_tick
        )

        def render_status(index):
            status = ""
            if index in looper.tracks:
                track = looper.get_track(index)
                status += "⚫" if track.notes else "⚪"
                status += "R" if track.recording else " "
                status += "M" if track.muted else " "
                status += str(len(track.notes) + len(track.notes_next))
            else:
                status = "⚪"
            return status.ljust(8)

        line1 = "".join([render_status(i) for i in (1, 4, 7)])
        line2 = "".join([render_status(i) for i in (2, 5, 8)])
        line3 = "".join([render_status(i) for i in (3, 6, 9)])

        cache = [top, line1, line2, line3]
        if self.cache == cache:
            return False
        self.cache = cache

        d.rectangle((0, 0, width, height), outline=0, fill=0)
        text(0, 0, top)
        text(0, 8, line1)
        text(0, 16, line2)
        text(0, 24, line3)
        return True

    def display(self):
        if RENDER_METHOD == "tk":
            self.image1 = ImageTk.BitmapImage(self.image)
            self.panel.configure(image=self.image1)
            self.root.update()
        elif RENDER_METHOD == "oled":
            self.disp.image(self.image)
            self.disp.display()


def hide_keyboard():
    os.system("stty -echo")


def show_keyboard():
    os.system("stty echo")


try:
    hide_keyboard()

    looper = Looper()

    # ui = UI()

    with Listener(
            on_press=looper.on_key_pressed,
            on_release=looper.on_key_released) as listener:
        listener.join()

finally:
    show_keyboard()
