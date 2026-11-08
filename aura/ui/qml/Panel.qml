import QtQuick

// A rounded card with a soft vertical gradient and a hairline border.
Rectangle {
    id: p
    property bool raised: false
    property color edge: Theme.hairline
    radius: Theme.radius
    border.color: edge
    border.width: 1
    gradient: Gradient {
        orientation: Gradient.Vertical
        GradientStop { position: 0; color: p.raised ? Theme.panelHi : Theme.panel }
        GradientStop { position: 1; color: Qt.rgba(0.06, 0.07, 0.13, 0.80) }
    }
}
