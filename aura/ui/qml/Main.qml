import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "."

ApplicationWindow {
    id: win
    objectName: "main"
    title: "Aura"
    width: 1120
    height: 740
    minimumWidth: 780
    minimumHeight: 480
    visible: false
    color: Theme.bg

    property int page: 0        // 0 chat, 1 activity, 2 settings
    // read once at start-up; changing it in Settings takes effect after restarting Aura
    readonly property bool csd: Boolean(backend.getSetting("custom_titlebar"))
    flags: csd ? (Qt.Window | Qt.FramelessWindowHint) : Qt.Window

    palette {
        window: Theme.bg; windowText: Theme.text; base: Theme.surface2; alternateBase: Theme.surface
        text: Theme.text; button: Theme.surface2; buttonText: Theme.text; highlight: Theme.accent
        highlightedText: "white"; placeholderText: Theme.muted; mid: Theme.border; dark: Theme.border
        light: Theme.surface2; midlight: Theme.border; toolTipBase: Theme.surface2; toolTipText: Theme.text
    }

    background: AuraBackground { animate: win.visible && win.active }

    TitleBar { id: titleBar; host: win; visible: win.csd; height: visible ? implicitHeight : 0; anchors.left: parent.left; anchors.right: parent.right; z: 5 }
    ResizeEdges { host: win; visible: win.csd; z: 10 }

    RowLayout {
        anchors.fill: parent
        anchors.topMargin: titleBar.height
        spacing: 0

        // ------------------------------------------------------------ sidebar
        Rectangle {
            Layout.preferredWidth: 272
            Layout.fillHeight: true
            color: Qt.rgba(0.05, 0.055, 0.11, 0.55)
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.hairline }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                RowLayout {
                    spacing: 10
                    Rectangle {
                        id: logo
                        width: 28; height: 28; radius: 14
                        rotation: 0
                        gradient: Gradient {
                            orientation: Gradient.Vertical
                            GradientStop { position: 0; color: "#8ff0ff" }
                            GradientStop { position: 0.55; color: "#9a5bff" }
                            GradientStop { position: 1; color: "#ff6bd6" }
                        }
                        // slow endless spin: the gradient sweeps around the orb
                        NumberAnimation on rotation { from: 0; to: 360; duration: 9000; loops: Animation.Infinite; running: win.visible && win.active }
                    }
                    Text { text: "Aura"; color: Theme.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        id: dot
                        width: 9; height: 9; radius: 4.5
                        color: backend.voiceState !== "idle" ? Theme.accent2 : (backend.busy ? Theme.warn : Theme.ok)
                        SequentialAnimation on opacity {
                            running: (backend.busy || backend.voiceState !== "idle") && win.visible && win.active
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                            NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                            onStopped: dot.opacity = 1
                        }
                    }
                }

                Chip {
                    Layout.fillWidth: true
                    label: "+  New chat"
                    onClicked: { backend.newConversation(); win.page = 0; }
                }

                ListView {
                    id: convList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.topMargin: 6
                    clip: true
                    spacing: 2
                    model: backend.conversations
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    section.property: "pinned"
                    section.criteria: ViewSection.FullString
                    section.delegate: Text {
                        required property string section
                        width: ListView.view.width
                        height: 26
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 4
                        text: section === "true" ? "PINNED" : "CHATS"
                        color: Theme.muted
                        font.pixelSize: 11
                        font.letterSpacing: 1.2
                    }

                    delegate: Rectangle {
                        id: crow
                        required property int convId
                        required property string title
                        required property string when
                        required property bool pinned
                        property bool editing: false
                        width: ListView.view.width
                        height: 50
                        radius: 10
                        readonly property bool current: convId === backend.activeConv && win.page === 0
                        color: "transparent"
                        gradient: (current || hh.hovered) ? rowFill : null
                        Gradient {
                            id: rowFill
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: crow.current ? Qt.rgba(0.545, 0.482, 1, 0.30) : Qt.rgba(1, 1, 1, 0.06) }
                            GradientStop { position: 1; color: crow.current ? Qt.rgba(0.22, 0.85, 0.79, 0.10) : Qt.rgba(1, 1, 1, 0.02) }
                        }
                        Rectangle {
                            visible: crow.current
                            width: 3; height: 22; radius: 1.5; x: 0; anchors.verticalCenter: parent.verticalCenter
                            gradient: Gradient {
                                GradientStop { position: 0; color: Theme.accent }
                                GradientStop { position: 1; color: Theme.accent2 }
                            }
                        }
                        HoverHandler { id: hh }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: { backend.openConversation(crow.convId); win.page = 0; }
                            onDoubleClicked: { crow.editing = true; editor.forceActiveFocus(); editor.selectAll(); }
                        }
                        Column {
                            visible: !crow.editing
                            x: 12
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 24
                            spacing: 2
                            Row {
                                spacing: 6
                                Rectangle { visible: crow.pinned; width: 6; height: 6; radius: 3; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                                Text { width: crow.width - 36 - (crow.pinned ? 12 : 0); text: crow.title; color: Theme.text; font.pixelSize: 13; elide: Text.ElideRight }
                            }
                            Text { text: crow.when; color: Theme.muted; font.pixelSize: 11 }
                        }
                        TextField {
                            id: editor
                            visible: crow.editing
                            x: 8
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 16
                            text: crow.title
                            color: Theme.text
                            selectionColor: Theme.accent
                            font.pixelSize: 13
                            background: Rectangle { radius: 8; color: Theme.bg; border.color: Theme.accent }
                            onAccepted: { backend.renameConversation(crow.convId, text); crow.editing = false; }
                            onActiveFocusChanged: if (!activeFocus) crow.editing = false
                            Keys.onEscapePressed: crow.editing = false
                        }
                        Row {
                            visible: hh.hovered && !crow.editing
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 0
                            IconButton {
                                icon: "pin"; flat: true; implicitWidth: 28; implicitHeight: 28
                                flatGlyph: crow.pinned ? Theme.accent : Theme.muted
                                tip: crow.pinned ? "Unpin" : "Pin to top"
                                onClicked: backend.setPinned(crow.convId, !crow.pinned)
                            }
                            IconButton {
                                icon: "edit"; flat: true; implicitWidth: 28; implicitHeight: 28
                                tip: "Rename"
                                onClicked: { crow.editing = true; editor.forceActiveFocus(); editor.selectAll(); }
                            }
                            IconButton {
                                icon: "trash"; flat: true; implicitWidth: 28; implicitHeight: 28
                                tip: "Delete"
                                onClicked: backend.deleteConversation(crow.convId)
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: parent.count === 0
                        text: "No chats yet"
                        color: Theme.muted
                        font.pixelSize: 12
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.hairline }
                Chip {
                    Layout.fillWidth: true
                    outline: win.page !== 1
                    selected: win.page === 1
                    label: "Activity log"
                    onClicked: win.page = 1
                }
                Chip {
                    Layout.fillWidth: true
                    outline: win.page !== 2
                    selected: win.page === 2
                    label: "Settings"
                    onClicked: win.page = 2
                }
            }
        }

        // ------------------------------------------------------------ content
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: win.page

            // chat
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: backend.activeConv ? "Conversation" : "New conversation"
                            color: Theme.muted
                            font.pixelSize: 13
                        }
                        Chip {
                            label: backend.voiceState === "idle" ? "Start voice mode" : "Stop voice mode"
                            tint: backend.voiceState === "idle" ? Theme.accent : Theme.danger
                            onClicked: backend.toggleVoice()
                        }
                    }

                    // thin looping gradient sweep while Aura is working
                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 2
                        clip: true
                        Rectangle { anchors.fill: parent; color: Theme.hairline }
                        Rectangle {
                            id: sweep
                            visible: backend.busy
                            width: parent.width * 0.35; height: 2; radius: 1
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: "transparent" }
                                GradientStop { position: 0.5; color: Theme.accent }
                                GradientStop { position: 1; color: "transparent" }
                            }
                            NumberAnimation on x {
                                running: backend.busy && win.visible && win.active
                                from: -sweep.width; to: sweep.parent.width
                                duration: 1600; loops: Animation.Infinite
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        MessageList {
                            anchors.fill: parent
                        }
                        Column {
                            anchors.centerIn: parent
                            visible: backend.messages.count === 0
                            spacing: 10
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "How can I help?"; color: Theme.text; font.pixelSize: 26; font.weight: Font.DemiBold }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                horizontalAlignment: Text.AlignHCenter
                                text: "Type below, or use voice mode.\nTry: “open Firefox”, “turn the volume down”, “what's using my GPU?”"
                                color: Theme.muted
                                font.pixelSize: 14
                            }
                        }
                    }

                    ConfirmBar { Layout.fillWidth: true }
                    ChatInput { Layout.fillWidth: true; Layout.preferredHeight: implicitHeight }
                }
            }

            // activity
            Item {
                ActivityPage { anchors.fill: parent; anchors.margins: 22 }
            }

            // settings
            Item {
                SettingsPage { anchors.fill: parent; anchors.margins: 22 }
            }
        }
    }

    Toast { }
}
