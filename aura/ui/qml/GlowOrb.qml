import QtQuick

// A soft round glow: a radial gradient painted ONCE (no per-frame repaint), then moved/faded by animations.
Canvas {
    id: orb
    property color color: "#8b7bff"
    property real strength: 0.30
    property int size: 520
    width: size; height: size
    onColorChanged: requestPaint()
    onStrengthChanged: requestPaint()
    onPaint: {
        var c = getContext("2d");
        c.reset();
        var r = width / 2;
        var g = c.createRadialGradient(r, r, 0, r, r, r);
        g.addColorStop(0, Qt.rgba(color.r, color.g, color.b, strength));
        g.addColorStop(0.45, Qt.rgba(color.r, color.g, color.b, strength * 0.35));
        g.addColorStop(1, Qt.rgba(color.r, color.g, color.b, 0));
        c.fillStyle = g;
        c.fillRect(0, 0, width, height);
    }
    Component.onCompleted: requestPaint()
}
