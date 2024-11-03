#run this in the old python environment (I just pasted it into the python console on the old docker image)

import tensorflow as tf
from tensorflow.keras import datasets, layers, models

# Load the existing model
model = tf.keras.models.load_model('/srv/boggle/model.h5')

# Save the weights
model.save_weights('/srv/boggle/model_weights.h5')
