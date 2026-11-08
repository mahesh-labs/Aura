import QtQuick
import QtQuick.Window
import "."

// Floating voice indicator. Placed top-right by the KWin script (see kwin.py).
Window {
    id: win
    objectName: "blob"
    title: "Aura Blob"
    width: 300
    height: 520
    color: "transparent"
    // read once at start-up. Off by default: the whole window is click-through (safest).
    readonly property bool clickable: Boolean(backend.getSetting("blob_clickable"))
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
           | (clickable ? 0 : Qt.WindowTransparentForInput)
    visible: false

    readonly property string st: backend.voiceState
    readonly property bool wanted: st !== "idle" || backend.blobPreview

    onWantedChanged: {
        if (wanted) {
            hideTimer.stop();
            visible = true;
            stage.opacity = 1;
            stage.scale = 1;
        } else {
            stage.opacity = 0;
            stage.scale = 0.55;
            hideTimer.restart();
        }
    }
    Timer { id: hideTimer; interval: 450; onTriggered: if (!win.wanted) win.visible = false }

    function c1For(s) {
        return s === "listening" ? "#6ee7ff" : s === "thinking" ? "#c58bff" : s === "speaking" ? "#7dffb2"
             : s === "confirm" ? "#ffd37a" : s === "error" ? "#ff8a8a" : "#6ee7ff";
    }
    function c2For(s) {
        return s === "listening" ? "#4d62ff" : s === "thinking" ? "#ff5fd2" : s === "speaking" ? "#1fa8ff"
             : s === "confirm" ? "#ff8a4c" : s === "error" ? "#d63c5e" : "#4d62ff";
    }

    Item {
        id: stage
        anchors.fill: parent
        opacity: 0
        scale: 0.55
        transformOrigin: Item.Top
        Behavior on opacity { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 420; easing.type: Easing.OutBack } }

        Canvas {
            id: cv
            width: 260; height: 260
            anchors.horizontalCenter: parent.horizontalCenter
            y: 4

            property real t: 0
            property real lvl: 0            // smoothed audio level 0..1
            property color col1: win.c1For(win.st)
            property color col2: win.c2For(win.st)
            Behavior on col1 { ColorAnimation { duration: 450 } }
            Behavior on col2 { ColorAnimation { duration: 450 } }

            Timer {
                interval: 16
                repeat: true
                running: win.visible
                onTriggered: {
                    var st = win.st;
                    var target = (st === "listening" || st === "speaking" || st === "confirm") ? backend.audioLevel : 0;
                    var speed = st === "thinking" ? 2.6 : (st === "idle" ? 0.5 : 1.0 + cv.lvl * 2.0);
                    cv.lvl += (target - cv.lvl) * 0.22;
                    cv.t += 0.016 * speed;
                    cv.requestPaint();
                }
            }

            function blob(ctx, cx, cy, R, amp, seed) {
                var N = 96;
                ctx.beginPath();
                for (var i = 0; i <= N; i++) {
                    var a = i / N * 2 * Math.PI;
                    var r = R * (1 + amp * (0.55 * Math.sin(2 * a + t * 1.1 + seed)
                                           + 0.35 * Math.sin(3 * a - t * 1.5 + seed * 2.0)
                                           + 0.22 * Math.sin(5 * a + t * 2.2 + seed * 3.0)));
                    var x = cx + r * Math.cos(a), y = cy + r * Math.sin(a);
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                }
                ctx.closePath();
            }

            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                var cx = width / 2, cy = height / 2;
                var thinking = win.st === "thinking";
                var amp = thinking ? 0.10 + 0.03 * Math.sin(t * 3) : 0.07 + lvl * 0.34;
                var R = 62 + lvl * 16;
                var c1 = col1, c2 = col2;

                // soft halo
                for (var k = 3; k >= 1; k--) {
                    blob(ctx, cx, cy, R + k * 17, amp * 0.9, k * 0.9);
                    var g = ctx.createRadialGradient(cx, cy, R * 0.4, cx, cy, R + k * 20);
                    g.addColorStop(0, Qt.rgba(c2.r, c2.g, c2.b, 0.16 / k));
                    g.addColorStop(1, Qt.rgba(c2.r, c2.g, c2.b, 0));
                    ctx.fillStyle = g;
                    ctx.fill();
                }
                // body
                blob(ctx, cx, cy, R, amp, 0.0);
                var body = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R * 1.25);
                body.addColorStop(0, Qt.rgba(c1.r, c1.g, c1.b, 0.98));
                body.addColorStop(0.7, Qt.rgba(c2.r, c2.g, c2.b, 0.95));
                body.addColorStop(1, Qt.rgba(c2.r, c2.g, c2.b, 0.85));
                ctx.fillStyle = body;
                ctx.fill();
                // inner glassy highlight
                blob(ctx, cx - R * 0.12, cy - R * 0.2, R * 0.62, amp * 1.3, 2.1);
                var hi = ctx.createRadialGradient(cx - R * 0.25, cy - R * 0.35, 2, cx - R * 0.1, cy - R * 0.15, R * 0.7);
                hi.addColorStop(0, "rgba(255,255,255,0.55)");
                hi.addColorStop(1, "rgba(255,255,255,0)");
                ctx.fillStyle = hi;
                ctx.fill();
            }
        }

        // status pill + live conversation card, stacked under the blob
        Column {
            id: info
            width: parent.width
            anchors.top: cv.bottom
            anchors.topMargin: -10
            spacing: 8

            Rectangle {
                id: pill
                property bool expanded: false
                anchors.horizontalCenter: parent.horizontalCenter
                visible: backend.caption !== ""
                width: expanded ? info.width - 20 : Math.min(info.width - 20, probe.implicitWidth + 32)
                height: cap.implicitHeight + 18
                radius: 18
                clip: true
                border.color: pillMa.containsMouse ? Qt.rgba(1, 1, 1, 0.35) : Qt.rgba(1, 1, 1, 0.14)
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Qt.rgba(0.10, 0.09, 0.22, 0.94) }
                    GradientStop { position: 1; color: Qt.rgba(0.05, 0.12, 0.17, 0.94) }
                }
                Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                // single-line copy of the caption, only used to size the pill
                Text { id: probe; visible: false; text: cap.text; font.pixelSize: 13; font.family: Theme.family }
                Text {
                    id: cap
                    x: 16; y: 9
                    width: pill.width - 32
                    text: backend.caption.replace(/\s+/g, " ")
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    maximumLineCount: pill.expanded ? 200 : (win.clickable ? 3 : 6)
                    elide: Text.ElideRight
                    color: "white"
                    font.pixelSize: 13
                    font.family: Theme.family
                }
                Text {      // hint that there is more
                    visible: win.clickable && cap.truncated && !pill.expanded
                    anchors.right: parent.right; anchors.rightMargin: 10
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 3
                    text: "⌄"; color: Theme.accent2; font.pixelSize: 14
                }
                MouseArea {
                    id: pillMa
                    anchors.fill: parent
                    enabled: win.clickable
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: pill.expanded = !pill.expanded
                }
                Connections { target: backend; function onCaptionChanged() { pill.expanded = false; } }
            }

            Rectangle {
                id: card
                anchors.horizontalCenter: parent.horizontalCenter
                visible: backend.liveUser !== "" || backend.liveReply !== ""
                width: info.width - 20
                height: Math.min(180, liveCol.implicitHeight + 24)
                radius: 16
                clip: true
                border.color: Qt.rgba(1, 1, 1, 0.12)
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0; color: Qt.rgba(0.09, 0.10, 0.20, 0.94) }
                    GradientStop { position: 1; color: Qt.rgba(0.06, 0.07, 0.14, 0.94) }
                }
                Flickable {
                    id: fl
                    anchors.fill: parent
                    anchors.margins: 12
                    clip: true
                    contentWidth: width
                    contentHeight: liveCol.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    // follow the streaming reply
                    onContentHeightChanged: if (contentHeight > height) contentY = contentHeight - height
                    Column {
                        id: liveCol
                        width: fl.width
                        spacing: 6
                        Text {
                            visible: backend.liveUser !== ""
                            width: parent.width
                            text: "You: " + backend.liveUser
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: "#9fb0ff"
                            font.pixelSize: 12
                            font.italic: true
                            font.family: Theme.family
                        }
                        Text {
                            visible: backend.liveReply !== ""
                            width: parent.width
                            text: backend.liveReply
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: "white"
                            font.pixelSize: 13
                            font.family: Theme.family
                        }
                    }
                }
            }
        }
    }

    // Only the pill/card area receives clicks; the rest of this window lets clicks fall through to what is below.
    Item {
        id: maskItem
        x: info.x
        y: info.y
        width: info.width
        height: Math.max(1, info.height)
        function push() { if (win.clickable) backend.setBlobMask(Math.round(x), Math.round(y), Math.round(width), Math.round(height)); }
        onXChanged: push()
        onYChanged: push()
        onWidthChanged: push()
        onHeightChanged: push()
        Component.onCompleted: push()
    }
}
