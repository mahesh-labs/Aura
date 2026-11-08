import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "."

// Our own title bar, used when "custom_titlebar" is on (frameless window). Drag to move, double-click to maximise.
Item {
    id: tb
    required property var host
    implicitHeight: 38

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(0.545, 0.482, 1, 0.14) }
            GradientStop { position: 1; color: Qt.rgba(0.22, 0.85, 0.79, 0.06) }
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.hairline }
    }
    DragHandler {
        target: null
        onActiveChanged: if (active) tb.host.startSystemMove()
    }
    TapHandler {
        onDoubleTapped: tb.host.visibility === Window.Maximized ? tb.host.showNormal() : tb.host.showMaximized()
    }
    Text {
        anchors.centerIn: parent
        text: "Aura"
        color: Theme.muted
        font.pixelSize: 12
        font.weight: Font.Medium
        font.letterSpacing: 1.5
    }
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        Repeater {
            model: [{g: "–", a: "min"}, {g: "▢", a: "max"}, {g: "✕", a: "close"}]
            delegate: Rectangle {
                required property var modelData
                width: 34; height: 26; radius: 8
                color: bma.containsMouse ? (modelData.a === "close" ? Theme.danger : Theme.surface2) : "transparent"
                Text { anchors.centerIn: parent; text: modelData.g; color: Theme.text; font.pixelSize: 13 }
                MouseArea {
                    id: bma
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        if (modelData.a === "min") tb.host.showMinimized();
                        else if (modelData.a === "max") tb.host.visibility === Window.Maximized ? tb.host.showNormal() : tb.host.showMaximized();
                        else tb.host.hide();
                    }
                }
            }
        }
    }
}
