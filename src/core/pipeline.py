cap = MicCapture(cfg)
wake_rb, vad_rb = Rebuffer(1280), Rebuffer(512)   # oWW / Silero frame sizes

for chunk in cap.chunks():                         # runs on the wake/vad thread
    for frame in wake_rb.push(chunk):
        if wakeword.process(frame):                # -> WAKE event
            stt_seed = cap.preroll.snapshot()      # the second before the wake
    for frame in vad_rb.push(chunk):
        vad.process(frame)                         # only consulted while LISTENING