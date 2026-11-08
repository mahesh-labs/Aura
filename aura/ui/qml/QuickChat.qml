import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Spotlight-style chat box. Summoned with a global shortcut (`aura chat`).
ApplicationWindow {
    id: win
    objectName: "chat"
    title: "Aura Quick Chat"
    width: 700
    height: Math.min(600, col.implicitHeight + 36)
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    visible: false
    background: Item { }

    palette {
        window: Theme.bg; windowText: Theme.text; base: Theme.surface2; text: Theme.text
        button: Theme.surface2; buttonText: Theme.text; highlight: Theme.accent; highlightedText: "white"
        placeholderText: Theme.muted
    }

    onVisibleChanged: if (visible) focusTimer.restart()
    Timer { id: focusTimer; interval: 120; onTriggered: input.field.forceActiveFocus() }
    Shortcut { sequence: "Escape"; onActivated: win.hide() }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 8
        radius: 20
        border.color: Theme.border
        border.width: 1
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0; color: Theme.bgTop }
            GradientStop { position: 1; color: Theme.bgBottom }
        }
        // looping gradient sweep along the top edge while Aura is working
        Item {
            x: 20; y: 1; width: parent.width - 40; height: 2; clip: true
            visible: backend.busy
            Rectangle {
                id: qsweep
                width: parent.width * 0.4; height: 2; radius: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 0.5; color: Theme.accent2 }
                    GradientStop { position: 1; color: "transparent" }
                }
                NumberAnimation on x { running: backend.busy && win.visible; from: -qsweep.width; to: qsweep.parent.width; duration: 1500; loops: Animation.Infinite }
            }
        }

        ColumnLayout {
            id: col
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Rectangle {
                    width: 10; height: 10; radius: 5
                    gradient: Gradient {
                        orientation: Gradient.Vertical
                        GradientStop { position: 0; color: backend.busy ? Theme.accent2 : "#8ff0ff" }
                        GradientStop { position: 1; color: backend.busy ? Theme.accent : Theme.ok }
                    }
                }
                Text {
                    text: "Aura"
                    color: Theme.text
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: backend.busy ? (backend.caption !== "" ? backend.caption : "Working…") : "Esc to close"
                    color: Theme.muted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                IconButton { icon: "plus"; flat: true; implicitWidth: 28; implicitHeight: 28; tip: "New chat"; onClicked: backend.newConversation() }
                IconButton { icon: "expand"; flat: true; implicitWidth: 28; implicitHeight: 28; tip: "Open in app"; onClicked: { backend.showMain(); win.hide(); } }
                IconButton { icon: "close"; flat: true; implicitWidth: 28; implicitHeight: 28; tip: "Close"; onClicked: win.hide() }
            }

            MessageList {
                id: msgs
                compact: true
                visible: backend.messages.count > 0
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? Math.min(contentHeight + 40, 380) : 0
            }

            ConfirmBar { Layout.fillWidth: true }

            ChatInput {
                id: input
                Layout.fillWidth: true
                Layout.preferredHeight: implicitHeight
                placeholder: "Ask Aura or tell it what to do…"
            }
        }
    }
}
