import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Shown while the agent waits for approval of a risky action.
Rectangle {
    id: bar
    visible: backend.confirmId !== ""
    function sendReply() {
        if (reply.text.trim() !== "") {
            backend.confirmReply(backend.confirmId, reply.text);
            reply.text = "";
        }
    }
    implicitHeight: visible ? col.implicitHeight + 24 : 0
    radius: 12
    border.color: Theme.warn
    border.width: 1
    gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: Qt.rgba(1, 0.74, 0.36, 0.16) }
        GradientStop { position: 1; color: Qt.rgba(1, 0.42, 0.62, 0.08) }
    }

    ColumnLayout {
        id: col
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8
        Text {
            text: "Aura wants to:"
            color: Theme.warn
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
        Text {
            Layout.fillWidth: true
            text: backend.confirmText
            color: Theme.text
            font.family: Theme.mono
            font.pixelSize: 13
            wrapMode: Text.WrapAnywhere
            maximumLineCount: 6
            elide: Text.ElideRight
        }
        RowLayout {
            spacing: 8
            Chip { label: "Allow"; tint: Theme.ok; onClicked: backend.confirmResponse(backend.confirmId, true) }
            Chip { label: "Deny"; outline: true; onClicked: backend.confirmResponse(backend.confirmId, false) }
            Text { text: "or say “yes” / “no” in voice mode"; color: Theme.muted; font.pixelSize: 12; visible: backend.voiceState !== "idle" }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            TextField {
                id: reply
                Layout.fillWidth: true
                placeholderText: "…or tell Aura what to change, e.g. “use ls -la instead”"
                placeholderTextColor: Theme.muted
                color: Theme.text
                selectionColor: Theme.accent
                font.pixelSize: 13
                background: Rectangle { radius: 8; color: Theme.surface2; border.color: reply.activeFocus ? Theme.accent : Theme.border }
                onAccepted: bar.sendReply()
            }
            Chip { label: "Send instructions"; outline: true; onClicked: bar.sendReply() }
        }
    }
}
