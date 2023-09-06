from PyQt5 import QtWidgets, QtGui, QtCore

class LightSwitchWidget(QtWidgets.QWidget):
    # Define a custom signal for when the switch is toggled
    switchToggled = QtCore.pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Layout and setup for the light switch
        self.layout = QtWidgets.QVBoxLayout(self)
        self.title_label = QtWidgets.QLabel("Light Switch", self)
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(self.title_label)
        self.onLabel = QtWidgets.QLabel("ON", self)
        self.offLabel = QtWidgets.QLabel("OFF", self)
        self.onLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.offLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.layout.addWidget(self.onLabel)
        self.layout.addWidget(self.offLabel)

        self.current_state = "ON"
        # Directly set the initial style for the "ON" state during initialization
        self.onLabel.setStyleSheet("""
            background-color: green;
            border: 2px solid black;
            border-style: inset;
            min-width: 50px;
            min-height: 50px;
        """)
        self.offLabel.setStyleSheet("""
            background-color: gray;
            border: 2px solid black;
            border-style: outset;
            min-width: 50px;
            min-height: 50px;
        """)

        self.onLabel.mousePressEvent = self.switch_on
        self.offLabel.mousePressEvent = self.switch_off
        # Connect the custom signal to the slot function
        # self.switchToggled.connect(self.print_switch_status)

    def switch_on(self, event):
        if self.current_state == "OFF":
            self.onLabel.setStyleSheet("""
                background-color: green;
                border: 2px solid black;
                border-style: inset;
                min-width: 50px;
                min-height: 50px;
            """)
            self.offLabel.setStyleSheet("""
                background-color: gray;
                border: 2px solid black;
                border-style: outset;
                min-width: 50px;
                min-height: 50px;
            """)
            self.current_state = "ON"
            self.switchToggled.emit()  # Emit the signal

    def switch_off(self, event):
        if self.current_state == "ON":
            self.onLabel.setStyleSheet("""
                background-color: gray;
                border: 2px solid black;
                border-style: outset;
                min-width: 50px;
                min-height: 50px;
            """)
            self.offLabel.setStyleSheet("""
                background-color: red;
                border: 2px solid black;
                border-style: inset;
                min-width: 50px;
                min-height: 50px;
            """)
            self.current_state = "OFF"
            self.switchToggled.emit()  # Emit the signal

    # Single slot function to check the status and print accordingly
    @QtCore.pyqtSlot()
    def print_switch_status(self):
        if self.current_state == "ON":
            print("The light was turned ON.")
        else:
            print("The light was turned OFF.")
