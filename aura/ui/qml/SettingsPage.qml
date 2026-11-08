import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Every control here only *stages* a change. Nothing is applied until "Apply" is pressed (or "Revert" drops it).
Item {
    id: root

    property var monitorList: backend.monitors()
    readonly property bool dirty: backend.pendingCount > 0

    // ---- small building blocks -------------------------------------------------
    component Section: Text {
        Layout.topMargin: 24
        color: Theme.text
        font.pixelSize: 16
        font.weight: Font.DemiBold
        Rectangle {
            anchors.top: parent.bottom
            anchors.topMargin: 4
            width: 44; height: 2; radius: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Theme.accent }
                GradientStop { position: 1; color: Theme.accent2 }
            }
        }
    }
    component Hint: Text {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    component Label2: Text { color: Theme.text; font.pixelSize: 13 }

    component TextSetting: ColumnLayout {
        id: ts
        property string key
        property string label
        property string hint: ""
        property bool numeric: false
        function sync() { tf.text = String(backend.getStaged(ts.key)); }
        Layout.fillWidth: true
        spacing: 4
        Label2 { text: ts.label }
        TextField {
            id: tf
            Layout.fillWidth: true
            text: String(backend.getStaged(ts.key))
            color: Theme.text
            selectionColor: Theme.accent
            font.pixelSize: 13
            background: Rectangle { radius: 10; color: Theme.surface2; border.color: tf.activeFocus ? Theme.accent : Theme.border }
            onTextEdited: {
                if (ts.numeric) { if (text.trim() !== "" && !isNaN(Number(text))) backend.stageSetting(ts.key, Number(text)); }
                else backend.stageSetting(ts.key, text);
            }
        }
        Hint { text: ts.hint; visible: ts.hint !== "" }
        Connections { target: backend; function onSettingsReset() { ts.sync(); } }
    }

    component ComboSetting: ColumnLayout {
        id: cs
        property string key
        property string label
        property string hint: ""
        property var options: []
        property bool editable: false
        function sync() {
            var v = String(backend.getStaged(cs.key));
            var i = cs.options.indexOf(v);
            if (i >= 0) cb.currentIndex = i;
            else if (cs.editable) { cb.currentIndex = -1; cb.editText = v; }
            else cb.currentIndex = -1;
        }
        Layout.fillWidth: true
        spacing: 4
        Label2 { text: cs.label }
        ComboBox {
            id: cb
            Layout.fillWidth: true
            editable: cs.editable
            model: cs.options
            font.pixelSize: 13
            Component.onCompleted: cs.sync()
            onActivated: backend.stageSetting(cs.key, cs.editable ? editText : currentText)
            onAccepted: if (cs.editable) backend.stageSetting(cs.key, editText)
            onActiveFocusChanged: if (!activeFocus && cs.editable) backend.stageSetting(cs.key, editText)
        }
        Hint { text: cs.hint; visible: cs.hint !== "" }
        Connections { target: backend; function onSettingsReset() { cs.sync(); } }
    }

    component SwitchSetting: ColumnLayout {
        id: sw
        property string key
        property string label
        property string hint: ""
        Layout.fillWidth: true
        spacing: 2
        Switch {
            id: sws
            text: sw.label
            checked: Boolean(backend.getStaged(sw.key))
            onToggled: backend.stageSetting(sw.key, checked)
        }
        Hint { text: sw.hint; visible: sw.hint !== "" }
        Connections { target: backend; function onSettingsReset() { sws.checked = Boolean(backend.getStaged(sw.key)); } }
    }

    component VoiceSetting: ColumnLayout {
        id: vs
        property var voiceList: backend.ttsVoices()
        function sync() { vcb.currentIndex = vcb.indexOfValue(String(backend.getStaged("tts_voice"))); }
        Layout.fillWidth: true
        spacing: 4
        Label2 { text: "Voice (Kokoro)" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ComboBox {
                id: vcb
                Layout.fillWidth: true
                model: vs.voiceList
                textRole: "label"
                valueRole: "id"
                font.pixelSize: 13
                Component.onCompleted: vs.sync()
                onActivated: backend.stageSetting("tts_voice", currentValue)
            }
            Chip { label: "Preview"; outline: true; onClicked: backend.previewVoice(vcb.currentValue) }
        }
        Hint { text: "Pick a voice and press Preview (it plays right away). Apply keeps it." }
        Connections { target: backend; function onSettingsReset() { vs.sync(); } }
    }

    component SliderSetting: ColumnLayout {
        id: ss
        property string key
        property string label
        property real from: 0
        property real to: 1
        property real step: 0.05
        Layout.fillWidth: true
        spacing: 2
        Label2 { text: ss.label + ":  " + sl.value.toFixed(2) }
        Slider {
            id: sl
            Layout.fillWidth: true
            from: ss.from; to: ss.to; stepSize: ss.step
            value: Number(backend.getStaged(ss.key))
            onMoved: backend.stageSetting(ss.key, value)
        }
        Connections { target: backend; function onSettingsReset() { sl.value = Number(backend.getStaged(ss.key)); } }
    }

    // ---- the page -------------------------------------------------------------
    ScrollView {
        id: sv
        anchors.fill: parent
        anchors.bottomMargin: root.dirty ? applyBar.height + 12 : 0
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: sv.availableWidth - 8
            spacing: 12

            Text { text: "Settings"; color: Theme.text; font.pixelSize: 22; font.weight: Font.DemiBold }
            Hint { text: "Changes are held until you press Apply at the bottom. Revert drops them." }

            // ---- model
            Section { text: "Model (Ollama)" }
            TextSetting { key: "ollama_url"; label: "Ollama URL" }
            ComboSetting {
                key: "model"; label: "Model"; editable: true
                options: backend.availableModels()
                hint: "Pick an installed model or type a name. For quick voice replies a smaller model feels snappier."
            }
            TextSetting { key: "num_ctx"; label: "Context window (tokens)"; numeric: true; hint: "32768 recommended for agents. Larger uses more VRAM/RAM." }
            SliderSetting { key: "temperature"; label: "Temperature"; from: 0; to: 1.5 }
            TextSetting { key: "user_name"; label: "Your name (optional)" }
            TextSetting { key: "extra_instructions"; label: "Extra instructions for the assistant"; hint: "Added to the system prompt, e.g. “Prefer Firefox. Reply in short sentences.”" }

            // ---- voice
            Section { text: "Voice" }
            ComboSetting { key: "input_device"; label: "Microphone"; options: backend.audioDevices("input"); hint: "Empty = system default. If your headset keeps switching modes, pick a non-headset microphone here." }
            ComboSetting { key: "output_device"; label: "Speakers"; options: backend.audioDevices("output"); hint: "Empty = system default" }
            ComboSetting { key: "stt_model"; label: "Speech recognition model"; options: ["tiny.en", "base.en", "small.en", "medium.en", "large-v3-turbo"]; hint: "Bigger = more accurate, slower. Try medium.en if it mishears you." }
            ComboSetting { key: "stt_device"; label: "Recognition runs on"; options: ["cpu", "cuda", "auto"]; hint: "cpu keeps your GPU free for the LLM. cuda needs cuDNN installed." }
            ComboSetting { key: "tts_engine"; label: "Voice engine"; options: ["kokoro", "espeak"] }
            VoiceSetting { }
            SliderSetting { key: "tts_speed"; label: "Speaking speed"; from: 0.7; to: 1.4 }
            TextSetting { key: "followup_seconds"; label: "Keep listening after a reply (seconds)"; numeric: true; hint: "0 = answer once, then close the blob" }
            SwitchSetting { key: "barge_in"; label: "Interrupt by talking"; hint: "Start speaking while Aura is talking and it stops and listens. Works best with headphones; on speakers it may hear itself, then raise the level below." }
            TextSetting { key: "barge_in_level"; label: "Interrupt loudness"; numeric: true; hint: "0.06 default. Raise it if Aura interrupts itself, lower it if it ignores you." }
            TextSetting { key: "silence_ms"; label: "End-of-speech silence (ms)"; numeric: true }

            // ---- sounds
            Section { text: "Sounds" }
            SwitchSetting { key: "sounds_enabled"; label: "Play sounds"; hint: "Chimes when voice mode starts or stops, a ping when Aura needs your approval, and a warning or error tone when something fails." }
            SliderSetting { key: "sounds_volume"; label: "Sound volume"; from: 0; to: 1 }
            Flow {
                Layout.fillWidth: true
                spacing: 8
                Chip { label: "Start"; outline: true; onClicked: backend.playSound("start") }
                Chip { label: "Stop"; outline: true; onClicked: backend.playSound("stop") }
                Chip { label: "Approval"; outline: true; onClicked: backend.playSound("approval") }
                Chip { label: "Warning"; outline: true; onClicked: backend.playSound("warning") }
                Chip { label: "Error"; outline: true; onClicked: backend.playSound("error") }
            }
            Hint { text: "The test buttons use the applied volume (press Apply after changing it)." }

            // ---- screen
            Section { text: "Screen reading" }
            ComboSetting {
                key: "vision_model"; label: "Vision model (Ollama)"; editable: true
                options: backend.visionModels()
                hint: "Used only to look at the screen. Models that can read images are listed first; leave it blank to auto-detect. Needs a vision model, e.g. gemma3:12b."
            }
            ComboSetting {
                key: "screen_target"; label: "Monitor to look at"
                options: [""].concat(backend.monitors().map(function(m) { return m.name; }))
                hint: "Blank = whichever monitor the mouse is on when you ask. Pick one to always use that monitor."
            }
            TextSetting { key: "pointer_seconds"; label: "Highlight time (seconds)"; numeric: true }

            // ---- wake word
            Section { text: "Wake word" }
            SwitchSetting { key: "wake_enabled"; label: "Listen for the wake word"; hint: "Keeps the microphone open while idle (KDE shows the mic indicator). Everything stays on this computer." }
            TextSetting { key: "wake_phrases"; label: "Wake phrases (comma separated)"; hint: "Say e.g. “hey aura” or “hey aura, open Firefox”. Add spellings Whisper tends to hear, like “hey ora”." }

            // ---- meta key
            Section { text: "Meta key" }
            SwitchSetting { key: "meta_hold_enabled"; label: "Hold the Meta key to talk"; hint: "A quick tap still opens the KDE launcher. Holding it for the time below starts voice mode. Needs permission to read the keyboard: run  sudo usermod -aG input $USER  once, then log out and in." }
            Text { text: "Status: " + backend.metaStatus(); color: Theme.muted; font.pixelSize: 12 }

            // ---- overlay
            Section { text: "Floating blob" }
            Hint { text: "Choose the monitor, then click or drag in the mini screen to place the blob. Press Apply, then “Show blob for 3 s” to see it for real." }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label2 { text: "Monitor" }
                ComboBox {
                    id: monBox
                    Layout.fillWidth: true
                    font.pixelSize: 13
                    textRole: "label"
                    valueRole: "name"
                    function labels() {
                        var out = [{name: "", label: "The screen I'm using when it appears"}];
                        for (var i = 0; i < root.monitorList.length; i++) {
                            var m = root.monitorList[i];
                            out.push({name: m.name, label: m.name + "  (" + m.w + " × " + m.h + ")"});
                        }
                        return out;
                    }
                    model: labels()
                    function sync() {
                        var i = indexOfValue(String(backend.getStaged("blob_screen")));
                        currentIndex = i >= 0 ? i : 0;
                    }
                    Component.onCompleted: sync()
                    onActivated: backend.stageSetting("blob_screen", currentValue)
                    Connections { target: backend; function onSettingsReset() { monBox.sync(); } }
                }
            }
            BlobPicker {
                id: picker
                Layout.fillWidth: true
                fx: Number(backend.getStaged("blob_fx"))
                fy: Number(backend.getStaged("blob_fy"))
                aspect: {
                    var n = String(backend.getStaged("blob_screen"));
                    for (var i = 0; i < root.monitorList.length; i++)
                        if (root.monitorList[i].name === n) return root.monitorList[i].w / root.monitorList[i].h;
                    return root.monitorList.length > 0 ? root.monitorList[0].w / root.monitorList[0].h : 16 / 9;
                }
                onPicked: (x, y) => { backend.stageSetting("blob_fx", x); backend.stageSetting("blob_fy", y); }
                Connections {
                    target: backend
                    function onSettingsChanged() {
                        picker.fx = Number(backend.getStaged("blob_fx"));
                        picker.fy = Number(backend.getStaged("blob_fy"));
                    }
                }
            }
            TextSetting { key: "blob_margin"; label: "Margin from screen edge (px)"; numeric: true }
            SwitchSetting {
                key: "blob_clickable"; label: "Click the blob's message to expand it (experimental)"
                hint: "Off: the blob never takes mouse clicks. On: you can click the message pill to see the whole text. Restart Aura to apply."
            }
            Chip { label: "Show blob for 3 s"; outline: true; onClicked: backend.testBlob() }

            // ---- appearance
            Section { text: "Main window" }
            SwitchSetting {
                key: "custom_titlebar"; label: "Use Aura's own title bar"
                hint: "Replaces the KDE title bar with a built-in one. Try this if the window frame flickers. Takes effect after you restart Aura."
            }

            // ---- shortcuts
            Section { text: "Keyboard shortcuts" }
            Hint { text: "Global shortcuts are handled by KDE. Bind these commands in System Settings → Shortcuts → Add Command:" }
            Panel {
                Layout.fillWidth: true
                implicitHeight: cmds.implicitHeight + 20
                Column {
                    id: cmds
                    x: 14; y: 10; spacing: 4
                    Text { text: "aura voice        toggle voice mode (blob)"; color: Theme.accent2; font.family: Theme.mono; font.pixelSize: 12 }
                    Text { text: "aura chat         toggle quick chat box"; color: Theme.accent2; font.family: Theme.mono; font.pixelSize: 12 }
                    Text { text: "aura new-chat     start a fresh conversation"; color: Theme.accent2; font.family: Theme.mono; font.pixelSize: 12 }
                }
            }
            Chip { label: "Open KDE shortcut settings"; outline: true; onClicked: backend.openShortcutSettings() }

            // ---- tools
            Section { text: "What Aura is allowed to do" }
            Hint { text: "“Enabled” lets the model use a tool at all. “Ask first” makes Aura request your approval (button, or by voice) before each use." }
            Repeater {
                model: { backend.settingsRevision; return backend.toolList(); }
                delegate: Panel {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: trow.implicitHeight + 16
                    RowLayout {
                        id: trow
                        anchors.fill: parent
                        anchors.margins: 8
                        anchors.leftMargin: 14
                        spacing: 12
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text { text: modelData.name; color: Theme.text; font.pixelSize: 13; font.family: Theme.mono }
                            Text { Layout.fillWidth: true; text: modelData.description; color: Theme.muted; font.pixelSize: 11; elide: Text.ElideRight }
                        }
                        Switch { text: "Enabled"; checked: modelData.enabled; onToggled: backend.stageToolEnabled(modelData.name, checked) }
                        Switch { text: "Ask first"; checked: modelData.ask; onToggled: backend.stageToolAsk(modelData.name, checked) }
                    }
                }
            }

            Item { Layout.preferredHeight: 30 }
        }
    }

    // ---- Apply / Revert bar -------------------------------------------------------
    Panel {
        id: applyBar
        raised: true
        edge: Theme.accent
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 56
        visible: root.dirty
        z: 5
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 12
            spacing: 10
            Rectangle {
                width: 8; height: 8; radius: 4; color: Theme.warn
                SequentialAnimation on opacity {
                    running: applyBar.visible
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.3; duration: 800; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1; duration: 800; easing.type: Easing.InOutSine }
                }
            }
            Text {
                Layout.fillWidth: true
                text: backend.pendingCount + (backend.pendingCount === 1 ? " unapplied change" : " unapplied changes")
                color: Theme.text
                font.pixelSize: 13
            }
            Chip { label: "Revert"; outline: true; onClicked: backend.revertStaged() }
            Chip { label: "Apply"; onClicked: backend.applyStaged() }
        }
    }
}
