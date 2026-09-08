import QtQuick 6.5

Item {
    id: root
    property var detections: []
    property real fovDegrees: 10
    property bool boxVisible: false
    property real boxLeft: 0
    property real boxTop: 0
    property real boxWidth: 0
    property real boxHeight: 0
    property string boxTeam: ""
    property real boxConfidence: 0
    property bool headVisible: false
    property real headLeft: 0
    property real headTop: 0
    property real headWidth: 0
    property real headHeight: 0
    property real headConfidence: 0

    Rectangle {
        x: (root.width - width) / 2
        y: (root.height - height) / 2
        width: Math.min(root.width, root.height) *
               Math.tan(root.fovDegrees * Math.PI / 180)
        height: width
        radius: width / 2
        color: "transparent"
        border.color: "#38bdf8"
        border.width: 2
        opacity: 0.7
    }

    Repeater {
        model: root.detections

        delegate: Rectangle {
            required property var modelData
            x: modelData.left
            y: modelData.top
            width: Math.max(0, modelData.right - modelData.left)
            height: Math.max(0, modelData.bottom - modelData.top)
            color: "transparent"
            border.color: modelData.class_name === "head" ? "#facc15" : "#8A2BE2"
            border.width: modelData.class_name === "head" ? 2 : 3

            Text {
                visible: parent.modelData.class_name !== "head"
                anchors.left: parent.left
                anchors.bottom: parent.top
                text: parent.modelData.class_name.toUpperCase() + " " +
                      Math.round(parent.modelData.confidence * 100) + "%"
                color: "#ffffff"
                font.bold: true
                font.pixelSize: 14
                style: Text.Outline
                styleColor: "#111827"
            }
        }
    }
}
