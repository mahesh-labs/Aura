import QtQuick
import QtQuick.Layouts
import "."

// A miniature screen: click or drag to choose where the floating blob appears.
ColumnLayout {
    id: bp
    property real fx: 1.0
    property real fy: 0.0
    property real aspect: 16 / 9
    signal picked(real fx, real fy)
    spacing: 8

    Item {
        Layout.fillWidth: true
        Layout.preferredHeight: 200

        Rectangle {
            id: scr
            anchors.centerIn: parent
            height: Math.min(parent.height, parent.width / bp.aspect)
            width: height * bp.aspect
            radius: 10
            border.color: Theme.border
            border.width: 2
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0; color: "#171b33" }
                GradientStop { position: 1; color: "#0d0f1d" }
            }
            // fake taskbar so it reads as a desktop
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 8; color: Qt.rgba(1, 1, 1, 0.06); radius: 3 }

            readonly property real bw: width * 0.15
            readonly property real bh: bw * 1.1

            function pick(mx, my) {
                var fx = Math.min(1, Math.max(0, (mx - bw / 2) / Math.max(1, width - bw)));
                var fy = Math.min(1, Math.max(0, (my - bh / 2) / Math.max(1, height - bh)));
                bp.picked(Math.round(fx * 100) / 100, Math.round(fy * 100) / 100);
            }

            Rectangle {
                id: marker
                width: scr.bw; height: scr.bh; radius: width / 2
                x: bp.fx * (scr.width - width)
                y: bp.fy * (scr.height - height)
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0; color: "#8ff0ff" }
                    GradientStop { position: 1; color: "#9a5bff" }
                }
                Behavior on x { enabled: !ma.pressed; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                Behavior on y { enabled: !ma.pressed; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                SequentialAnimation on opacity {
                    running: bp.visible
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.7; duration: 1100; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.0; duration: 1100; easing.type: Easing.InOutSine }
                }
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                cursorShape: Qt.CrossCursor
                onPressed: (m) => scr.pick(m.x, m.y)
                onPositionChanged: (m) => { if (pressed) scr.pick(m.x, m.y); }
            }
        }
    }

    Flow {
        Layout.fillWidth: true
        spacing: 8
        Chip { label: "Top left"; outline: true; onClicked: bp.picked(0, 0) }
        Chip { label: "Top right"; outline: true; onClicked: bp.picked(1, 0) }
        Chip { label: "Bottom left"; outline: true; onClicked: bp.picked(0, 1) }
        Chip { label: "Bottom right"; outline: true; onClicked: bp.picked(1, 1) }
        Chip { label: "Top centre"; outline: true; onClicked: bp.picked(0.5, 0) }
        Chip { label: "Centre"; outline: true; onClicked: bp.picked(0.5, 0.5) }
    }
}
