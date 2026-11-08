import QtQuick
import QtQuick.Controls
import "."

ListView {
    id: list
    property bool compact: false
    readonly property real maxBubble: Math.max(220, width * (compact ? 0.94 : 0.74))

    clip: true
    spacing: compact ? 6 : 10
    model: backend.messages
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    onCountChanged: Qt.callLater(function () { list.positionViewAtEnd(); })
    onContentHeightChanged: if (atYEnd || backend.busy) Qt.callLater(function () { list.positionViewAtEnd(); })

    footer: Item {
        width: list.width
        height: backend.busy ? 34 : 4
        Row {
            visible: backend.busy
            x: 6; y: 10; spacing: 5
            Repeater {
                model: 3
                Rectangle {
                    width: 8; height: 8; radius: 4; color: Theme.accent2
                    SequentialAnimation on opacity {
                        running: backend.busy
                        loops: Animation.Infinite
                        PauseAnimation { duration: index * 160 }
                        NumberAnimation { from: 0.25; to: 1; duration: 350 }
                        NumberAnimation { from: 1; to: 0.25; duration: 350 }
                        PauseAnimation { duration: (2 - index) * 160 }
                    }
                }
            }
        }
    }

    delegate: Item {
        id: row
        required property int index
        required property string role
        required property string content
        required property string source
        required property string toolName
        required property string toolArgs
        required property string elapsed

        width: list.width
        height: ld.item ? ld.item.height : 0

        Loader {
            id: ld
            width: parent.width
            sourceComponent: row.role === "user" ? userC : (row.role === "tool" ? toolC : asstC)
        }

        Component {
            id: userC
            Item {
                height: bubble.height
                Rectangle {
                    id: bubble
                    anchors.right: parent.right
                    width: txt.width + 28
                    height: txt.height + 20
                    radius: 16
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: Theme.accent }
                        GradientStop { position: 1; color: "#5a73ff" }
                    }
                    Text {
                        id: txt
                        x: 14; y: 10
                        width: Math.min(implicitWidth, list.maxBubble - 28)
                        text: row.content
                        color: "white"
                        font.pixelSize: 14
                        font.family: Theme.family
                        wrapMode: Text.Wrap
                    }
                    Text {
                        visible: row.source === "voice"
                        text: "voice"
                        anchors.right: parent.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.muted
                        font.pixelSize: 10
                    }
                }
            }
        }

        Component {
            id: asstC
            Item {
                height: acol.height
                Column {
                  id: acol
                  spacing: 3
                  Rectangle {
                    id: abubble
                    width: atxt.width + 28
                    height: atxt.height + 20
                    radius: 16
                    border.color: Theme.hairline
                    gradient: Gradient {
                        orientation: Gradient.Vertical
                        GradientStop { position: 0; color: Theme.panelHi }
                        GradientStop { position: 1; color: Theme.panel }
                    }
                    TextEdit {
                        id: atxt
                        x: 14; y: 10
                        width: Math.min(implicitWidth, list.maxBubble - 28)
                        text: row.content
                        readOnly: true
                        selectByMouse: true
                        textFormat: TextEdit.MarkdownText
                        wrapMode: TextEdit.Wrap
                        color: Theme.text
                        selectionColor: Theme.accent
                        font.pixelSize: 14
                        font.family: Theme.family
                    }
                  }
                  Text {
                    visible: row.elapsed !== ""
                    text: "Took " + row.elapsed
                    leftPadding: 8
                    color: Theme.muted
                    font.pixelSize: 11
                  }
                }
            }
        }

        Component {
            id: toolC
            Item {
                height: tbox.height
                Rectangle {
                    id: tbox
                    width: Math.min(list.width, list.maxBubble + 60)
                    height: tcol.implicitHeight + 14
                    radius: 10
                    color: "transparent"
                    border.color: Theme.border
                    Column {
                        id: tcol
                        x: 12; y: 7
                        width: parent.width - 24
                        spacing: 2
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            color: Theme.accent2
                            font.pixelSize: 12
                            font.family: Theme.mono
                            text: "⚙ " + row.toolName + (row.toolArgs !== "" ? "  " + row.toolArgs : "")
                        }
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            maximumLineCount: row.content.length > 400 ? 3 : 2
                            wrapMode: Text.Wrap
                            color: Theme.muted
                            font.pixelSize: 12
                            text: row.content
                        }
                    }
                }
            }
        }
    }
}
