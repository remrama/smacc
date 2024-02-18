"""
Custom widgets
"""

from PyQt5 import QtWidgets, QtGui, QtCore


try:
    from blinkstick import blinkstick
except:
    blinkstick = None


class VisualStimController(QtWidgets.QWidget):
    """
    A :class:`QtWidgets.QtWidget` with parameters/controllers for visual
    stimulation.

    Requires the python package ``blink-stick-python``
    https://github.com/arvydas/blinkstick-python

    """

    # switchToggled = QtCore.pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if blinkstick is None:
            raise ValueError("Use of visual stimulation requires `blinkstick` Python package.")

        self.stick = blinkstick.find_first()
        if self.stick is None:
            raise ValueError("No BlinkStick found")
        # else:
        #     assert stick.get_variant_string() == "BlinkStick Flex"

        # Create subwidgets needed for the display
        self.title_label = QtWidgets.QLabel("Title of VisualStimController", self)
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.freq_label = QtWidgets.QLabel("Frequency", self)
        self.freq_label.setAlignment(QtCore.Qt.AlignCenter)
        self.brightness_label = QtWidgets.QLabel("Brightness", self)
        self.brightness_label.setAlignment(QtCore.Qt.AlignCenter)
        self.flicker_checkbox = QtWidgets.QCheckBox("Flicker?")
        self.flicker_checkbox.setChecked(True)
        self.flicker_checkbox.animal = "Cat"

        # Create/compile layout with subwidgets
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.title_label)
        self.layout.addWidget(self.freq_label)
        self.layout.addWidget(self.brightness_label)
        self.setLayout(self.layout)
        # layout.addWidget(cbutton, 0, 0)


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
