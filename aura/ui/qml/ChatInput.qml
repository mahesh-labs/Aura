import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: root
    property alias field: area
    property string placeholder: "Message Aura…   (Enter to send, Shift+Enter for a new line)"
    signal submitted(string text)

    implicitHeight: col.implicitHeight

    function send() {
        var t = area.text.trim();
        if (t === "") return;
        area.text = "";
        backend.sendMessage(t);     // queued automatically if Aura is busy
        root.submitted(t);
    }

    ColumnLayout {
        id: col
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 6

        // messages typed while Aura was busy
        Repeater {
            model: backend.queued
            delegate: Rectangle {
                required property int index
                required property string modelData
                Layout.fillWidth: true
                implicitHeight: 30
                radius: 10
                color: Theme.surface
                border.color: Theme.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 4
                    spacing: 8
                    Text { text: "Queued"; color: Theme.warn; font.pixelSize: 11; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: modelData; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 12 }
                    IconButton { icon: "close"; flat: true; implicitWidth: 22; implicitHeight: 22; onClicked: backend.removeQueued(index) }
                }
            }
        }

        Panel {
            id: box
            Layout.fillWidth: true
            // height moves in whole-line steps (not pixel by pixel) so the layout stays calm while typing
            Layout.preferredHeight: 52 + Math.max(0, Math.min(area.lineCount, 6) - 1) * 21
            radius: 18
            raised: true
            edge: area.activeFocus ? Theme.accent : Theme.hairline

            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8

                Flickable {
                    id: fl
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: width
                    contentHeight: area.height
                    boundsBehavior: Flickable.StopAtBounds
                    TextArea.flickable: TextArea {
                        id: area
                        placeholderText: backend.busy ? "Aura is working… Enter adds your message to the queue" : root.placeholder
                        placeholderTextColor: Theme.muted
                        color: Theme.text
                        selectionColor: Theme.accent
                        selectedTextColor: "white"
                        wrapMode: TextArea.Wrap
                        font.pixelSize: 14
                        font.family: Theme.family
                        background: null
                        leftPadding: 6
                        verticalAlignment: TextArea.AlignVCenter
                        Keys.onPressed: (e) => {
                            if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) {
                                e.accepted = true;
                                root.send();
                            }
                        }
                    }
                    ScrollBar.vertical: ScrollBar { }
                }

                IconButton {
                    icon: "mic"
                    flat: true
                    tip: "Voice mode"
                    Layout.alignment: Qt.AlignBottom
                    tint: backend.voiceState !== "idle" ? Theme.accent : Theme.border
                    onClicked: backend.toggleVoice()
                }
                IconButton {
                    visible: backend.busy
                    icon: "stop"
                    tint: Theme.danger
                    tip: "Stop (also clears the queue)"
                    Layout.alignment: Qt.AlignBottom
                    onClicked: backend.stop()
                }
                IconButton {
                    icon: "send"
                    tint: Theme.accent
                    tip: backend.busy ? "Add to queue" : "Send"
                    Layout.alignment: Qt.AlignBottom
                    onClicked: root.send()
                }
            }
        }
    }
}
