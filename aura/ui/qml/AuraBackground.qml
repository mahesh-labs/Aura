import QtQuick

// Window background: deep vertical gradient + three slow drifting colour glows. Cheap: the glows are static
// textures that only translate; animations pause when `animate` is false (window hidden / unfocused).
Rectangle {
    id: bg
    property bool animate: true
    clip: true
    gradient: Gradient {
        orientation: Gradient.Vertical
        GradientStop { position: 0.0; color: Theme.bgTop }
        GradientStop { position: 1.0; color: Theme.bgBottom }
    }

    GlowOrb {
        id: o1
        color: Theme.accent; strength: 0.26; size: 640
        x: -200; y: -220
        SequentialAnimation on x {
            running: bg.animate; loops: Animation.Infinite
            NumberAnimation { to: bg.width * 0.35; duration: 26000; easing.type: Easing.InOutSine }
            NumberAnimation { to: -200; duration: 26000; easing.type: Easing.InOutSine }
        }
        SequentialAnimation on y {
            running: bg.animate; loops: Animation.Infinite
            NumberAnimation { to: -60; duration: 19000; easing.type: Easing.InOutSine }
            NumberAnimation { to: -220; duration: 19000; easing.type: Easing.InOutSine }
        }
    }
    GlowOrb {
        id: o2
        color: Theme.accent2; strength: 0.16; size: 560
        x: bg.width - 380; y: bg.height - 340
        SequentialAnimation on x {
            running: bg.animate; loops: Animation.Infinite
            NumberAnimation { to: bg.width - 560; duration: 31000; easing.type: Easing.InOutSine }
            NumberAnimation { to: bg.width - 300; duration: 31000; easing.type: Easing.InOutSine }
        }
        SequentialAnimation on opacity {
            running: bg.animate; loops: Animation.Infinite
            NumberAnimation { from: 1; to: 0.55; duration: 9000; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.55; to: 1; duration: 9000; easing.type: Easing.InOutSine }
        }
    }
    GlowOrb {
        id: o3
        color: Theme.accent3; strength: 0.10; size: 480
        x: bg.width * 0.5; y: bg.height * 0.3
        SequentialAnimation on y {
            running: bg.animate; loops: Animation.Infinite
            NumberAnimation { to: bg.height * 0.55; duration: 23000; easing.type: Easing.InOutSine }
            NumberAnimation { to: bg.height * 0.1; duration: 23000; easing.type: Easing.InOutSine }
        }
    }
}
