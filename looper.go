/**
Go by example: https://gobyexample.com
Atomic: https://golang.org/pkg/sync/atomic/#CompareAndSwapInt32
PortMidi: https://github.com/rakyll/portmidi/blob/master/portmidi.go
Keylogger: Keylogger: https://github.com/tito/keylogger/blob/master/model.go

**/

package main
import (
    "log"
    "time"
    "strings"
    "sync/atomic"
    "github.com/rakyll/portmidi"
    "github.com/ScaleFT/monotime"
    "github.com/tito/keylogger"
)

const KEY_ESC = 1
const KEY_1 = 2
const KEY_2 = 3
const KEY_3 = 4
const KEY_4 = 5
const KEY_5 = 6
const KEY_6 = 7
const KEY_7 = 8
const KEY_8 = 9
const KEY_9 = 10
const KEY_0 = 11
const KEY_MINUS = 12
const KEY_EQUAL = 13
const KEY_BS = 14
const KEY_TAB = 15
const KEY_Q = 16
const KEY_W = 17
const KEY_E = 18
const KEY_R = 19
const KEY_T = 20
const KEY_Y = 21
const KEY_U = 22
const KEY_I = 23
const KEY_O = 24
const KEY_P = 25
const KEY_BRACKETOPEN = 26
const KEY_BRACKETCLOSE = 27
const KEY_ENTER = 28
const KEY_L_CTRL = 29
const KEY_A = 30
const KEY_S = 31
const KEY_D = 32
const KEY_F = 33
const KEY_G = 34
const KEY_H = 35
const KEY_J = 36
const KEY_K = 37
const KEY_L = 38
const KEY_SEMICOLON = 39
const KEY_QUOTE = 40
const KEY_BACKQUOTE = 41
const KEY_L_SHIFT = 42
const KEY_BACKSLASH = 43
const KEY_Z = 44
const KEY_X = 45
const KEY_C = 46
const KEY_V = 47
const KEY_B = 48
const KEY_N = 49
const KEY_M = 50
const KEY_COLON = 51
const KEY_DOT = 52
const KEY_SLASH = 53
const KEY_R_SHIFT = 54
const KEY_MUL = 55
const KEY_L_ALT = 56
const KEY_SPACE = 57
const KEY_CAPS_LOCK = 58
const KEY_F1 = 59
const KEY_F2 = 60
const KEY_F3 = 61
const KEY_F4 = 62
const KEY_F5 = 63
const KEY_F6 = 64
const KEY_F7 = 65
const KEY_F8 = 66
const KEY_F9 = 67
const KEY_F10 = 68
const KEY_NUM_LOCK = 69
const KEY_SCROLL_LOCK = 70
const KEY_HOME = 71
const KEY_UP_8 = 72
const KEY_PGUP_9 = 73
const KEY_NUMPADMINUS = 74
const KEY_LEFT_4 = 75
const KEY_NUMPAD5 = 76
const KEY_RT_ARROW_6 = 77
const KEY_NUMPADPLUS = 78
const KEY_END_1 = 79
const KEY_DOWN = 80
const KEY_PGDN_3 = 81
const KEY_INS = 82
const KEY_DEL = 83
// const KEY_ = 84
// const KEY_ = 85
// const KEY_ = 86
const KEY_F11 = 87
const KEY_F12 = 88
// const KEY_ = 89
// const KEY_ = 90
// const KEY_ = 91
// const KEY_ = 92
// const KEY_ = 93
// const KEY_ = 94
// const KEY_ = 95
const KEY_R_ENTER = 96
const KEY_R_CTRL = 97
// const KEY_SLASH = 98
const KEY_PRT_SCR = 99
const KEY_R_ALT = 100
// const KEY_ = 101
// const KEY_HOME = 102
const KEY_UP = 103
const KEY_PGUP = 104
const KEY_LEFT = 105
const KEY_RIGHT = 106
const KEY_END = 107
// const KEY_DOWN = 108
const KEY_PGDN = 109
const KEY_INSERT = 110
// const KEY_DEL = 111
// const KEY_ = 112
// const KEY_ = 113
// const KEY_ = 114
// const KEY_ = 115
// const KEY_ = 116
// const KEY_ = 117
// const KEY_ = 118
const KEY_PAUSE = 119


type Looper struct {
    Length uint64
    BeatLength uint64
    Restart int32
    Keyboard chan keylogger.InputEvent
    MidiIn chan portmidi.Event
    MidiOut chan portmidi.Event
    PatternMode bool
    Tracks map[int]*Track
}


func (looper *Looper) MidiInRoutine() {
    // search for something else than Through
    var device portmidi.DeviceID = -1
    var info *portmidi.DeviceInfo
    for i := 0; i < portmidi.CountDevices(); i++ {
        info = portmidi.Info(portmidi.DeviceID(i))
        if info.IsInputAvailable == false {
            continue
        }
        if strings.Contains(info.Name, "Through") {
            continue
        }
        device = portmidi.DeviceID(i)
        break
    }

    if device == -1 {
        log.Fatal("No midi device connected")
        return
    }

    log.Println("MIDI In:", info.Name)
    in, err := portmidi.NewInputStream(device, 1024)
    if err != nil {
        log.Fatal(err)
    }
    defer in.Close()

    ch := in.Listen()
    for {
        ev := <- ch
        if ev.Status == 248 {
            continue
        }
        looper.MidiIn <- ev
    }
}


