# Use USB GPIO to switch FX on and off
# Bits 0 to 4 are LED outputs
# Bits 5 to 7 are momentary pushbutton inputs
# On init, try to open serial port

# state:
# 0: Send output mask
# 1: Send outputs
# 2: Send request for inputs
# 3: Wait (might not be needed)
# 4: Receive inputs and process

# Outputs:
# 0 = Compressor on level 1 (Reaper channel 10 FX 2)
# 1 = Compressor on level 2 (Reaper channel 10 FX 3)
# 2 = Mid and centre boost (Reaper channel 10 FX 4 & 5)
# 3 = Signal > -50.0dB
# 4 = Comp exceeded by 12dB


# Inputs:
# 5 = Compressor level 1 PB
# 6 = Compressor level 2 PB
# 7 = Mid and centre boost PB

import serial
import math

TrackFXindex = 9 # Zero bazsed track index (9 = track 10)
Comp1FXindex = 1 # Zero bazsed compressoer indexes
Comp2FXindex = 2
EQFXindex = 3 # Zero bazsed EQ indexe
WidthFXindex = 4 # Zero bazsed stereo width index

threshold = 0.0
redThreshold = 20.0
rms = 0.0

yellThreshold = -50.0
yellOnDelay = 3 # 5 cycles at approx 10Hz = 0.3 sec
yellOffDelay = 600  # 1200 cycles at approx 10Hz = 60 sec
yellOnCount = 0
yellOffCount = 0
yellLED = False

state = 0
maskSent = False
outputs = [False, False, False, False, False]
output_command = ""
inputs = [False, False, False]
inputsMem = [False, False, False]
toggle = [False, False, False]
errorTxt = ""
outputStr = ""
inputStr = ""

timeout = 0.01
port_name = "COM3"  # Replace with your actual COM port
baud_rate = 19200
ser = None

def openPort():
    try:
        global ser
        ser = serial.Serial(
            port=port_name,
            baudrate=baud_rate,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=timeout)
    except:
        pass

openPort()

