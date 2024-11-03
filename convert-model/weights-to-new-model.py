#run this in the new python environment (I made a .venv and did pip install --no-deps requirements.txt and then ran this file)
#had to change the layer sizes from what I thought (32,64,64,64 => 64,32,16,100) but the new model's output is identical to the old one

import tensorflow as tf
from tensorflow.keras import layers, models

# Define constants
IMG_DIM = 30  # Image dimension
class_names = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
L = len(class_names)  # Number of output classes, which is 26

# Define the model architecture (must match the old model architecture)
model = models.Sequential()
model.add(layers.Conv2D(64, (3, 3), activation='relu', input_shape=(IMG_DIM, IMG_DIM, 1)))
model.add(layers.MaxPooling2D((2, 2)))
model.add(layers.Conv2D(32, (3, 3), activation='relu'))
model.add(layers.MaxPooling2D((2, 2)))
model.add(layers.Conv2D(16, (3, 3), activation='relu'))

model.add(layers.Flatten())
model.add(layers.Dense(100, activation='relu'))
model.add(layers.Dense(L, activation="softmax"))

# Load the saved weights from the old environment
model.load_weights('/srv/boggle/model_weights.h5')

# Compile the model (optional, depends on use case)
model.compile(optimizer='adam',
              loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
              metrics=['accuracy'])

# Save the entire model in the new environment
model.save('/srv/boggle/new_model.h5')
