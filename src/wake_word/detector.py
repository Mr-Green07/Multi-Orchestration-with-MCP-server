import logging
logging.getLogger().setLevel(logging.ERROR)

import pyaudio
import numpy as np 
# pyrefly: ignore [missing-import]
import openwakeword as oww
# pyrefly: ignore [missing-import]
from openwakeword.model import Model

print("Checking for pre-trained models...")
oww.utils.download_models()


print("Loading models...")
oww_model = Model(wakeword_models=["hey_mycroft"])

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1280

audio = pyaudio.PyAudio()
mic_stream = audio.open(format= FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
print("Listening for 'hey, jarvis'... (press Ctrl + C to stop)")


try:
    while True:
        audio_chunk = np.frombuffer(mic_stream.read(CHUNK, exception_on_overflow = False), dtype = np.int16)
        volume = np.abs(audio_chunk).mean()
        print(f"mic volume: {volume:.0f}", end = "\r")
        prediction = oww_model.predict(audio_chunk)

        for model_name, score in prediction.items():
            if score > 0.1:
                print(f"Wake word detected: {model_name} -confidence: {score:.2f}")

                oww_model.reset()

except KeyboardInterrupt:
    print("Stopping...")

finally:
    mic_stream.stop_stream()
    mic_stream.close()
    audio.terminate()

