import QtQuick
import "."

Rectangle {
    property alias text: lbl.text
    z: 100
    x: (parent ? parent.width / 2 : 0) - width / 2
    y: parent ? parent.height + 6 : 0
    width: lbl.implicitWidth + 16
    height: lbl.implicitHeight + 8
    radius: 6
    color: Theme.surface2
    border.color: Theme.border
    Text { id: lbl; anchors.centerIn: parent; color: Theme.text; font.pixelSize: 12 }
}
