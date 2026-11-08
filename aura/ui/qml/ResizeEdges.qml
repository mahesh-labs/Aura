import QtQuick

// Invisible grips around a frameless host so it can still be resized.
Item {
    id: re
    required property var host
    anchors.fill: parent
    readonly property int g: 6
    component Grip: MouseArea {
        required property int edges
        hoverEnabled: true
        onPressed: re.host.startSystemResize(edges)
    }
    Grip { edges: Qt.LeftEdge;   x: 0; y: re.g; width: re.g; height: parent.height - 2 * re.g; cursorShape: Qt.SizeHorCursor }
    Grip { edges: Qt.RightEdge;  x: parent.width - re.g; y: re.g; width: re.g; height: parent.height - 2 * re.g; cursorShape: Qt.SizeHorCursor }
    Grip { edges: Qt.TopEdge;    x: re.g; y: 0; width: parent.width - 2 * re.g; height: re.g; cursorShape: Qt.SizeVerCursor }
    Grip { edges: Qt.BottomEdge; x: re.g; y: parent.height - re.g; width: parent.width - 2 * re.g; height: re.g; cursorShape: Qt.SizeVerCursor }
    Grip { edges: Qt.LeftEdge | Qt.TopEdge;     x: 0; y: 0; width: re.g * 2; height: re.g * 2; cursorShape: Qt.SizeFDiagCursor }
    Grip { edges: Qt.RightEdge | Qt.BottomEdge; x: parent.width - re.g * 2; y: parent.height - re.g * 2; width: re.g * 2; height: re.g * 2; cursorShape: Qt.SizeFDiagCursor }
    Grip { edges: Qt.RightEdge | Qt.TopEdge;    x: parent.width - re.g * 2; y: 0; width: re.g * 2; height: re.g * 2; cursorShape: Qt.SizeBDiagCursor }
    Grip { edges: Qt.LeftEdge | Qt.BottomEdge;  x: 0; y: parent.height - re.g * 2; width: re.g * 2; height: re.g * 2; cursorShape: Qt.SizeBDiagCursor }
}