def serLoop():
    global ser
    global state
    global maskSent
    global outputs
    global output_command
    global inputs
    global inputsMem
    global errorTxt
    global outputStr
    global inputStr
    global toggle
    global threshold
    global redThreshold
    global yellThreshold
    global rms
    global yellOnDelay
    global yellOffDelay
    global yellOnCount
    global yellOffCount
    global yellLED
    
    # Is serial defined?
    serDefined = True
    try:
        ser
        ser.isOpen
    except:
        serDefined = False

    if serDefined and ser and ser.isOpen:
        match state:
            case 0:
                # Send output mask
                try:
                    output_mask_command = f"gpio iomask 1F\r"
                    ser.write(output_mask_command.encode())
                    output_dir_command = f"gpio iodir E0\r"
                    ser.write(output_dir_command.encode())
                    maskSent = True
                except:
                    errorTxt = "Failed to send mask"
            case 1:
                # Get track
                selectedTrack = RPR_GetTrack(0, TrackFXindex)
                # Get state of FX. Note: tracks and FX are zero based
                outputs[0] = RPR_TrackFX_GetEnabled(selectedTrack, Comp1FXindex)
                outputs[1] = RPR_TrackFX_GetEnabled(selectedTrack, Comp2FXindex)
                outputs[2] = RPR_TrackFX_GetEnabled(selectedTrack, EQFXindex)
                # Get signal levels - rms is just an approximation
                left = RPR_Track_GetPeakInfo(selectedTrack, 0)
                right = RPR_Track_GetPeakInfo(selectedTrack, 1)
                if (left + right) > 0.0:
                    rms = 0.7 * 20 * math.log10((left + right) / 2)
                else:
                    rms = 0.0
                # Get thresholds from compressors
                if outputs[0] and not outputs[1]:
                    value, t, fidx, pidx, minval, maxval = RPR_TrackFX_GetParam(selectedTrack, Comp1FXindex, 0, 0.0, 1.0)
                    threshold = 20 * math.log10(value)
                elif outputs[1]:
                    value, t, fidx, pidx, minval, maxval = RPR_TrackFX_GetParam(selectedTrack, Comp2FXindex, 0, 0.0, 1.0)
                    threshold = 20 * math.log10(value)
                else:
                    # Should really have the main limiter here...
                    threshold = -20.0
                # Red LED indicatees compressing
                redLED = rms  > (threshold + redThreshold)
                outputs[4] = redLED
                # Yellow LED indicates signal
                if (rms > yellThreshold) and not yellLED:
                    yellOnCount += 1
                    if yellOnCount >= yellOnDelay:
                        yellLED = True
                else:
                    yellOnCount = 0
                if (rms < yellThreshold) and yellLED:
                    yellOffCount += 1
                    if yellOffCount >= yellOffDelay:
                        yellLED = False
                else:
                    yellOffCount = 0
                outputs[3] = yellLED
                # Send state to outputs
                outputVal = 0
                if outputs[4]:
                    outputVal += 16
                if outputs[3]:
                    outputVal += 8
                if outputs[2]:
                    outputVal += 4
                if outputs[1]:
                    outputVal += 2
                if outputs[0]:
                    outputVal += 1
                # Convert to hex, zero fill and output
                outputStr = format(outputVal, 'x').zfill(2)
                try:
                    output_command = f"gpio writeall "
                    output_command += outputStr
                    output_command += "\r"
                    ser.write(output_command.encode())
                except:
                    errorTxt = "Failed to send outputs"
                    maskSent = False
            case 2:
                try:
                    # Send request for inputs
                    read_inputs_command = f"gpio readall\r"
                    ser.write(read_inputs_command.encode())
                except:
                    errorTxt = "Failed to send read inputs"
                    maskSent = False
            case 3:
                # Do nothing
                pass
            case 4:
                try:
                    # Read inputs
                    inputStr = ser.read_all().decode()
                    inputStr = inputStr[-5:-4]
                    # Inputs are pulled down when button pushed
                    if inputStr == "E":
                        inputs[0] = 0
                        inputs[1] = 0
                        inputs[2] = 0
                    elif inputStr == "C":
                        inputs[0] = 0
                        inputs[1] = 0
                        inputs[2] = 1
                    elif inputStr == "A":
                        inputs[0] = 0
                        inputs[1] = 1
                        inputs[2] = 0
                    elif inputStr == "6":
                        inputs[0] = 1
                        inputs[1] = 0
                        inputs[2] = 0
                    else:
                        inputs[0] = 0
                        inputs[1] = 0
                        inputs[2] = 0
                    # When inputs change, toggle and switch FX
                    if inputs[0] and not inputsMem[0]:
                        toggle[0] = not toggle[0]
                        try:
                            selectedTrack = RPR_GetTrack(0, TrackFXindex)
                            RPR_TrackFX_SetEnabled(selectedTrack, Comp1FXindex, toggle[0])
                        except:
                            errorTxt = "Failed to set track 10, FX 2"
                    elif inputs[1] and not inputsMem[1]:
                        toggle[1] = not toggle[1]
                        try:
                            selectedTrack = RPR_GetTrack(0, TrackFXindex)
                            RPR_TrackFX_SetEnabled(selectedTrack, Comp2FXindex, toggle[1])
                        except:
                            errorTxt = "Failed to set track 10, FX 3"
                    elif inputs[2] and not inputsMem[2]:
                        toggle[2] = not toggle[2]
                        try:
                            selectedTrack = RPR_GetTrack(0, TrackFXindex)
                            # 2 FX on here
                            RPR_TrackFX_SetEnabled(selectedTrack, EQFXindex, toggle[2])
                            RPR_TrackFX_SetEnabled(selectedTrack, WidthFXindex, toggle[2])
                        except:
                            errorTxt = "Failed to set track 10, FX 4 & 5"
                    inputsMem[0] = inputs[0]
                    inputsMem[1] = inputs[1]
                    inputsMem[2] = inputs[2]
                except:
                    errorTxt = "Failed to read inputs"
                    maskSent = False
                
        state += 1
        if not maskSent:
            state = 0
        elif state > 4:
            state = 1
    else:
        maskSent = False
        state = 0
        try:
            ser.close()
        except:
            pass
        openPort()
        
    RPR_defer("serLoop()")  # Schedule next run 

serLoop()


