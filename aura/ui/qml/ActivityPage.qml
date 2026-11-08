import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ColumnLayout {
    spacing: 12

    function kindColor(k) {
        return k === "voice" ? Theme.accent2 : k === "chat" ? Theme.accent : k === "tool" ? "#7cc4ff"
             : k === "approval" ? Theme.warn : k === "error" ? Theme.danger : Theme.muted;
    }

    RowLayout {
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text { text: "Activity"; color: Theme.text; font.pixelSize: 22; font.weight: Font.DemiBold }
            Text { text: "Everything Aura heard, said and did on this computer, newest first."; color: Theme.muted; font.pixelSize: 13 }
        }
        Chip { label: "Clear log"; outline: true; onClicked: backend.clearActions() }
    }

    Flow {
        Layout.fillWidth: true
        spacing: 8
        Repeater {
            model: [{k: "all", t: "All"}, {k: "voice", t: "Voice"}, {k: "chat", t: "Chat"},
                    {k: "tools", t: "Tools"}, {k: "approvals", t: "Approvals"}, {k: "errors", t: "Errors"}]
            delegate: Chip {
                required property var modelData
                label: modelData.t
                outline: true
                selected: backend.eventFilter === modelData.k
                onClicked: backend.setEventFilter(modelData.k)
            }
        }
    }

    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 8
        model: backend.events
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { }

        Text {
            anchors.centerIn: parent
            visible: backend.events.count === 0
            text: "Nothing here yet. Talk to Aura or ask it to do something."
            color: Theme.muted
        }

        delegate: Panel {
            id: card
            required property string when
            required property string kind
            required property string title
            required property string detail
            property bool open: false
            width: ListView.view.width
            height: dcol.implicitHeight + 20

            Rectangle {
                width: 3; radius: 1.5
                x: 0; y: 10; height: parent.height - 20
                color: kindColor(card.kind)
            }
            MouseArea { anchors.fill: parent; enabled: card.detail !== ""; onClicked: card.open = !card.open }

            Column {
                id: dcol
                x: 16; y: 10
                width: parent.width - 32
                spacing: 4
                Row {
                    spacing: 10
                    Text { text: card.when; color: Theme.muted; font.pixelSize: 12 }
                    Rectangle {
                        height: 18; width: kt.implicitWidth + 14; radius: 9
                        color: Qt.rgba(kindColor(card.kind).r, kindColor(card.kind).g, kindColor(card.kind).b, 0.18)
                        Text { id: kt; anchors.centerIn: parent; text: card.kind; font.pixelSize: 11; color: kindColor(card.kind) }
                    }
                    Text { text: card.title; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                }
                Text {
                    width: parent.width
                    visible: card.detail !== ""
                    text: card.detail
                    color: Theme.muted
                    font.pixelSize: 12
                    font.family: card.kind === "tool" ? Theme.mono : Theme.family
                    wrapMode: Text.Wrap
                    maximumLineCount: card.open ? 40 : 3
                    elide: Text.ElideRight
                }
            }
        }
    }
}
