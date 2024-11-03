import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BoggleCVPipeline import processImage, BoggleError
# make sure to change in BoggleCVPipeline: MODEL_FILE="/srv/boggle/new_model.h5"

img = '/srv/boggle/upload-board/20210724_203424.jpg'
lettersGuessed, confidence = processImage(img)
print(lettersGuessed, confidence)

with open(img + '.txt') as f:
    contents = f.read()
    lettersSaved = contents.split(';')[1].strip()
    print(lettersGuessed == lettersSaved, lettersGuessed, lettersSaved)
    assert lettersGuessed == lettersSaved

#upgraded model from tensorflow 2.11.2 to 2.18.0