func (looper *Looper) MidiOutRoutine() {
    var device portmidi.DeviceID = -1
    var info *portmidi.DeviceInfo
    for i := 0; i < portmidi.CountDevices(); i++ {
        info = portmidi.Info(portmidi.DeviceID(i))
        if info.IsOutputAvailable == false {
            continue
        }
        if strings.Contains(info.Name, "Through") {
            continue
        }
        device = portmidi.DeviceID(i)
        break
    }

    if device == -1 {
        log.Fatal("No midi device connected")
        return
    }

    log.Println("MIDI Out:", info.Name)
    out, err := portmidi.NewOutputStream(device, 1024, 10)
    if err != nil {
        log.Fatal(err)
    }

    for {
        ev := <- looper.MidiOut
        out.WriteShort(ev.Status, ev.Data1, ev.Data2)
    }
}


func (looper *Looper) StartPattern() {
    log.Println("Start pattern mode")
    looper.PatternMode = true
}


func (looper *Looper) EndPattern() {
    log.Println("End pattern mode")
    looper.PatternMode = false
}


func (looper *Looper) PatternMidiIn(ev portmidi.Event) {
    log.Println("Pattern mode:", ev)
    track := looper.GetTrack(0)

    status := GetStatus(ev)
    channel := GetChannel(ev)

    if status == NOTE_ON && ev.Data2 != 0 {
        // standard note on
        track.AddNote(0, 1, 60, 127)
        track.AddNote(0, 1, 60, 0)
    } else if status == CONTROL_CHANGE && channel == 0 && ev.Data1 == 64 && ev.Data2 == 127 {
        // sustain, used to add nothing
    }
}


func (looper *Looper) GetTrack(index int) (*Track) {
    track, ok := looper.Tracks[index]
    if !ok {
        track = NewTrack()
        looper.Tracks[index] = track
    }
    return track
}


func (looper *Looper) ProcessKeyboardEvent(ev keylogger.InputEvent) {
    log.Println("Keyboard:", ev.Code, ev.Value)
    switch ev.Code {
        case KEY_F1:
            if ev.Value == 1 {
                looper.StartPattern()
            } else {
                looper.EndPattern()
            }
        default:
            log.Println("Keyboard not handled", ev.Code)
    }
}


func (looper *Looper) ProcessMidiInEvent(ev portmidi.Event) {
    log.Println("MidiEvent", ev, looper.PatternMode)
    if looper.PatternMode == true {
        looper.PatternMidiIn(ev)
        return
    }
}


func (looper *Looper) PlayerRoutine() {
    prev_deltatime := 0
    deltatime := 0
    var tick uint64 = 0

    for {
        if atomic.CompareAndSwapInt32(&looper.Restart, 1, 0) {
            prev_deltatime = 0
            deltatime = 0
            tick = 0
        }

        length := atomic.LoadUint64(&looper.Length)
        prev_deltatime = deltatime
        now := monotime.Now()

        interval := atomic.LoadUint64(&looper.BeatLength)
        if now - tick > interval {
            tick = now
        }

        _ = length

        if deltatime > prev_deltatime {
            // log.Println("Play notes (delta)", prev_deltatime, deltatime)
        } else {
            // log.Println("Play notes (delta end)", prev_deltatime, length)
            // log.Println("Merges")
            // log.Println("Play notes (delta start)", 0, deltatime)
        }

        // depending of the perf, move that to separate goroutine
        select {
            case mev := <- looper.MidiIn:
                looper.ProcessMidiInEvent(mev)
            case kev := <- looper.Keyboard:
                looper.ProcessKeyboardEvent(kev)
            default:
        }
    }
}


func (looper *Looper) KeyboardRoutine() {
    devs, err := keylogger.NewDevices()
    if err != nil {
	    log.Println(err)
	    return
    }
    rd := keylogger.NewKeyLogger(devs[0])
    in, err := rd.Read()
    if err != nil {
	    log.Println(err)
	    return
    }

    for i := range in {
	    if i.Type == keylogger.EV_KEY {
            if i.Value == 2 {
                // avoid repeatition
                continue
            }
            // log.Println(i.Type, i.Code, i. , i.KeyString())
            looper.Keyboard <- i
	    }
    }
}


func main() {
    log.Println("Midi Looper")
    log.Println("by Mathieu Virbel <mat@meltingrocks.com>")

    var looper Looper
    looper.Keyboard = make(chan keylogger.InputEvent)
    looper.MidiIn = make(chan portmidi.Event)
    looper.MidiOut = make(chan portmidi.Event)
    looper.Tracks = make(map[int]*Track)

    portmidi.Initialize()
    go looper.MidiInRoutine()
    go looper.MidiOutRoutine()
    go looper.PlayerRoutine()
    go looper.KeyboardRoutine()

    for {
        time.Sleep(1)
    }
}
