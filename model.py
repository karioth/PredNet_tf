from PredNet import *
import tensorflow as tf
import os
import numpy as np
from tensorflow.keras import models

# PredNet model definition
class PredNetModel(models.Model):
    """
    A Keras Model implementation of the PredNet architecture, adapted for flexible use in both training and inference with custom loss calculations.

    Args:
        stack_sizes (list): Sizes of the feature maps (channels) for each layer of the network.
        R_stack_sizes (list): Sizes of the recurrent state of each layer (channels of the representation units).
        A_filt_sizes (list): Filter sizes for the target computation layers.
        Ahat_filt_sizes (list): Filter sizes for the prediction computation layers.
        R_filt_sizes (list): Filter sizes for the representation computation layers.
        layer_loss_weights (array): Weights for the loss at each layer, used for calculating weighted loss.
        time_loss_weights (array): Weights over time steps for calculating the loss over time.
        **kwargs: Additional keyword arguments for the TensorFlow Keras model.

    Attributes:
        prednet (PredNet): The core PredNet architecture encapsulated as a Keras RNN.
        timeDense (TimeDistributed): A layer to apply layer loss weighting over time.
        flatten (Flatten): Flattens the output to calculate a weighted loss.
        dense (Dense): Computes a final scalar error to guide training.
    """
    def __init__(self, stack_sizes, R_stack_sizes, A_filt_sizes, Ahat_filt_sizes, R_filt_sizes, layer_loss_weights, time_loss_weights,**kwargs):
        super(PredNetModel, self).__init__(**kwargs)
        
        self.stack_sizes = stack_sizes
        self.R_stack_sizes = R_stack_sizes
        self.A_filt_sizes = A_filt_sizes
        self.Ahat_filt_sizes = Ahat_filt_sizes
        self.R_filt_sizes = R_filt_sizes
        
        # Initialize PredNet cells based on provided configurations
        self.cells = [
                PredNet_Cell(
                    stack_size=stack_size,
                    R_stack_size=R_stack_size,
                    A_filt_size=A_filt_size,
                    Ahat_filt_size=Ahat_filt_size,
                    R_filt_size=R_filt_size)

                for stack_size, R_stack_size, A_filt_size, Ahat_filt_size, R_filt_size in zip(
                    self.stack_sizes, self.R_stack_sizes, self.A_filt_sizes, self.Ahat_filt_sizes, self.R_filt_sizes)] # initialize the cells according to the hyperparameters.

        # self.nb_layers = len(stack_sizes)
        self.layer_loss_weights = layer_loss_weights # weighting for each layer in final loss.
        self.time_loss_weights = time_loss_weights # weighting for the timesteps in final loss.

        # Set up the PredNet RNN architecture
        self.prednet = PredNet(cell = self.cells, return_sequences = True) # pass the cells to the PredNet(RNN) class

        #Layers for additional error computations for weighted loss during traning
        self.timeDense = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1, trainable=False), weights=[self.layer_loss_weights, np.zeros(1)], trainable=False)
        self.flatten =  tf.keras.layers.Flatten()
        self.dense = tf.keras.layers.Dense(1, weights=[self.time_loss_weights, np.zeros(1)], trainable=False)


    @tf.function
    def call(self, input, training=False):
        x = self.prednet(input, training=training)
        return x

    @tf.function
    def train_step(self, data):
        """
        Overrides the default train_step to integrate custom loss calculation, so it works with custom training loops and model.fit().
        Thanks to this, the PredNet can work on all modes seemlesly without having to define a new architecture when changing to inference/prediction mode.
        """
        x, target = data
        with tf.GradientTape() as tape:
            all_error = self(x, training = True) #set traning = True to get errors as output

            #apply the additional error computations
            time_error = self.timeDense(all_error)
            flattened = self.flatten(time_error)
            prediction_error = self.dense(flattened)

            loss = self.compute_loss(y = target, y_pred = prediction_error) # target is a 0 initialized array reflecting the self-supervided goal of minimizing overall prediction error.

            
        gradients = tape.gradient(loss, self.trainable_variables)
        self.optimizer.apply_gradients(zip(gradients, self.trainable_variables))
        
        for metric in self.metrics:
            if metric.name == "loss":
                metric.update_state(loss)
            else:
                metric.update_state(target, prediction_error)
        
        return {m.name: m.result() for m in self.metrics}
    
    @tf.function
    def test_step(self, data):
        """
        Custom test_step to evaluate the model during validation, using the same custom error computation as in training.
        """
        # Similarly for the test_step. Traditionally traning would be set to false, but since here we use it to change the output to error, we set to true to evaluate loss performance.
        x_val, target_val = data
        all_error_val = self(x_val, training = True)
        #apply the additional error computations
        time_error = self.timeDense(all_error_val)
        flattened = self.flatten(time_error)
        prediction_error_val = self.dense(flattened)

        self.compute_loss(y=target_val, y_pred = prediction_error_val)
       
        for metric in self.metrics:
            if metric.name != "loss":
                metric.update_state(y, y_pred)
        
        return {m.name: m.result() for m in self.metrics}
    
        
        
