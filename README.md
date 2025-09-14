# Raspberry Pi Camera GUI

This is a simple, yet powerful, graphical user interface (GUI) for the Raspberry Pi camera module, built using Python, PyQt5, and picamera2. It provides a clean, single-window interface for previewing, capturing, and recording from your Raspberry Pi camera.

## Features

- **Live Preview:** Displays a real-time video stream from the camera.  
- **Resolution Control:** Easily switch between different preview resolutions to balance frame rate and quality.  
- **Image Capture:** Capture still images in various formats, including JPEG, PNG, TIFF, and RAW (DNG).  
- **Video Recording:** Record videos in the MP4 format.  
- **Custom Cropping:** Draw a rectangle on the preview to crop your captured images to a specific area.  
- **Magnifier:** A movable magnification window for precise focusing and detailed inspection of the live feed.  

### Focus Controls

- **Autofocus:** A one-shot autofocus trigger for sharp shots.  
- **Continuous Focus:** Keeps the image in focus automatically.  
- **Manual Focus:** Manually adjust the lens position with a slider.  

- **Preview Rotation:** Rotate the live preview in 90-degree increments.  
- **Theme:** A toggleable dark mode for comfortable viewing in low-light conditions.  

## Requirements

To run this application, you will need:

- A Raspberry Pi with a compatible camera module (e.g., Camera Module 3).  
- The `picamera2` library, which requires a recent Raspberry Pi OS.  
- Python 3.  

## Dependencies

Install the required Python libraries using pip:

```bash
pip3 install PyQt5 numpy Pillow
pip3 install picamera2[gui]
