import QtQuick
import "."

// Round button with a drawn glyph (no icon fonts needed). icon: send | stop | mic | plus | close | trash | expand
Rectangle {
    id: b
    property string icon: "send"
    property color tint: Theme.accent
    property color glyph: "white"
    property bool flat: false
    property color flatGlyph: Theme.muted
    property string tip: ""
    signal clicked()

    onIconChanged: cv.requestPaint()
    implicitWidth: 36
    implicitHeight: 36
    radius: width / 2
    color: flat ? (ma.containsMouse ? Theme.surface2 : "transparent") : "transparent"
    property color tint2: Qt.colorEqual(tint, Theme.accent) ? Theme.accent2 : Qt.darker(tint, 1.35)
    gradient: flat ? null : fill
    Gradient {
        id: fill
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: ma.containsMouse ? Qt.lighter(b.tint, 1.18) : b.tint }
        GradientStop { position: 1; color: ma.containsMouse ? Qt.lighter(b.tint2, 1.18) : b.tint2 }
    }
    opacity: enabled ? 1 : 0.4

    Canvas {
        id: cv
        anchors.centerIn: parent
        width: 18; height: 18
        property color g: b.flat ? b.flatGlyph : b.glyph
        onGChanged: requestPaint()
        onPaint: {
            var c = getContext("2d");
            c.reset();
            c.strokeStyle = g; c.fillStyle = g; c.lineWidth = 2; c.lineCap = "round"; c.lineJoin = "round";
            var i = b.icon;
            if (i === "send") {
                c.beginPath(); c.moveTo(2, 9); c.lineTo(16, 2); c.lineTo(11, 16); c.lineTo(8.5, 10.5); c.closePath(); c.fill();
            } else if (i === "stop") {
                c.fillRect(4, 4, 10, 10);
            } else if (i === "mic") {
                c.beginPath(); c.roundedRect ? c.roundedRect(6, 1, 6, 10, 3, 3) : c.rect(6, 1, 6, 10); c.fill();
                c.beginPath(); c.arc(9, 9, 6, 0, Math.PI, false); c.stroke();
                c.beginPath(); c.moveTo(9, 15); c.lineTo(9, 17.5); c.stroke();
            } else if (i === "plus") {
                c.beginPath(); c.moveTo(9, 3); c.lineTo(9, 15); c.moveTo(3, 9); c.lineTo(15, 9); c.stroke();
            } else if (i === "close") {
                c.beginPath(); c.moveTo(4, 4); c.lineTo(14, 14); c.moveTo(14, 4); c.lineTo(4, 14); c.stroke();
            } else if (i === "trash") {
                c.beginPath(); c.moveTo(3, 5); c.lineTo(15, 5); c.moveTo(7, 5); c.lineTo(7, 3); c.lineTo(11, 3); c.lineTo(11, 5);
                c.moveTo(5, 5); c.lineTo(6, 16); c.lineTo(12, 16); c.lineTo(13, 5); c.stroke();
            } else if (i === "pin") {
                c.beginPath(); c.arc(9, 6, 3.6, 0, 2 * Math.PI); c.fill();
                c.beginPath(); c.moveTo(9, 9.5); c.lineTo(9, 16); c.stroke();
            } else if (i === "edit") {
                c.beginPath(); c.moveTo(3, 15); c.lineTo(4, 11); c.lineTo(12, 3); c.lineTo(15, 6); c.lineTo(7, 14); c.closePath(); c.stroke();
            } else if (i === "expand") {
                c.beginPath(); c.moveTo(3, 7); c.lineTo(3, 3); c.lineTo(7, 3); c.moveTo(15, 11); c.lineTo(15, 15); c.lineTo(11, 15);
                c.moveTo(3, 3); c.lineTo(8, 8); c.moveTo(15, 15); c.lineTo(10, 10); c.stroke();
            }
        }
        Component.onCompleted: requestPaint()
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: b.clicked()
    }
    ToolTipLabel { visible: ma.containsMouse && b.tip !== ""; text: b.tip }
}
