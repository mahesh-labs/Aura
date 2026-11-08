pragma Singleton
import QtQuick

QtObject {
    // base
    readonly property color bg: "#0a0b13"
    readonly property color bgTop: "#0c0e1a"
    readonly property color bgBottom: "#120f22"
    readonly property color surface: "#131628"
    readonly property color surface2: "#1b1f36"
    readonly property color border: "#2b3152"
    readonly property color borderSoft: "#1f2440"
    readonly property color text: "#eceef8"
    readonly property color muted: "#8e96b4"
    // brand gradient: violet -> cyan, with a pink accent for highlights
    readonly property color accent: "#8b7bff"
    readonly property color accent2: "#38d9c9"
    readonly property color accent3: "#ff6bd6"
    readonly property color danger: "#ff6b7a"
    readonly property color warn: "#ffbd5c"
    readonly property color ok: "#4ade80"
    readonly property string family: "Noto Sans"
    readonly property string mono: "monospace"
    readonly property int radius: 14
    // translucent panels (no blur; they let the slow background glow show through)
    readonly property color panel: Qt.rgba(0.075, 0.086, 0.157, 0.78)
    readonly property color panelHi: Qt.rgba(0.11, 0.125, 0.21, 0.82)
    readonly property color hairline: Qt.rgba(1, 1, 1, 0.07)
}
