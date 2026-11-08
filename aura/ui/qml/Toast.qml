import QtQuick
import "."

Rectangle {
    id: box
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 18
    width: Math.min(parent.width - 40, lbl.implicitWidth + 32)
    height: lbl.implicitHeight + 20
    radius: 12
    color: Theme.surface2
    border.color: Theme.warn
    border.width: 1
    opacity: 0
    visible: opacity > 0
    z: 1000
    Behavior on opacity { NumberAnimation { duration: 200 } }
    Text {
        id: lbl
        anchors.centerIn: parent
        width: Math.min(implicitWidth, box.parent.width - 72)
        wrapMode: Text.Wrap
        color: Theme.text
        font.pixelSize: 13
    }
    Timer { id: t; interval: 5000; onTriggered: box.opacity = 0 }
    Connections {
        target: backend
        function onToast(msg) { lbl.text = msg; box.opacity = 1; t.restart(); }
    }
}
