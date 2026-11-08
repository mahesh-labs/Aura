import QtQuick
import QtQuick.Window
import "."

// Full-screen, click-through overlay: dims everything except a glowing rounded rectangle, then fades out.
Window {
    id: win
    objectName: "pointer"
    title: "Aura Pointer"
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
    visibility: Window.Hidden

    // target box in fractions of the screen
    property real fx1: 0.4
    property real fy1: 0.4
    property real fx2: 0.6
    property real fy2: 0.5
    property string label: ""
    property real hold: 3.0

    readonly property real pad: 10
    readonly property real bx: Math.max(0, fx1 * width - pad)
    readonly property real by: Math.max(0, fy1 * height - pad)
    readonly property real bw: Math.min(width - bx, (fx2 - fx1) * width + 2 * pad)
    readonly property real bh: Math.min(height - by, (fy2 - fy1) * height + 2 * pad)

    // Python sets the properties above, then bumps `request` to start the show
    property int request: 0
    onRequestChanged: present()

    function present() {
        visibility = Window.FullScreen;
        stage.opacity = 0;
        frame.scale = 1.18;
        anim.restart();
    }

    SequentialAnimation {
        id: anim
        ParallelAnimation {
            NumberAnimation { target: stage; property: "opacity"; to: 1; duration: 260; easing.type: Easing.OutCubic }
            NumberAnimation { target: frame; property: "scale"; to: 1; duration: 340; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: Math.max(500, win.hold * 1000) }
        ParallelAnimation {
            NumberAnimation { target: stage; property: "opacity"; to: 0; duration: 300; easing.type: Easing.InCubic }
            NumberAnimation { target: frame; property: "scale"; to: 1.12; duration: 300; easing.type: Easing.InCubic }
        }
        ScriptAction { script: { win.visibility = Window.Hidden; } }
    }

    Item {
        id: stage
        anchors.fill: parent
        opacity: 0

        // the dim: four slabs around the hole (cheap, no shaders)
        Rectangle { x: 0; y: 0; width: win.width; height: win.by; color: "#a6000000" }
        Rectangle { x: 0; y: win.by + win.bh; width: win.width; height: win.height - win.by - win.bh; color: "#a6000000" }
        Rectangle { x: 0; y: win.by; width: win.bx; height: win.bh; color: "#a6000000" }
        Rectangle { x: win.bx + win.bw; y: win.by; width: win.width - win.bx - win.bw; height: win.bh; color: "#a6000000" }

        Item {
            id: frame
            x: win.bx; y: win.by; width: win.bw; height: win.bh
            transformOrigin: Item.Center

            Canvas {
                id: cv
                anchors.fill: parent
                anchors.margins: -14
                property real phase: 0
                Timer { running: win.visibility !== Window.Hidden; interval: 33; repeat: true
                        onTriggered: { cv.phase = (cv.phase + 0.02) % 1.0; cv.requestPaint(); } }
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.reset();
                    var m = 14, r = 16, w = width - 2 * m, h = height - 2 * m;
                    function rr(inset) {
                        var x = m - inset, y = m - inset, ww = w + 2 * inset, hh = h + 2 * inset, rad = r + inset;
                        ctx.beginPath();
                        ctx.moveTo(x + rad, y);
                        ctx.arcTo(x + ww, y, x + ww, y + hh, rad);
                        ctx.arcTo(x + ww, y + hh, x, y + hh, rad);
                        ctx.arcTo(x, y + hh, x, y, rad);
                        ctx.arcTo(x, y, x + ww, y, rad);
                        ctx.closePath();
                    }
                    var a = phase * Math.PI * 2;
                    var g = ctx.createLinearGradient(width / 2 + Math.cos(a) * width / 2, height / 2 + Math.sin(a) * height / 2,
                                                     width / 2 - Math.cos(a) * width / 2, height / 2 - Math.sin(a) * height / 2);
                    g.addColorStop(0.0, "#6ee7ff"); g.addColorStop(0.5, "#c58bff"); g.addColorStop(1.0, "#ff5fd2");
                    // soft glow = a few wider, fainter strokes (no blur effect)
                    var widths = [14, 10, 6], alphas = [0.10, 0.18, 0.30];
                    for (var i = 0; i < widths.length; i++) {
                        ctx.globalAlpha = alphas[i]; ctx.lineWidth = widths[i]; ctx.strokeStyle = g; rr(0); ctx.stroke();
                    }
                    ctx.globalAlpha = 1; ctx.lineWidth = 3; ctx.strokeStyle = g; rr(0); ctx.stroke();
                }
            }

            Rectangle {
                visible: win.label !== ""
                anchors.horizontalCenter: parent.horizontalCenter
                y: (win.by + win.bh + 56 < win.height) ? parent.height + 22 : -height - 22
                width: lbl.implicitWidth + 28; height: 30; radius: 15
                color: "#e61a1d2b"; border.color: "#6ee7ff"; border.width: 1
                Text { id: lbl; anchors.centerIn: parent; text: win.label; color: "white"; font.pixelSize: 14 }
            }
        }
    }
}
