import QtQuick
import "."

// Gradient pill button (filled) or outlined button.
Rectangle {
    id: c
    property alias label: t.text
    property color tint: Theme.accent
    property color tint2: Qt.colorEqual(tint, Theme.accent) ? Theme.accent2 : Qt.darker(tint, 1.35)
    property bool outline: false
    property bool selected: false          // for filter chips: outlined look with a gradient edge/fill
    signal clicked()
    implicitWidth: t.implicitWidth + 28
    implicitHeight: 32
    radius: 16
    color: "transparent"
    border.color: outline ? (selected ? Theme.accent : (ma.containsMouse ? Theme.muted : Theme.border)) : "transparent"
    border.width: 1
    gradient: (!outline || selected) ? fill : null
    Gradient {
        id: fill
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: c.outline ? Qt.rgba(c.tint.r, c.tint.g, c.tint.b, 0.28) : (ma.containsMouse ? Qt.lighter(c.tint, 1.15) : c.tint) }
        GradientStop { position: 1; color: c.outline ? Qt.rgba(c.tint2.r, c.tint2.g, c.tint2.b, 0.28) : (ma.containsMouse ? Qt.lighter(c.tint2, 1.15) : c.tint2) }
    }
    Text { id: t; anchors.centerIn: parent; color: (c.outline && !c.selected) ? Theme.text : "white"; font.pixelSize: 13; font.weight: Font.Medium }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: c.clicked() }
}
